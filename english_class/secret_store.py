"""Authenticated encryption for the public service's provider credentials.

The separately backed-up master key protects a copied database. It does not
protect against an attacker who can read this process or both files.
"""
from __future__ import annotations

import json
import os
import stat
import tempfile
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

ENCRYPTED_PREFIX = 'enc:v1:'


class SecretStorageError(RuntimeError):
    """A credential cannot be safely opened; never replace it with a new key."""


def private_directory(path: Path) -> None:
    """Create only missing directories as 0700; preserve existing parents."""
    if path.is_dir():
        return
    if not path.parent.is_dir():
        private_directory(path.parent)
    try:
        path.mkdir(mode=0o700)
    except FileExistsError:
        if not path.is_dir():
            raise


def private_file(path: Path, *, create: bool = False, read_only: bool = False) -> int:
    """Return a private regular-file descriptor without following a final symlink."""
    flags = (os.O_RDONLY if read_only else os.O_RDWR) | getattr(os, 'O_NOFOLLOW', 0)
    if create:
        flags |= os.O_CREAT
    fd = os.open(path, flags, 0o600)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise SecretStorageError('密钥和数据库必须是普通文件')
        if stat.S_IMODE(os.fstat(fd).st_mode) != 0o600:
            os.fchmod(fd, 0o600)
    except BaseException:
        os.close(fd)
        raise
    return fd


def secure_database_files(path: Path) -> None:
    private_directory(path.parent)
    for suffix in ('', '-wal', '-shm', '-journal'):
        target = Path(str(path) + suffix)
        try:
            current = target.lstat()
        except FileNotFoundError:
            if not suffix:
                # The migration sidecar lock serializes Store initialization.
                # Open only a newly created inode, never another descriptor for
                # an existing SQLite file whose process-level locks are active.
                try:
                    fd = os.open(target, os.O_RDWR | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
                except FileExistsError:
                    secure_database_files(path)
                    return
                try:
                    os.fchmod(fd, 0o600)
                finally:
                    os.close(fd)
            continue
        if not stat.S_ISREG(current.st_mode):
            raise SecretStorageError('数据库及其辅助文件必须是普通文件，不得使用符号链接')
        # POSIX record locks are released when this process closes *any* file
        # descriptor for their inode, including DB/WAL/SHM. Do not open/close
        # these existing files merely to inspect or adjust permissions.
        if stat.S_IMODE(current.st_mode) != 0o600:
            os.chmod(target, 0o600, follow_symlinks=False)


class CredentialCipher:
    def __init__(self, path: Path, *, required: bool):
        self.path = Path(path)
        try:
            if not self.path.exists() and not self.path.is_symlink():
                if required:
                    raise SecretStorageError('模型主密钥文件缺失，请恢复原主密钥；不会生成新密钥覆盖已有密文')
                self._create_key()
            fd = private_file(self.path, read_only=True)
            try:
                with os.fdopen(fd, 'rb') as stream:
                    key = stream.read(1024).strip()
                self._fernet = Fernet(key)
            except (ValueError, TypeError):
                raise SecretStorageError('模型主密钥文件无效，请从独立备份恢复；未替换已有文件') from None
        except OSError as exc:
            raise SecretStorageError('无法安全读取模型主密钥文件，请检查文件路径、所有者与0600权限') from exc

    def _create_key(self) -> None:
        private_directory(self.path.parent)
        # Publish only a complete, flushed key. link() never overwrites another
        # process's key, unlike replace(); the temporary file is always private.
        fd, temporary = tempfile.mkstemp(prefix='.' + self.path.name + '-', dir=self.path.parent)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(Fernet.generate_key() + b'\n')
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, self.path)
                directory_fd = os.open(self.path.parent, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            except FileExistsError:
                pass
        finally:
            os.unlink(temporary)

    def encrypt(self, student_id: str, api_key: str) -> str:
        value = json.dumps({'student_id': student_id, 'api_key': api_key}, ensure_ascii=False,
                           separators=(',', ':')).encode('utf-8')
        return ENCRYPTED_PREFIX + self._fernet.encrypt(value).decode('ascii')

    def decrypt(self, student_id: str, value: str) -> str:
        try:
            if not value.startswith(ENCRYPTED_PREFIX):
                raise ValueError('unexpected credential format')
            plaintext = self._fernet.decrypt(value[len(ENCRYPTED_PREFIX):].encode('ascii'))
            record = json.loads(plaintext)
            if not isinstance(record, dict) or record.get('student_id') != student_id or not isinstance(record.get('api_key'), str):
                raise ValueError('credential does not belong to this student')
            return record['api_key']
        except (InvalidToken, ValueError, TypeError, UnicodeError):
            raise SecretStorageError('无法解密已保存的模型密钥：主密钥不匹配或密文损坏，请恢复原主密钥；未改写密文') from None
