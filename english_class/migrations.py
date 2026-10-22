"""Small serialized SQLite upgrades, including retryable credential cleanup."""
from __future__ import annotations

import fcntl
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from .secret_store import CredentialCipher, ENCRYPTED_PREFIX, SecretStorageError, private_file


@contextmanager
def migration_lock(path: Path):
    # Covers the post-transaction VACUUM/checkpoint as well as the SQL changes.
    # BEGIN IMMEDIATE below remains the database-level schema/write lock.
    # Never open/close the database inode for this advisory lock: doing so can
    # release another connection's SQLite POSIX record locks in this process.
    fd = private_file(Path(str(path) + '.migration.lock'), create=True)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _add_columns(con, table, columns):
    existing = {row['name'] for row in con.execute(f'PRAGMA table_info({table})')}
    for name, kind in columns:
        if name not in existing:
            con.execute(f'ALTER TABLE {table} ADD COLUMN {name} {kind}')


def _original_schema(con):
    statements = [
        'CREATE TABLE IF NOT EXISTS students (id TEXT PRIMARY KEY, config TEXT NOT NULL)',
        "CREATE TABLE IF NOT EXISTS credentials (hash TEXT PRIMARY KEY, student_id TEXT NOT NULL REFERENCES students(id), role TEXT NOT NULL CHECK(role IN ('parent','brain')))",
        'CREATE TABLE IF NOT EXISTS progress (student_id TEXT NOT NULL REFERENCES students(id), word_id TEXT NOT NULL, status INTEGER NOT NULL DEFAULT 0 CHECK(status BETWEEN 0 AND 2), unclear_count INTEGER NOT NULL DEFAULT 0, last_practiced_date TEXT NOT NULL, updated_at TEXT NOT NULL, PRIMARY KEY(student_id,word_id))',
        "CREATE TABLE IF NOT EXISTS student_llm (student_id TEXT PRIMARY KEY REFERENCES students(id), base_url TEXT NOT NULL, model TEXT NOT NULL, api_key TEXT NOT NULL, updated_at TEXT NOT NULL, last_status TEXT NOT NULL DEFAULT '', last_error TEXT NOT NULL DEFAULT '', last_used_at TEXT NOT NULL DEFAULT '')",
        'CREATE TABLE IF NOT EXISTS events (student_id TEXT NOT NULL REFERENCES students(id), event_key TEXT NOT NULL, fingerprint TEXT NOT NULL, result TEXT NOT NULL, PRIMARY KEY(student_id,event_key))',
        'CREATE TABLE IF NOT EXISTS scene_generation_usage (student_id TEXT NOT NULL REFERENCES students(id), day TEXT NOT NULL, count INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(student_id,day))',
    ]
    for statement in statements:
        con.execute(statement)
    _add_columns(con, 'progress', [(name, 'INTEGER NOT NULL DEFAULT 0')
                                  for name in ('valid_count', 'used_word_count', 'imitated_count')])
    _add_columns(con, 'students', [('pi_last_seen', 'TEXT'), ('brain_last_seen', 'TEXT'),
                                  ('pi_ssh_ok', 'INTEGER'), ('pi_ssh_checked_at', 'TEXT')])
    _add_columns(con, 'student_llm', [('thinking', 'INTEGER NOT NULL DEFAULT 0')])


def _record(con, version):
    con.execute("INSERT INTO schema_migrations(version,applied_at) VALUES (?,strftime('%Y-%m-%dT%H:%M:%fZ','now'))", (version,))


def migrate(con: sqlite3.Connection, key_path: Path) -> CredentialCipher:
    con.execute('PRAGMA journal_mode=WAL')
    con.execute('BEGIN IMMEDIATE')
    try:
        con.execute('CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)')
        versions = {row['version'] for row in con.execute('SELECT version FROM schema_migrations')}
        if any(version > 3 for version in versions):
            raise SecretStorageError('数据库由更新版本迁移，请使用对应版本；未更改已有数据')
        if 1 not in versions:
            _original_schema(con)
            _record(con, 1)
        rows = con.execute('SELECT student_id,api_key FROM student_llm').fetchall()
        cipher = CredentialCipher(key_path, required=2 in versions or any(row['api_key'].startswith(ENCRYPTED_PREFIX) for row in rows))
        # Check every encrypted row before any credential update. A wrong key
        # or one damaged row must not cause a partially re-encrypted database.
        for row in rows:
            if 2 in versions or row['api_key'].startswith(ENCRYPTED_PREFIX):
                cipher.decrypt(row['student_id'], row['api_key'])
        if 2 not in versions:
            _add_columns(con, 'student_llm', [('allow_platform_fallback', 'INTEGER NOT NULL DEFAULT 0')])
            _add_columns(con, 'scene_generation_usage', [('success_count', 'INTEGER NOT NULL DEFAULT 0')])
            for row in rows:
                if not row['api_key'].startswith(ENCRYPTED_PREFIX):
                    con.execute('UPDATE student_llm SET api_key=? WHERE student_id=?',
                                (cipher.encrypt(row['student_id'], row['api_key']), row['student_id']))
            _record(con, 2)
        con.commit()
    except BaseException:
        con.rollback()
        raise

    if 3 not in versions:
        # secure_delete (set on Store connections) overwrites updated cells;
        # VACUUM also rebuilds legacy free pages. The final TRUNCATE checkpoint
        # removes older plaintext WAL frames. Old backups/snapshots are outside
        # this database operation and must be handled separately by the owner.
        try:
            con.execute('PRAGMA busy_timeout=1000')
            con.execute('VACUUM')
            result = con.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()
            if result[0] != 0 or result[1] != 0:
                raise SecretStorageError('模型密钥迁移后的WAL清理被占用，请停止旧服务或数据库读取连接后重启；尚未确认清理完成')
            con.execute('BEGIN IMMEDIATE')
            _record(con, 3)
            con.commit()
        except sqlite3.Error as exc:
            con.rollback()
            raise SecretStorageError('模型密钥迁移清理未完成，请停止旧服务或数据库读取连接后重启') from exc
        finally:
            con.execute('PRAGMA busy_timeout=15000')
    return cipher
