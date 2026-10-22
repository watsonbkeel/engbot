"""Portable v0.3.1 -> v0.3.2 API recovery tests; no git history or providers needed.

The fixture was captured with the actual baseline brain, Tutor and TurnRecovery
from 98eaddd3c4a35ab23a5e02ba373f05f0c2d645c9. Its model/ASR were test fixtures.
"""
import copy
import hashlib
import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from english_class.brain_api import create_brain
from english_class.client import ServiceError
from english_class.turn_recovery import fingerprint, private_json_write
from tests.test_v3_reliability import DatabaseIO, EDGE_TOKEN, HEADERS

FIXTURE = Path(__file__).parent / 'fixtures' / 'v031_pending_turn.json'


class UpgradeIO(DatabaseIO):
    def __init__(self, db):
        super().__init__(db)
        self.record_calls = []
        self.chat_calls = 0
        self.allow_chat = False
        self.fail_word = None
        self.fail_count = 0

    async def record(self, *args, **kwargs):
        self.record_calls.append((copy.deepcopy(args), copy.deepcopy(kwargs)))
        if self.fail_count and args[0] == self.fail_word:
            self.fail_count -= 1
            raise ServiceError('test-only public write unavailable')
        return await super().record(*args, **kwargs)

    async def chat(self, *args, **kwargs):
        self.chat_calls += 1
        assert self.allow_chat, 'upgrade closure must not rejudge or generate a new prompt'
        return await super().chat(*args, **kwargs)

    async def transcribe(self, *args, **kwargs):
        raise AssertionError('upgrade closure must not transcribe old audio')


def legacy_case(db, tmp_path, *, marker=None, chinese_help=True, pending=True):
    fixture = json.loads(FIXTURE.read_text())
    data = fixture['journal']
    now = time.time()
    data['saved_at'] = now
    data['pending']['at'] = now
    if marker is not None:
        data['pending']['executor_version'] = marker
    for cached in data['replies'].values():
        cached['at'] = now
    for snapshot in (data['state'], data['pending']['before']):
        shift = time.monotonic() - snapshot['saved_monotonic']
        for key in ('started_at', 'last_heard', 'quiet_since', 'pause_at'):
            if snapshot['state'].get(key) is not None:
                snapshot['state'][key] += shift
        snapshot['saved_monotonic'] += shift
        snapshot['saved_wall'] = now
        snapshot['state']['config']['chinese_help'] = chinese_help
        snapshot['state']['history'] = [{'role': 'user', 'content': 'private legacy lesson example'}]
    db.add_student('s001', 'test-parent-upgrade-token', 'test-brain-upgrade-token')
    db.save_config('s001', data['state']['state']['config'])
    for event in fixture['committed_records'] if pending else fixture['committed_records'][:-1]:
        db.record('s001', *event['args'], **event['kwargs'])
    if not pending:
        data['pending'] = None
    state = tmp_path / 'brain' / 'resume.json'
    fixture['resume']['saved_at'] = now
    fixture['resume']['config']['chinese_help'] = chinese_help
    private_json_write(state, fixture['resume'])
    private_json_write(state.with_name('turn-recovery.json'), data)
    return fixture, UpgradeIO(db), state


def add_uncertain_record(data, word_id, event_key):
    args = [word_id, 1, False, event_key]
    kwargs = {'evidence': {'answer_valid': True, 'used_word': False, 'imitated': False}}
    operation = {'method': 'record', 'fingerprint': fingerprint(['record', args, kwargs]),
                 'done': False, 'args': args, 'kwargs': kwargs}
    data['pending']['operations'].append(operation)
    return operation


def save_journal(fixture, state):
    private_json_write(state.with_name('turn-recovery.json'), fixture['journal'])


def post(client, body):
    return client.post('/voice/turn', headers=HEADERS, json=body)


def assert_upgrade_done(response, *, english=False):
    assert response.status_code == 200, response.text
    reply = response.json()
    assert reply['phase'] == 'done' and reply['active'] is False
    text = ' '.join(item['text'] for item in reply['segments'])
    assert ('upgrad' in text.lower() and 'start' in text.lower()) if english else ('系统已升级' in text and '重新开始' in text)
    return reply


