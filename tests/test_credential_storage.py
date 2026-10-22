"""Real SQLite/key-file regressions using fictional credentials only."""
from __future__ import annotations

import base64
import os
import sqlite3
import stat
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from english_class.dictionary import Dictionary
from english_class.models import LearningConfig
from english_class.store import RateLimit, Store, token_hash


KEY = 'fictional-provider-secret-never-a-real-account-87654321'
OLD_KEY = 'fictional-previous-secret-for-migration-12345678'


def _raw_key(path):
    with sqlite3.connect(path) as con:
        return con.execute('SELECT api_key FROM student_llm WHERE student_id=?', ('s001',)).fetchone()[0]


def _disk_contains(path, secret):
    return any(secret.encode() in item.read_bytes()
               for item in path.parent.glob(path.name + '*') if item.is_file() and not item.name.endswith('.key'))


def _legacy(path, *, count=19):
    """A pre-upgrade database, including an obsolete key on an old SQLite page."""
    con = sqlite3.connect(path)
    try:
        con.execute('PRAGMA journal_mode=WAL')
        con.execute('PRAGMA secure_delete=OFF')
        con.executescript('''
            CREATE TABLE students(id TEXT PRIMARY KEY, config TEXT NOT NULL);
            CREATE TABLE credentials(hash TEXT PRIMARY KEY, student_id TEXT NOT NULL, role TEXT NOT NULL);
            CREATE TABLE student_llm(student_id TEXT PRIMARY KEY, base_url TEXT NOT NULL, model TEXT NOT NULL,
                api_key TEXT NOT NULL, updated_at TEXT NOT NULL, last_status TEXT NOT NULL DEFAULT '',
                last_error TEXT NOT NULL DEFAULT '', last_used_at TEXT NOT NULL DEFAULT '', thinking INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE scene_generation_usage(student_id TEXT NOT NULL, day TEXT NOT NULL, count INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY(student_id,day));
        ''')
        con.execute('INSERT INTO students VALUES (?,?)', ('s001', LearningConfig(grade=1, semester=1).model_dump_json()))
        con.execute('INSERT INTO credentials VALUES (?,?,?)', (token_hash('fictional-parent-token-long'), 's001', 'parent'))
        con.execute('INSERT INTO student_llm VALUES (?,?,?,?,?,?,?,?,?)',
                    ('s001', 'https://models.example/v1', 'fixture-model', OLD_KEY, 'old', 'ok', '', 'old', 1))
        con.commit()
        con.execute('UPDATE student_llm SET api_key=? WHERE student_id=?', (KEY, 's001'))
        # Simulate older deleted credential pages, which updating the one live
        # key with secure_delete enabled cannot erase retroactively.
        con.execute('CREATE TABLE retired_credentials(value TEXT)')
        con.execute('INSERT INTO retired_credentials VALUES (?)', (OLD_KEY * 200,))
        con.commit()
        con.execute('DROP TABLE retired_credentials')
        day = datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat()
        con.execute('INSERT INTO scene_generation_usage VALUES (?,?,?)', ('s001', day, count))
        con.commit()
    finally:
        con.close()


def _save(store):
    store.add_student('s001', 'fictional-parent-token-long', 'fictional-brain-token-long')
    store.save_llm('s001', 'https://models.example/v1', 'fixture-model', KEY, True)


def test_saved_provider_key_is_encrypted_on_disk_and_survives_restart(db):
    _save(db)
    assert _raw_key(db.path) != KEY
    assert not _disk_contains(db.path, KEY)
    assert db.llm('s001')['api_key'] == KEY
    assert Store(db.path, db.dictionary).llm('s001')['api_key'] == KEY


