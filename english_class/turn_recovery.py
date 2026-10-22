"""Short-lived, private recovery journal for one student's serial voice turns.

Persist an IO intent *before* a progress request and its result before continuing.
On retry replay completed reads/judgments; an unconfirmed progress write retains
the exact idempotency key and payload. This closes the commit/reply gap without
claiming a transaction across HTTP and SQLite. No provider credentials or raw
audio are stored here. This is a bounded recovery cache, not a lesson archive.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import time
import uuid
from pathlib import Path

from . import __version__
from .client import ServiceError

RECOVERY_TTL_SECONDS = 6 * 60 * 60
MAX_REPLIES = 128
FORMAT_VERSION = 1


def fingerprint(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':')).encode()).hexdigest()


def private_json_write(path: Path, data) -> None:
    """Atomic replacement; old complete state survives a failed write."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with os.fdopen(os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w', encoding='utf-8') as handle:
            json.dump(data, handle, ensure_ascii=False, separators=(',', ':'))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
        try: os.fsync(directory)
        finally: os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


class TurnRecovery:
    def __init__(self, path=None, *, wall=time.time):
        self.path = Path(path) if path else None
        self.wall = wall
        self.cursor = 0
        self.data = {'version': FORMAT_VERSION, 'pending': None, 'replies': {},
                     'state': None, 'question_id': uuid.uuid4().hex, 'saved_at': wall()}
        if self.path and self.path.exists():
            try:
                loaded = json.loads(self.path.read_text(encoding='utf-8'))
                if (loaded.get('version') != FORMAT_VERSION or not isinstance(loaded.get('replies'), dict)
                        or not isinstance(loaded.get('question_id'), str)):
                    raise ValueError('invalid recovery format')
                if 0 <= wall() - float(loaded['saved_at']) <= RECOVERY_TTL_SECONDS:
                    self.data = loaded
                else:
                    self.path.unlink(missing_ok=True)
            except (OSError, ValueError, TypeError, KeyError) as exc:
                # Silently dropping an unreadable pending write could repeat evidence.
                raise ServiceError('回合恢复文件不可用；请先检查状态目录，未处理新的回答') from exc

    @property
    def pending(self):
        return self.data['pending']

    @property
    def question_id(self):
        return self.data['question_id']

    @property
    def needs_upgrade_close(self):
        return self.pending is not None and self.pending.get('executor_version') != __version__

    def save(self, candidate=None):
        candidate = self.data if candidate is None else candidate
        if self.path:
            try: private_json_write(self.path, candidate)
            except OSError as exc:
                raise ServiceError('无法保存回合恢复状态；本轮暂停，请检查状态目录') from exc
        self.data = candidate

    def prune(self):
        cutoff = self.wall() - RECOVERY_TTL_SECONDS
        kept = {k: v for k, v in self.data['replies'].items() if v['at'] >= cutoff}
        changed = len(kept) != len(self.data['replies'])
        self.data['replies'] = kept
        return changed

    def expired(self):
        created = self.pending['at'] if self.pending else self.data['saved_at']
        return self.wall() - created > RECOVERY_TTL_SECONDS

    def reset(self):
        if self.path:
            try: self.path.unlink(missing_ok=True)
            except OSError as exc: raise ServiceError('无法清理到期回合恢复文件') from exc
        self.data = {'version': FORMAT_VERSION, 'pending': None, 'replies': {}, 'state': None,
                     'question_id': uuid.uuid4().hex, 'saved_at': self.wall()}

    def lookup(self, key, digest):
        self.prune()
        previous = self.data['replies'].get(key)
        if previous:
            if previous['fingerprint'] != digest:
                raise ValueError('相同请求编号不能用于不同内容')
            return copy.deepcopy(previous['reply'])
        if self.pending and self.pending['request_id'] == key and self.pending['fingerprint'] != digest:
            raise ValueError('相同请求编号不能用于不同内容')
        return None

    def begin(self, key, digest, tutor):
        if self.pending:
            if self.pending['request_id'] != key:
                raise ValueError('上一回合尚未确认；请先用原请求编号恢复，或明确结束练习')
            if self.pending['fingerprint'] != digest:
                raise ValueError('相同请求编号不能用于不同内容')
            tutor.restore_state(copy.deepcopy(self.pending['before']))
        else:
            self.data['pending'] = {'request_id': key, 'fingerprint': digest, 'at': self.wall(),
                                    'executor_version': __version__, 'before': tutor.export_state(), 'operations': []}
            self.data['saved_at'] = self.wall()
            self.save()
        self.cursor = 0

    async def settle_records(self, io):
        """Confirm old write intents without replaying changed model/ASR code."""
        for index, operation in enumerate(self.pending['operations']):
            if operation['method'] != 'record' or operation['done']:
                continue
            # Exact original payload and key: a committed response may have been
            # lost. Store.record deduplicates the retry; never infer a new result.
            result = await io.record(*copy.deepcopy(operation['args']), **copy.deepcopy(operation['kwargs']))
            candidate = copy.deepcopy(self.data)
            settled = candidate['pending']['operations'][index]
            settled['result'], settled['done'] = copy.deepcopy(result), True
            self.save(candidate)

    async def invoke(self, io, method, *args, **kwargs):
        if not self.pending:
            return await getattr(io, method)(*args, **kwargs)
        # Raw audio is supplied again by the Pi on retry; only its digest and ASR
        # result are needed on the server to avoid transcribing a committed turn.
        signature_args = list(args)
        if method == 'transcribe':
            signature_args[0] = {'sha256': hashlib.sha256(args[0]).hexdigest()}
        signature = fingerprint([method, signature_args, kwargs])
        operations = self.pending['operations']
        index = self.cursor
        self.cursor += 1
        if index < len(operations):
            operation = operations[index]
            if operation['method'] != method or operation['fingerprint'] != signature:
                raise ServiceError('恢复回合与当前程序状态不一致；请结束练习后重新开始')
            if operation['done']:
                return copy.deepcopy(operation['result'])
        else:
            operation = {'method': method, 'fingerprint': signature, 'done': False}
            # The complete stable write intent is inspectable/recoverable even if
            # the process dies after SQLite commits but before HTTP responds.
            if method == 'record':
                operation['args'], operation['kwargs'] = copy.deepcopy(list(args)), copy.deepcopy(kwargs)
            operations.append(operation)
            self.save()
        if method == 'record':
            args, kwargs = operation['args'], operation['kwargs']
        result = await getattr(io, method)(*args, **kwargs)
        operation['result'], operation['done'] = copy.deepcopy(result), True
        self.save()
        return copy.deepcopy(result)

    def failed(self, tutor):
        if not self.pending:
            return
        operations = self.pending['operations']
        # A syntactically successful model HTTP response may fail Tutor's semantic
        # validation. No later IO has accepted that last read: retry it, while
        # retaining earlier judgments and every progress intent/result.
        if self.cursor and self.cursor == len(operations):
            last = operations[-1]
            if last['method'] == 'chat' and last['done']:
                last['done'] = False
                last.pop('result', None)
                self.save()
        tutor.restore_state(copy.deepcopy(self.pending['before']))

    def complete(self, reply, tutor, question_id, *, extra_reply=None):
        candidate = copy.deepcopy(self.data)
        pending = candidate['pending']
        now = self.wall()
        candidate['replies'][pending['request_id']] = {'fingerprint': pending['fingerprint'],
                                                      'reply': copy.deepcopy(reply), 'at': now}
        if extra_reply is not None:
            key, digest, response = extra_reply
            candidate['replies'][key] = {'fingerprint': digest, 'reply': copy.deepcopy(response), 'at': now}
        while len(candidate['replies']) > MAX_REPLIES:
            del candidate['replies'][next(iter(candidate['replies']))]
        candidate['state'] = tutor.export_state()
        if not reply.get('active'):
            candidate['state']['state']['history'] = []
        candidate['question_id'], candidate['saved_at'], candidate['pending'] = question_id, now, None
        self.save(candidate)

    def abandon(self, tutor):
        """Explicit stop may abandon a pending prompt; confirmed progress stays."""
        if self.pending:
            tutor.restore_state(copy.deepcopy(self.pending['before']))
            self.data['pending'] = None
            self.save()


class RecoverableIO:
    def __init__(self, io, recovery):
        self.raw, self.recovery = io, recovery

    def __getattr__(self, name):
        if name not in ('config', 'words', 'progress', 'record', 'chat', 'transcribe'):
            return getattr(self.raw, name)

        async def call(*args, **kwargs):
            return await self.recovery.invoke(self.raw, name, *args, **kwargs)
        return call