@pytest.mark.parametrize('marker', [None, '0.3.0'], ids=['unversioned-v031', 'other-executor-version'])
def test_upgrade_settles_only_uncertain_write_and_caches_original_reply(db, tmp_path, marker):
    fixture, io, state = legacy_case(db, tmp_path, marker=marker)
    uncertain = add_uncertain_record(fixture['journal'], '1a_022', 'legacy-lost-write-032')
    # Public DB committed this write, but its reply never reached the old brain.
    db.record('s001', *uncertain['args'], **uncertain['kwargs'])
    saved_progress = db.progress('s001')
    save_journal(fixture, state)
    app = create_brain(io, EDGE_TOKEN, state_path=state)
    with TestClient(app) as client:
        # Completed old replies must replay unchanged without triggering closure.
        assert post(client, fixture['completed_start']['body']).json() == fixture['completed_start']['reply']
        assert io.record_calls == [] and app.state.recovery.pending is not None
        assert post(client, {**fixture['retry'], 'request_id': 'different-request-032'}).status_code == 409
        assert post(client, {**fixture['retry'], 'text': 'different answer'}).status_code == 409
        reply = assert_upgrade_done(post(client, fixture['retry']))
        assert reply['request_id'] == fixture['retry']['request_id']
        assert reply['question_id'] != fixture['retry']['question_id']
        assert io.record_calls == [(tuple(uncertain['args']), uncertain['kwargs'])]
        assert db.progress('s001') == saved_progress
        assert app.state.recovery.pending is None and app.state.tutor.history == []
        assert not state.exists()
    recovered = create_brain(io, EDGE_TOKEN, state_path=state)
    with TestClient(recovered) as client:
        assert post(client, fixture['retry']).json() == reply
        assert len(io.record_calls) == 1 and io.chat_calls == 0
        assert recovered.state.tutor.history == []
        # A fresh lesson must not load the partially processed old recall question.
        io.allow_chat = True
        fresh = post(client, {'action': 'start', 'request_id': 'fresh-after-upgrade-032'})
        assert fresh.status_code == 200 and fresh.json()['phase'] == 'listen', fresh.text
        assert fresh.json()['session_id'] != reply['session_id']


def test_partial_settlement_failure_keeps_remaining_intents_across_restart(db, tmp_path):
    fixture, io, state = legacy_case(db, tmp_path)
    first = add_uncertain_record(fixture['journal'], '1a_022', 'settle-first-032')
    second = add_uncertain_record(fixture['journal'], '1a_017', 'settle-second-032')
    save_journal(fixture, state)
    io.fail_word = '1a_017'
    io.fail_count = 1
    with TestClient(create_brain(io, EDGE_TOKEN, state_path=state)) as client:
        failed = post(client, fixture['retry'])
        assert failed.status_code == 503, failed.text
    journal = json.loads(state.with_name('turn-recovery.json').read_text())
    writes = [op for op in journal['pending']['operations'] if op['method'] == 'record']
    assert [op['done'] for op in writes] == [True, True, False]
    assert state.exists()
    with TestClient(create_brain(io, EDGE_TOKEN, state_path=state)) as client:
        assert_upgrade_done(post(client, fixture['retry']))
    assert [args[0] for args, _ in io.record_calls] == ['1a_022', '1a_017', '1a_017']
    rows = {row['word_id']: row for row in db.progress('s001')['words']}
    assert rows['1a_022']['valid_count'] == rows['1a_017']['valid_count'] == 1
    assert io.chat_calls == 0


@pytest.mark.parametrize('explicit_stop', [False, True], ids=['original-retry', 'explicit-stop'])
def test_failed_upgrade_cache_commit_keeps_pending_and_resume_until_retry(db, tmp_path, monkeypatch, explicit_stop):
    fixture, io, state = legacy_case(db, tmp_path)
    app = create_brain(io, EDGE_TOKEN, state_path=state)
    body = {'action': 'stop', 'request_id': 'stop-upgrade-cache-032'} if explicit_stop else fixture['retry']
    original_save = app.state.recovery.save

    def fail_completed_save(candidate=None):
        if candidate is not None and candidate['pending'] is None:
            raise ServiceError('test-only cache commit failed')
        return original_save(candidate)

    monkeypatch.setattr(app.state.recovery, 'save', fail_completed_save)
    with TestClient(app) as client:
        assert post(client, body).status_code == 503
        assert app.state.recovery.pending['request_id'] == fixture['retry']['request_id']
        assert state.exists(), 'never clear resume before the closure result is durable'
    with TestClient(create_brain(io, EDGE_TOKEN, state_path=state)) as client:
        reply = assert_upgrade_done(post(client, body))
        assert post(client, body).json() == reply
    assert io.record_calls == [] and io.chat_calls == 0
    assert not state.exists()


def test_old_invalid_wav_pending_closes_before_new_audio_validation(db, tmp_path):
    fixture, io, state = legacy_case(db, tmp_path, chinese_help=False)
    wav = b'old truncated audio without a WAV header'
    request_id = 'legacy-invalid-wav-032'
    identity = {key: fixture['retry'][key] for key in ('session_id', 'question_id')}
    pending = fixture['journal']['pending']
    pending['request_id'] = request_id
    pending['fingerprint'] = fingerprint(['audio', identity['session_id'], identity['question_id'], hashlib.sha256(wav).hexdigest()])
    pending['operations'] = [{'method': 'transcribe', 'done': False, 'fingerprint': 'old-asr-intent'}]
    save_journal(fixture, state)
    app = create_brain(io, EDGE_TOKEN, state_path=state)
    with TestClient(app) as client:
        response = client.post('/voice/audio', headers=HEADERS, params={'request_id': request_id, **identity}, content=wav)
        reply = assert_upgrade_done(response, english=True)
        assert app.state.recovery.pending is None and app.state.tutor.history == []
        assert client.post('/voice/audio', headers=HEADERS, params={'request_id': request_id, **identity}, content=wav).json() == reply
    assert io.record_calls == [] and io.chat_calls == 0 and not state.exists()