def test_database_and_key_permissions_do_not_depend_on_shell_umask(tmp_path, dictionary_path):
    parent = tmp_path / 'existing-directory'
    parent.mkdir(mode=0o755)
    path = parent / 'new-private-directory' / 'class.sqlite3'
    saved = os.umask(0o022)
    try:
        store = Store(path, Dictionary(dictionary_path))
        _save(store)
        with store.connect() as con:
            con.execute('UPDATE student_llm SET last_status=?', ('ok',))
            for item in path.parent.glob('class.sqlite3*'):
                assert stat.S_IMODE(item.stat().st_mode) == 0o600
    finally:
        os.umask(saved)
    assert stat.S_IMODE(parent.stat().st_mode) == 0o755
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert Path(str(path) + '.key').is_file()


def test_restart_tightens_existing_database_and_key_permissions(db):
    _save(db)
    key_path = Path(str(db.path) + '.key')
    db.path.chmod(0o666)
    assert key_path.exists()
    key_path.chmod(0o644)
    Store(db.path, db.dictionary)
    assert stat.S_IMODE(db.path.stat().st_mode) == 0o600
    assert stat.S_IMODE(key_path.stat().st_mode) == 0o600


def test_missing_master_key_fails_closed_without_replacing_ciphertext(db):
    _save(db)
    original = _raw_key(db.path)
    key_path = Path(str(db.path) + '.key')
    assert key_path.exists()
    key_path.unlink()
    with pytest.raises(RuntimeError, match='主密钥'):
        Store(db.path, db.dictionary)
    assert not key_path.exists()
    assert _raw_key(db.path) == original


@pytest.mark.parametrize('replacement', [base64.urlsafe_b64encode(b'Z' * 32), b'invalid-master-key-file'])
def test_wrong_or_invalid_master_key_does_not_modify_stored_credentials(db, replacement):
    _save(db)
    original = _raw_key(db.path)
    key_path = Path(str(db.path) + '.key')
    key_path.write_bytes(replacement)
    with pytest.raises(RuntimeError, match='主密钥'):
        Store(db.path, db.dictionary)
    assert key_path.read_bytes() == replacement
    assert _raw_key(db.path) == original


def test_corrupt_ciphertext_is_rejected_instead_of_being_treated_as_a_new_plaintext_key(db):
    _save(db)
    with db.connect() as con:
        con.execute('UPDATE student_llm SET api_key=?', ('enc:v1:corrupted-ciphertext',))
    with pytest.raises(RuntimeError, match='密钥'):
        Store(db.path, db.dictionary)
    assert _raw_key(db.path) == 'enc:v1:corrupted-ciphertext'


def test_legacy_credentials_migrate_without_losing_identity_config_or_attempts(tmp_path, dictionary_path):
    path = tmp_path / 'legacy.sqlite3'
    _legacy(path)
    assert _disk_contains(path, KEY)
    assert _disk_contains(path, OLD_KEY)
    store = Store(path, Dictionary(dictionary_path))
    assert store.llm('s001')['api_key'] == KEY
    assert store.llm('s001')['thinking'] is True
    assert store.llm('s001')['allow_platform_fallback'] is False
    assert store.authenticate('fictional-parent-token-long') == {'student_id': 's001', 'role': 'parent'}
    assert store.config('s001')['grade'] == 1
    usage = store.scene_generation_usage('s001')
    assert usage['attempts'] == 19 and usage['successes'] == 0 and usage['remaining'] == 1
    assert usage['successes_since_version'] == '0.3.4'
    assert not _disk_contains(path, KEY)
    assert not _disk_contains(path, OLD_KEY)
    assert Store(path, store.dictionary).llm('s001')['api_key'] == KEY


def test_migration_waits_for_legacy_readers_and_can_finish_after_retry(tmp_path, dictionary_path):
    path = tmp_path / 'busy-legacy.sqlite3'
    _legacy(path)
    reader = sqlite3.connect(path)
    try:
        reader.execute('BEGIN')
        reader.execute('SELECT api_key FROM student_llm').fetchall()
        with pytest.raises(RuntimeError, match='迁移|清理'):
            Store(path, Dictionary(dictionary_path))
        assert Path(str(path) + '.key').exists()
    finally:
        reader.close()
    store = Store(path, Dictionary(dictionary_path))
    assert store.llm('s001')['api_key'] == KEY
    assert not _disk_contains(path, KEY)


def test_configured_master_key_path_is_separate_and_explicit_path_takes_priority(tmp_path, dictionary_path, monkeypatch):
    path = tmp_path / 'database' / 'class.sqlite3'
    from_env = tmp_path / 'service-secrets' / 'llm.key'
    explicit = tmp_path / 'explicit-secrets' / 'llm.key'
    monkeypatch.setenv('LLM_SECRET_KEY_FILE', str(from_env))
    store = Store(path, Dictionary(dictionary_path), credential_key_path=explicit)
    _save(store)
    assert explicit.is_file() and not from_env.exists()
    assert not Path(str(path) + '.key').exists()
    assert Store(path, store.dictionary, credential_key_path=explicit).llm('s001')['api_key'] == KEY
    other = Store(tmp_path / 'other.sqlite3', store.dictionary)
    assert from_env.is_file()
    assert other.credential_key_path == from_env


def test_existing_external_master_key_needs_only_read_access(tmp_path, dictionary_path, monkeypatch):
    from english_class import secret_store
    key_path = tmp_path / 'read-only-secrets' / 'llm.key'
    path = tmp_path / 'class.sqlite3'
    store = Store(path, Dictionary(dictionary_path), credential_key_path=key_path)
    _save(store)
    real_open = secret_store.os.open
    real_fchmod = secret_store.os.fchmod
    key_inode = key_path.stat().st_ino
    def protected_open(path_arg, flags, *args, **kwargs):
        if Path(path_arg) == key_path and flags & os.O_ACCMODE != os.O_RDONLY:
            raise PermissionError('simulated systemd ProtectSystem=strict for external master key')
        return real_open(path_arg, flags, *args, **kwargs)
    def protected_chmod(fd, mode):
        if os.fstat(fd).st_ino == key_inode:
            raise PermissionError('simulated read-only external secrets directory')
        return real_fchmod(fd, mode)
    monkeypatch.setattr(secret_store.os, 'open', protected_open)
    monkeypatch.setattr(secret_store.os, 'fchmod', protected_chmod)
    reopened = Store(path, store.dictionary, credential_key_path=key_path)
    assert reopened.llm('s001')['api_key'] == KEY


def test_encrypted_key_cannot_be_copied_to_a_different_student(db):
    _save(db)
    db.add_student('s002', 'fictional-other-parent-token', 'fictional-other-brain-token')
    db.save_llm('s002', 'https://models.example/v1', 'fixture-model', OLD_KEY)
    with db.connect() as con:
        con.execute('UPDATE student_llm SET api_key=(SELECT api_key FROM student_llm WHERE student_id=?) WHERE student_id=?', ('s001', 's002'))
    with pytest.raises(RuntimeError, match='密钥'):
        db.llm('s002')


def test_concurrent_startup_migrates_a_legacy_database_once(tmp_path, dictionary_path):
    path = tmp_path / 'concurrent.sqlite3'
    _legacy(path)
    dictionary = Dictionary(dictionary_path)
    with ThreadPoolExecutor(max_workers=4) as pool:
        stores = list(pool.map(lambda _: Store(path, dictionary), range(4)))
    assert all(store.llm('s001')['api_key'] == KEY for store in stores)
    with sqlite3.connect(path) as con:
        versions = con.execute('SELECT version FROM schema_migrations').fetchall()
    assert versions and len(versions) == len(set(versions))
    assert not _disk_contains(path, KEY)