def test_upgrade_stop_does_not_wait_for_unavailable_record_and_replays_both_ids(db, tmp_path):
    fixture, io, state = legacy_case(db, tmp_path)
    add_uncertain_record(fixture['journal'], '1a_022', 'abandoned-on-stop-032')
    save_journal(fixture, state)
    saved_progress = db.progress('s001')
    io.fail_word = '1a_022'
    io.fail_count = 100
    stop = {'action': 'stop', 'request_id': 'stop-old-lesson-032'}
    app = create_brain(io, EDGE_TOKEN, state_path=state)
    with TestClient(app) as client:
        stopped = assert_upgrade_done(post(client, stop))
        assert stopped['request_id'] == stop['request_id']
        assert post(client, stop).json() == stopped
        original = assert_upgrade_done(post(client, fixture['retry']))
        assert original['request_id'] == fixture['retry']['request_id']
        assert original['question_id'] == stopped['question_id']
        assert post(client, {**stop, 'text': 'different stop payload'}).status_code == 409
        assert post(client, {**fixture['retry'], 'text': 'different old answer'}).status_code == 409
        assert app.state.recovery.pending is None and app.state.tutor.history == []
    assert db.progress('s001') == saved_progress
    assert io.record_calls == [] and io.chat_calls == 0 and not state.exists()


def test_upgrade_cleanup_failure_prevents_loading_old_resume_on_start(db, tmp_path, monkeypatch):
    fixture, io, state = legacy_case(db, tmp_path)
    original_unlink = Path.unlink
    blocked = [True]

    def unlink(path, *args, **kwargs):
        if path == state and blocked[0]:
            raise OSError('test-only resume directory unavailable')
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'unlink', unlink)
    app = create_brain(io, EDGE_TOKEN, state_path=state)
    with TestClient(app) as client:
        closed = assert_upgrade_done(post(client, fixture['retry']))
        assert state.exists()
        start = {'action': 'start', 'request_id': 'start-waits-for-cleanup-032'}
        assert post(client, start).status_code == 503
        spoken_start = {'text': '开始今天的英语练习', 'request_id': 'spoken-start-cleanup-032'}
        assert post(client, spoken_start).status_code == 503
        assert client.post('/voice/push', headers=HEADERS, json=spoken_start).status_code == 503
        for number, unreliable in enumerate(({'confidence': .64}, {'unclear': True})):
            quiet = post(client, {**spoken_start, 'request_id': 'quiet-start-' + str(number), **unreliable})
            assert quiet.status_code == 200 and quiet.json()['active'] is False
        assert app.state.tutor.phase == 'done' and app.state.recovery.pending is None
        assert post(client, fixture['retry']).json() == closed
        blocked[0] = False
        io.allow_chat = True
        fresh = post(client, start)
        assert fresh.status_code == 200 and fresh.json()['phase'] == 'listen', fresh.text


@pytest.mark.parametrize('legacy_push', [False, True], ids=['text-turn', 'legacy-text-bridge'])
def test_upgrade_reliable_text_stop_uses_the_same_close_policy(db, tmp_path, legacy_push):
    fixture, io, state = legacy_case(db, tmp_path)
    add_uncertain_record(fixture['journal'], '1a_022', 'text-stop-abandoned-write-032')
    save_journal(fixture, state)
    io.fail_word = '1a_022'; io.fail_count = 100
    body = {'text': '结束练习', 'request_id': 'spoken-stop-upgrade-032'}
    app = create_brain(io, EDGE_TOKEN, state_path=state)
    with TestClient(app) as client:
        for unreliable in ({'confidence': .64}, {'unclear': True}):
            rejected = post(client, {**body, **unreliable})
            assert rejected.status_code == 409 and app.state.recovery.pending is not None
        response = (client.post('/voice/push', headers=HEADERS, json=body) if legacy_push else post(client, body))
        closed = assert_upgrade_done(response)
        assert closed['request_id'] == body['request_id']
        assert post(client, body).json() == closed
        assert app.state.recovery.pending is None and app.state.tutor.history == []
    assert io.record_calls == [] and io.chat_calls == 0 and not state.exists()


def test_old_state_without_pending_continues_normally(db, tmp_path):
    fixture, io, state = legacy_case(db, tmp_path, pending=False)
    io.allow_chat = True
    app = create_brain(io, EDGE_TOKEN, state_path=state)
    with TestClient(app) as client:
        response = post(client, {**fixture['retry'], 'request_id': 'natural-continue-032'})
        assert response.status_code == 200, response.text
        assert response.json()['active'] is True and response.json()['phase'] == 'dialog'
        assert '系统已升级' not in str(response.json()['segments'])
        assert io.judgments == 1