@pytest.mark.parametrize('action', ['permissions', 'migration_lock'])
def test_file_security_operations_do_not_release_active_sqlite_transaction_locks(db, action):
    """Closing another descriptor for a DB/WAL/SHM inode can drop POSIX locks."""
    from english_class.migrations import migration_lock
    from english_class.secret_store import secure_database_files
    _save(db)
    if action == 'migration_lock':
        with db.connect() as con:
            con.execute('PRAGMA journal_mode=DELETE')
    child = '''
import sqlite3, sys
con=sqlite3.connect(sys.argv[1],timeout=.05)
try:
    con.execute('BEGIN IMMEDIATE')
    con.execute("UPDATE students SET brain_last_seen='child-committed' WHERE id='s001'")
    con.commit()
    print('committed')
except sqlite3.OperationalError:
    print('blocked')
finally:
    con.close()
'''
    def contender():
        result = subprocess.run([sys.executable, '-c', child, str(db.path)], capture_output=True, text=True, timeout=3)
        assert result.returncode == 0, result.stderr
        return result.stdout.strip()
    with db.connect() as con:
        con.execute('BEGIN IMMEDIATE')
        con.execute("UPDATE students SET brain_last_seen='parent-uncommitted' WHERE id='s001'")
        assert contender() == 'blocked'
        if action == 'permissions':
            for suffix in ('', '-wal', '-shm', '-journal'):
                target = Path(str(db.path) + suffix)
                if target.exists():
                    target.chmod(0o644)
            secure_database_files(db.path)
        else:
            with migration_lock(db.path):
                pass
        assert con.in_transaction is True
        assert contender() == 'blocked'
    assert db.status('s001')['brain_last_seen'] == 'parent-uncommitted'


def test_replacing_and_clearing_student_key_keeps_plaintext_out_of_database(db):
    _save(db)
    before = _raw_key(db.path)
    db.save_llm('s001', 'https://models.example/v1', 'new-model', OLD_KEY, False, True)
    assert _raw_key(db.path) != before
    row = db.llm('s001')
    assert row['api_key'] == OLD_KEY and row['allow_platform_fallback'] is True
    assert not _disk_contains(db.path, KEY) and not _disk_contains(db.path, OLD_KEY)
    db.clear_llm('s001')
    assert db.llm('s001') is None
    assert Store(db.path, db.dictionary).llm('s001') is None


def test_scene_usage_counts_attempts_and_confirmed_successes_separately(db):
    _save(db)
    first = db.reserve_scene_generation('s001')
    db.reserve_scene_generation('s001')
    db.mark_scene_generation_success('s001', first)
    usage = db.scene_generation_usage('s001')
    assert usage['attempts'] == 2 and usage['successes'] == 1 and usage['remaining'] == 18
    assert 'failures' not in usage
    assert usage['day'] == first and usage['limit'] == 20


def test_scene_success_is_recorded_against_reserved_day_across_midnight(db):
    _save(db)
    db.today = lambda: '2026-10-21'
    reserved_day = db.reserve_scene_generation('s001')
    db.today = lambda: '2026-10-22'
    db.reserve_scene_generation('s001')
    db.mark_scene_generation_success('s001', reserved_day)
    assert db.scene_generation_usage('s001')['successes'] == 0
    with db.connect() as con:
        assert con.execute('SELECT success_count FROM scene_generation_usage WHERE day=?',
                           (reserved_day,)).fetchone()[0] == 1


def test_concurrent_scene_reservations_cannot_exceed_attempt_limit(db):
    _save(db)
    def reserve(_):
        try:
            db.reserve_scene_generation('s001', limit=3)
            return 'accepted'
        except RateLimit as exc:
            assert '请求3次' in str(exc) and '失败' in str(exc)
            return 'limited'
    with ThreadPoolExecutor(max_workers=6) as pool:
        result = list(pool.map(reserve, range(8)))
    assert result.count('accepted') == 3 and result.count('limited') == 5
    assert db.scene_generation_usage('s001', limit=3)['remaining'] == 0
