"""Local reliability regressions; provider substitutes exist only in tests.

Exercise real Tutor/brain/Pi/SQLite boundaries. These are not hardware or real
provider acceptance measurements.
"""
import copy
import json
import os
import time
import uuid

import httpx
import pytest
from fastapi.testclient import TestClient

from english_class.brain_api import create_brain
from english_class.client import ServiceError
from english_class.providers import pcm_wav
from pi.english_voice import Edge


EDGE_TOKEN = 'local-test-edge-token-12345'
HEADERS = {'Authorization': 'Bearer ' + EDGE_TOKEN}


class DatabaseIO:
    """Actual SQLite writes, deterministic test-only speech/model boundaries."""
    def __init__(self, db):
        self.db = db
        self.sid = 's001'
        self.judgments = 0
        self.dialog_failures = 0
        self.record_response_failures = 0
        self.asr_calls = 0
        self.heartbeats = []
        self.speech = []
        self.answer = '苹果'

    async def config(self):
        return self.db.config(self.sid)

    async def words(self, cfg):
        return self.db.dictionary.select(cfg['grade'], cfg['semester'], cfg['unit'])

    async def progress(self):
        return self.db.progress(self.sid)

    async def record(self, word_id, status, unclear, key, evidence=None):
        result = self.db.record(self.sid, word_id, status, unclear, key, evidence)
        if self.record_response_failures:
            self.record_response_failures -= 1
            raise ServiceError('test: progress response lost after commit')
        return result

    async def chat(self, messages, json_output=True):
        prompt = messages[0]['content']
        data = json.loads(messages[-1]['content'])
        if 'VOCABULARY_JUDGE' in prompt:
            self.judgments += 1
            return json.dumps({'correct': data['answer'] in (data['word'], data['meaning'])})
        if 'ENGLISH_CUE' in prompt:
            return json.dumps({'cue': 'What fruit is often red?'})
        if self.dialog_failures:
            self.dialog_failures -= 1
            raise ServiceError('test: next question unavailable')
        return json.dumps({'reply': [{'text': 'What fruit do you like?', 'language': 'en'}],
                           'relevant': True, 'modelled': []})

    async def transcribe(self, wav, language):
        self.asr_calls += 1
        return {'text': self.answer, 'confidence': None, 'unclear': False, 'provider': 'test'}

    async def heartbeat(self, pi=False):
        self.heartbeats.append(pi)
        return {'pi': pi}

    async def speak(self, segments, slow=False, speed='middle'):
        self.speech.append((copy.deepcopy(segments), slow, speed))
        return b'test-audio'


@pytest.fixture
def local_io(db):
    db.add_student('s001', 'local-parent-token-1234567', 'local-brain-token-12345678')
    cfg = db.config('s001')
    db.save_config('s001', {**cfg, 'practice_words': 1})
    return DatabaseIO(db)


def turn(client, action='answer', text='', request_id=None, identity=None):
    body = {'action': action, 'text': text, 'request_id': request_id or uuid.uuid4().hex}
    if identity:
        body.update({k: identity[k] for k in ('session_id', 'question_id')})
    return client.post('/voice/turn', json=body, headers=HEADERS)


def test_partial_commit_replays_first_judgment_after_brain_restart(local_io, tmp_path):
    """Removing durable IO replay rejudges an already committed answer."""
    state = tmp_path / 'brain' / 'resume.json'
    app = create_brain(local_io, EDGE_TOKEN, state_path=state)
    with TestClient(app) as client:
        assert turn(client, 'start').status_code == 200
        assert turn(client, text='苹果').status_code == 200
        assert turn(client, 'stop').status_code == 200
        assert state.is_file()
        assert turn(client, 'start').json()['phase'] == 'recall'
        local_io.dialog_failures = 1
        failed = turn(client, text='apple', request_id='recover-final-recall')
        assert failed.status_code == 503
        assert local_io.db.progress('s001')['words'][0]['status'] == 2
        assert state.is_file(), 'resume must survive until next question commits'
        first_judgments = local_io.judgments

    restarted = create_brain(local_io, EDGE_TOKEN, state_path=state)
    with TestClient(restarted) as client:
        recovered = turn(client, text='apple', request_id='recover-final-recall')
        assert recovered.status_code == 200, recovered.text
        assert recovered.json()['phase'] == 'dialog'
        assert local_io.judgments == first_judgments, 'never judge a committed answer twice'
        row = local_io.db.progress('s001')['words'][0]
        assert row['used_word_count'] == 1
        assert not state.exists()
        assert turn(client, text='apple', request_id='recover-final-recall').json() == recovered.json()


def test_lost_progress_response_reuses_stable_intent(local_io, tmp_path):
    state = tmp_path / 'brain' / 'resume.json'
    with TestClient(create_brain(local_io, EDGE_TOKEN, state_path=state)) as client:
        assert turn(client, 'start').status_code == 200
        local_io.record_response_failures = 1
        failed = turn(client, text='苹果', request_id='lost-progress-response')
        assert failed.status_code == 503
        judged = local_io.judgments
    with TestClient(create_brain(local_io, EDGE_TOKEN, state_path=state)) as client:
        recovered = turn(client, text='苹果', request_id='lost-progress-response')
        assert recovered.status_code == 200
        assert recovered.json()['phase'] == 'recall'
        assert local_io.judgments == judged
        rows = local_io.db.progress('s001')['words']
        assert len(rows) == 1
        assert rows[0]['valid_count'] == 1


def test_stale_audio_rejected_before_asr_but_exact_replay_survives_restart(local_io, tmp_path):
    cfg = local_io.db.config('s001')
    local_io.db.save_config('s001', {**cfg, 'practice_words': 2})
    state = tmp_path / 'brain' / 'resume.json'
    with TestClient(create_brain(local_io, EDGE_TOKEN, state_path=state)) as client:
        start = turn(client, 'start').json()
        assert start.get('question_id'), 'brain must issue an opaque question version'
        params = {k: start[k] for k in ('session_id', 'question_id')}
        first = client.post('/voice/audio', headers=HEADERS, params={**params, 'request_id': 'audio-first-answer'}, content=pcm_wav(b'\0'*3200))
        assert first.status_code == 200
        assert first.json()['question_id'] != start['question_id']
    with TestClient(create_brain(local_io, EDGE_TOKEN, state_path=state)) as client:
        replay = client.post('/voice/audio', headers=HEADERS, params={**params, 'request_id': 'audio-first-answer'}, content=pcm_wav(b'\0'*3200))
        assert replay.json() == first.json()
        stale = client.post('/voice/audio', headers=HEADERS, params={**params, 'request_id': 'audio-stale-answer'}, content=pcm_wav(b'\0'*3200))
        assert stale.status_code == 409
        assert local_io.asr_calls == 1
        assert len(local_io.db.progress('s001')['words']) == 1


def test_legacy_identical_commands_are_distinct_events(local_io):
    with TestClient(create_brain(local_io, EDGE_TOKEN)) as client:
        first = client.post('/voice/push', headers=HEADERS, json={'text': '开始练习'}).json()
        assert turn(client, 'stop').json()['phase'] == 'done'
        second = client.post('/voice/push', headers=HEADERS, json={'text': '开始练习'}).json()
        assert second['session_id'] != first['session_id']
        assert second['phase'] == 'listen'
        event = {'text': '暂停', 'request_id': 'explicit-legacy-event'}
        assert client.post('/voice/push', headers=HEADERS, json=event).json() == client.post('/voice/push', headers=HEADERS, json=event).json()


def test_brain_heartbeat_independent_of_pi_and_idle_tick_throttled(local_io):
    with TestClient(create_brain(local_io, EDGE_TOKEN)) as client:
        assert False in local_io.heartbeats, 'brain startup announces itself without a Pi'
        assert turn(client, 'tick').status_code == 200
        assert turn(client, 'tick').status_code == 200
        assert local_io.heartbeats.count(True) == 1


@pytest.mark.parametrize('grade,speed', [(1, 'elementary'), (7, 'middle'), (12, 'high')])
def test_brain_derives_speech_speed_from_grade(local_io, grade, speed):
    app = create_brain(local_io, EDGE_TOKEN)
    app.state.tutor.config = {'grade': grade}
    with TestClient(app) as client:
        response = client.post('/voice/speech', headers=HEADERS, json={
            'segments': [{'text': 'Hello.', 'language': 'en'}], 'slow': True,
            'speed': 'high' if grade == 1 else 'elementary'})
        assert response.status_code == 200
        assert local_io.speech[-1][1:] == (True, speed)


def edge_with_identity(monkeypatch, tmp_path):
    monkeypatch.setenv('BRAIN_URL', 'https://brain.example')
    monkeypatch.setenv('EDGE_TOKEN', EDGE_TOKEN)
    monkeypatch.setenv('EDGE_PENDING_PATH', str(tmp_path / 'edge' / 'pending-turn.json'))
    edge = Edge(play_audio=False, start_worker=False)
    edge.active = True
    edge.last_result = {'active': True, 'phase': 'listen', 'session_id': 'session-one', 'question_id': 'question-one',
                        'word_index': 0, 'segments': []}
    edge.note_question(edge.last_result)
    return edge


def pop(edge):
    item = edge.queue.get_nowait()
    edge.queue.task_done()
    return item


def test_pi_lost_reply_freezes_queue_and_recovers_same_event(monkeypatch, tmp_path):
    edge = edge_with_identity(monkeypatch, tmp_path)
    calls = []
    lose = [True]
    def request(path, *, body=None, params=None, **kwargs):
        if path == '/voice/audio':
            calls.append(params)
            if lose[0]:
                lose[0] = False
                raise httpx.ReadError('test: response lost after brain commit')
            return {**edge.last_result, 'question_id': 'question-two', 'word_index': 1}
        return edge.last_result
    edge.request = request
    edge.submit(wav=b'answer-one')
    edge.submit(wav=b'queued-old-answer')
    first, queued = pop(edge), pop(edge)
    edge.process(first)
    assert edge.pending['request_id'] == first['request_id']
    edge.process(queued)
    assert len(calls) == 1, 'do not send a second answer while first outcome is unknown'
    edge.retry_pending()
    assert calls[0] == calls[1]
    assert calls[0]['question_id'] == 'question-one'
    assert edge.last_result['question_id'] == 'question-two'
    edge.process(queued)
    assert len(calls) == 2, 'queued old audio must not be judged against the next word'
    assert edge.pending is None
    assert not (tmp_path / 'edge' / 'pending-turn.json').exists()


def test_pi_pending_survives_process_restart_with_private_file(monkeypatch, tmp_path):
    edge = edge_with_identity(monkeypatch, tmp_path)
    def fail(*args, **kwargs):
        raise httpx.ReadError('test: offline')
    edge.request = fail
    edge.submit(wav=b'private-test-audio')
    original = pop(edge)
    edge.process(original)
    path = tmp_path / 'edge' / 'pending-turn.json'
    assert path.is_file()
    assert os.stat(path).st_mode & 0o777 == 0o600
    restarted = Edge(play_audio=False, start_worker=False)
    assert restarted.pending['request_id'] == original['request_id']
    assert restarted.pending['wav'] == original['wav']
    assert restarted.pending['question_id'] == 'question-one'


def test_pi_idle_tick_and_server_question_change(monkeypatch, tmp_path):
    edge = edge_with_identity(monkeypatch, tmp_path)
    edge.active = False
    assert edge.submit_tick()
    item = pop(edge)
    edge.request = lambda *a, **k: {**edge.last_result, 'question_id': 'changed-by-tick',
                                   'segments': [{'text': 'Next question.', 'language': 'en'}]}
    before = edge.spoken
    edge.process(item)
    assert edge.spoken == before + 1


@pytest.mark.parametrize('spoken,action', [('听不懂','explain'), ('什么意思','explain'),
                                         ('这是什么意思','explain'), ('这个词什么意思','explain'),
                                         ('给我提示','explain'), ('我不会','howtosay'),
                                         ('不会说','howtosay'), ('我不会说','howtosay'), ('怎么说','howtosay'),
                                         ('I want to stop.','stop')])
def test_pi_v3_help_and_stop_commands(spoken, action):
    from pi.audio import control_action
    assert control_action(spoken) == action


def test_finished_snapshot_does_not_keep_dialog_history(local_io, tmp_path):
    state = tmp_path / 'brain' / 'resume.json'
    app = create_brain(local_io, EDGE_TOKEN, state_path=state)
    with TestClient(app) as client:
        assert turn(client, 'start').status_code == 200
        app.state.tutor.history = [{'role': 'user', 'content': 'private test conversation'}]
        assert turn(client, 'stop').status_code == 200
    recovery = json.loads((state.parent / 'turn-recovery.json').read_text())
    assert recovery['state']['state']['history'] == []
    assert os.stat(state.parent / 'turn-recovery.json').st_mode & 0o777 == 0o600


def test_live_recovery_window_expires_without_restart(local_io, tmp_path):
    from english_class.turn_recovery import RECOVERY_TTL_SECONDS
    state = tmp_path / 'brain' / 'resume.json'
    app = create_brain(local_io, EDGE_TOKEN, state_path=state)
    with TestClient(app) as client:
        assert turn(client, 'start').status_code == 200
        local_io.record_response_failures = 1
        assert turn(client, text='苹果', request_id='expired-progress-turn').status_code == 503
        app.state.recovery.wall = lambda: time.time() + RECOVERY_TTL_SECONDS + 1
        response = turn(client, 'tick')
        assert response.status_code == 200
        assert response.json()['phase'] == 'idle'
        assert app.state.recovery.pending is None
        serialized = (state.parent / 'turn-recovery.json').read_text()
        assert 'expired-progress-turn' not in serialized


def test_real_pi_and_brain_lost_response_cannot_write_next_word(local_io, tmp_path, monkeypatch):
    cfg = local_io.db.config('s001')
    local_io.db.save_config('s001', {**cfg, 'practice_words': 2})
    app = create_brain(local_io, EDGE_TOKEN, state_path=tmp_path / 'brain' / 'resume.json')
    edge = edge_with_identity(monkeypatch, tmp_path)
    lost = [False]
    calls = []
    with TestClient(app) as client:
        def request(path, *, body=None, content=None, params=None, raw=False):
            response = client.post(path, headers=HEADERS, json=body, content=content, params=params)
            assert response.status_code == 200, response.text
            if path == '/voice/audio':
                calls.append(params['request_id'])
                if not lost[0]:
                    lost[0] = True
                    raise httpx.ReadError('test: brain committed but reply was lost')
            return response.content if raw else response.json()
        edge.request = request
        edge.last_result = None
        edge.submit('start')
        edge.process(pop(edge))
        edge.submit(wav=pcm_wav(b'\0'*3200))
        edge.submit(wav=pcm_wav(b'\0'*6400))
        first, stale = pop(edge), pop(edge)
        edge.process(first)
        assert app.state.tutor.index == 1
        assert edge.last_result['word_index'] == 0
        edge.process(stale)
        edge.retry_pending()
        edge.process(stale)
        assert calls == [first['request_id'], first['request_id']]
        assert local_io.asr_calls == 1
        rows = local_io.db.progress('s001')['words']
        assert [(r['word_id'], r['status']) for r in rows] == [('1a_021', 1)]


def test_stop_can_cancel_unconfirmed_turn_without_rejudging(local_io, tmp_path):
    app = create_brain(local_io, EDGE_TOKEN, state_path=tmp_path / 'brain' / 'resume.json')
    with TestClient(app) as client:
        assert turn(client, 'start').status_code == 200
        local_io.record_response_failures = 1
        assert turn(client, text='苹果', request_id='stop-after-lost-progress').status_code == 503
        judged = local_io.judgments
        assert turn(client, 'stop').json()['phase'] == 'done'
        assert app.state.recovery.pending is None
        assert local_io.judgments == judged
        assert len(local_io.db.progress('s001')['words']) == 1


def test_invalid_next_model_reply_can_retry_without_changing_committed_judgment(local_io, tmp_path):
    original = local_io.chat
    invalid = [True]
    async def chat(messages, json_output=True):
        if 'VOCABULARY_JUDGE' not in messages[0]['content'] and invalid[0]:
            invalid[0] = False
            return 'not valid lesson JSON'
        return await original(messages, json_output)
    local_io.chat = chat
    with TestClient(create_brain(local_io, EDGE_TOKEN, state_path=tmp_path / 'brain' / 'resume.json')) as client:
        assert turn(client, 'start').status_code == 200
        assert turn(client, text='苹果').status_code == 200
        assert turn(client, text='apple', request_id='malformed-next-prompt').status_code == 503
        judged = local_io.judgments
        result = turn(client, text='apple', request_id='malformed-next-prompt')
        assert result.status_code == 200, result.text
        assert result.json()['phase'] == 'dialog'
        assert local_io.judgments == judged
        assert local_io.db.progress('s001')['words'][0]['used_word_count'] == 1


@pytest.mark.asyncio
async def test_brain_periodic_heartbeat_runs_during_slow_lesson(local_io, monkeypatch):
    import asyncio
    monkeypatch.setattr('english_class.brain_api.HEARTBEAT_SECONDS', .015)
    monkeypatch.setattr('english_class.brain_api.HEARTBEAT_THROTTLE', .005)
    entered, release = asyncio.Event(), asyncio.Event()
    original = local_io.config
    async def slow_config():
        entered.set()
        await release.wait()
        return await original()
    local_io.config = slow_config
    app = create_brain(local_io, EDGE_TOKEN)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://local-test') as client:
            pending = asyncio.create_task(client.post('/voice/turn', headers=HEADERS,
                                                     json={'action': 'start', 'request_id': 'slow-start-heartbeat'}))
            try:
                await entered.wait()
                await asyncio.sleep(.08)
                assert local_io.heartbeats.count(False) >= 3
            finally:
                release.set()
                assert (await pending).status_code == 200


def test_malformed_student_model_reaches_real_public_fallback(local_io, monkeypatch):
    from english_class.public_api import create_app
    from english_class.providers import Providers
    real_client = httpx.AsyncClient
    calls = []
    def provider(request):
        custom = request.headers['host'] == 'student.test'
        calls.append(custom)
        payload = {'choices': [None]} if custom else {'choices': [{'message': {'content': '{"correct":true}'},
                                                                 'finish_reason': 'stop'}]}
        return httpx.Response(200, json=payload)
    monkeypatch.setattr('english_class.providers.httpx.AsyncClient',
                        lambda **kwargs: real_client(transport=httpx.MockTransport(provider), **kwargs))
    p = Providers(llm_base='https://platform.test', llm_key='test-platform-key')
    monkeypatch.setattr('english_class.providers._resolve_llm_endpoint', lambda url: (url, ('8.8.8.8',)))
    local_io.db.save_llm('s001', 'https://student.test', 'test-model', 'test-student-key',
                         allow_platform_fallback=True)
    with TestClient(create_app(local_io.db, p)) as client:
        response = client.post('/internal/chat', params={'student_id': 's001'},
                               headers={'Authorization': 'Bearer local-brain-token-12345678'},
                               json={'messages': [{'role': 'user', 'content': 'Return JSON.'}], 'json_output': True})
        assert response.status_code == 200, response.text
        assert response.json()['provider'] == 'platform'
    assert calls == [True, False]
    assert local_io.db.llm('s001')['last_status'] == 'fallback'


def test_pi_stop_after_lost_completed_reply_still_stops_current_lesson(local_io, tmp_path, monkeypatch):
    from pi.english_voice import BrainRequestError
    app = create_brain(local_io, EDGE_TOKEN)
    edge = edge_with_identity(monkeypatch, tmp_path)
    edge.last_result = None
    with TestClient(app) as client:
        def request(path, *, body=None, content=None, params=None, raw=False):
            response = client.post(path, headers=HEADERS, json=body, content=content, params=params)
            if response.status_code >= 400:
                raise BrainRequestError(response.status_code, response.json()['detail'])
            if path == '/voice/audio':
                raise httpx.ReadError('test: reply lost after changing question')
            return response.content if raw else response.json()
        edge.request = request
        edge.submit('start')
        edge.process(pop(edge))
        edge.submit(wav=pcm_wav(b'\0'*3200))
        edge.process(pop(edge))
        assert edge.pending is not None
        edge.submit('stop')
        edge.process(pop(edge))
        assert app.state.tutor.phase == 'done'
        assert edge.active is False
        assert edge.pending is None


def test_replacing_queued_stop_with_pause_does_not_deadlock_recovery(monkeypatch, tmp_path):
    import threading
    edge = edge_with_identity(monkeypatch, tmp_path)
    retried = threading.Event()
    offline = [True]
    def request(path, **kwargs):
        if offline[0]:
            raise httpx.ReadError('test: temporarily offline')
        if path == '/voice/audio': retried.set()
        return edge.last_result
    edge.request = request
    edge.submit(wav=b'answer')
    edge.process(pop(edge))
    edge.submit('stop')
    edge.submit('pause')  # supersedes the still-queued stop
    offline[0] = False
    edge.retry_at = 0
    edge.thread.start()
    try:
        assert retried.wait(.5), 'worker must still confirm the original answer'
    finally:
        edge.close()
        edge.thread.join(timeout=1)
        assert not edge.thread.is_alive()


def idle_route_edge(monkeypatch, tmp_path):
    from types import SimpleNamespace
    monkeypatch.setenv('BRAIN_URL', 'https://brain.example')
    monkeypatch.setenv('EDGE_TOKEN', EDGE_TOKEN)
    monkeypatch.setenv('EDGE_PENDING_PATH', str(tmp_path / 'edge' / 'pending-turn.json'))
    return Edge(play_audio=False, start_worker=False), SimpleNamespace(active=False, leave=lambda: None)


@pytest.mark.parametrize('restart_pi', [False, True], ids=['lost-first-start-reply', 'restored-pending-start'])
def test_route_stop_reaches_brain_when_first_start_is_unconfirmed(local_io, tmp_path, monkeypatch, restart_pi):
    from pi.english_voice import route
    edge, chat = idle_route_edge(monkeypatch, tmp_path)
    app = create_brain(local_io, EDGE_TOKEN, state_path=tmp_path / 'brain' / 'resume.json')
    calls = []
    stop_reply_lost = [False]
    with TestClient(app) as client:
        def request(path, *, body=None, content=None, params=None, raw=False):
            response = client.post(path, headers=HEADERS, json=body, content=content, params=params)
            assert response.status_code == 200, response.text
            calls.append((body['action'], body['request_id']))
            if body['action'] == 'start':
                raise httpx.ReadError('test: first start committed but response lost')
            if body['action'] == 'stop' and not stop_reply_lost[0]:
                stop_reply_lost[0] = True
                raise httpx.ReadError('test: stop also committed but response lost')
            return response.content if raw else response.json()
        edge.request = request
        assert route(edge, chat, '小陈同学，学英语', .99, b'') == 'start'
        edge.process(pop(edge))
        assert app.state.tutor.phase == 'listen'
        assert edge.active is False and edge.pending['action'] == 'start'
        if restart_pi:
            edge = Edge(play_audio=False, start_worker=False)
            edge.request = request
            assert edge.active is False and edge.pending['action'] == 'start'
        assert route(edge, chat, '结束练习', .69, b'') is None
        assert edge.queue.empty()
        assert route(edge, chat, '结束练习', .99, b'') == 'stop'
        assert edge.stop_queued is True
        edge.process(pop(edge))
        assert app.state.tutor.phase == 'done'
        assert edge.pending['action'] == 'stop'
        edge.retry_pending()
        assert edge.pending is None and edge.active is False
        assert not edge.pending_path.exists()
        assert [action for action, _ in calls] == ['start', 'stop', 'stop']
        assert calls[1][1] == calls[2][1], 'a lost stop response must reuse its event ID'
        assert local_io.db.progress('s001')['words'] == []


@pytest.mark.parametrize('stage', ['queued', 'pending', 'restored'])
def test_route_repeated_start_does_not_create_another_unconfirmed_event(monkeypatch, tmp_path, stage):
    from pi.english_voice import route
    edge, chat = idle_route_edge(monkeypatch, tmp_path)
    def offline(*args, **kwargs):
        raise httpx.ReadError('test: start outcome unknown')
    edge.request = offline
    assert route(edge, chat, '小陈同学，学英语', .99, b'') == 'start'
    if stage != 'queued':
        edge.process(pop(edge))
        original = edge.pending['request_id']
        if stage == 'restored': edge = Edge(play_audio=False, start_worker=False)
    assert route(edge, chat, '小陈同学，学英语', .99, b'') == 'start'
    if stage == 'queued':
        assert edge.queue.qsize() == 1
    else:
        assert edge.queue.empty()
        assert edge.pending['request_id'] == original


@pytest.mark.parametrize('text', ['结束练习', '今天天气怎么样', 'apple'])
def test_route_idle_without_unconfirmed_start_stays_silent(monkeypatch, tmp_path, text):
    from pi.english_voice import route
    edge, chat = idle_route_edge(monkeypatch, tmp_path)
    assert route(edge, chat, text, .99, b'environmental audio') is None
    assert edge.queue.empty() and edge.pending is None and edge.stop_queued is False


@pytest.fixture
def scene_completion():
    """Use the actual Tutor ending, including dialogue feedback and scene review."""
    import asyncio
    from english_class.engine import Tutor
    from test_v3_learning import SCENE, V3IO
    async def finish():
        io = V3IO(mode='scene', count=1, scene=SCENE)
        io.config_value['difficulty'] = 'basic'
        tutor = Tutor(io)
        await tutor.turn(action='start', request_id='final-replay-start')
        await tutor.turn('Hi sir', request_id='final-replay-opening')
        for i in range(6):
            result = await tutor.turn('I want an apple', request_id=f'final-replay-answer-{i}')
        assert result['phase'] == 'done' and not result['active']
        assert len(result['segments']) == 6
        return result, io
    return asyncio.run(finish())


def failed_final_edge(monkeypatch, tmp_path, scene_completion, failure='tts'):
    from pi.english_voice import BrainRequestError
    final, io = scene_completion
    edge, chat = idle_route_edge(monkeypatch, tmp_path)
    edge.active = True
    edge.phase = 'dialog'
    edge.audio_enabled = True
    requests, played, notices = [], [], []
    fail = [True]
    def request(path, *, body=None, **kwargs):
        requests.append((path, copy.deepcopy(body)))
        if path == '/voice/speech':
            if failure == 'tts' and fail[0]:
                fail[0] = False
                raise BrainRequestError(503, 'test: final speech unavailable')
            return b'test-final-speech'
        assert path == '/voice/turn' and body['action'] in ('answer', 'tick')
        return copy.deepcopy(final if body['action'] == 'answer' else {**final, 'segments': []})
    def play(audio):
        if failure == 'playback' and fail[0]:
            fail[0] = False
            raise RuntimeError('test: playback interrupted')
        played.append(audio)
    edge.request = request
    edge.play = play
    edge.local_message = notices.append
    edge.submit(text='I want an apple')
    edge.process(pop(edge))
    assert not edge.active and edge.phase == 'done' and edge.pending is None
    assert not played and notices and '再说一次' in notices[0]
    return edge, chat, requests, played, io


@pytest.mark.parametrize('failure', ['tts', 'playback'])
def test_final_reply_replays_locally_after_failed_playback_and_idle_tick(monkeypatch, tmp_path, scene_completion, failure):
    from pi.english_voice import route
    final, _ = scene_completion
    edge, chat, requests, played, io = failed_final_edge(monkeypatch, tmp_path, scene_completion, failure)
    writes, judgments = copy.deepcopy(io.writes), len(io.chat_calls)
    assert edge.submit_tick()
    edge.process(pop(edge))
    assert edge.last_result['segments'] == [], 'idle status must not erase replayable feedback'
    for speech in ('I want an apple', '今天天气怎么样'):
        assert route(edge, chat, speech, .99, b'environmental audio') is None
    assert route(edge, chat, '再说一次', .69, b'') is None
    assert edge.queue.empty()
    assert route(edge, chat, '再说一次', .99, b'') == 'repeat'
    edge.process(pop(edge))
    assert played == [b'test-final-speech']
    assert [body['action'] for path, body in requests if path == '/voice/turn'] == ['answer', 'tick']
    speech_bodies = [body for path, body in requests if path == '/voice/speech']
    assert len(speech_bodies) == 2 and speech_bodies[0] == speech_bodies[1]
    assert speech_bodies[-1]['segments'] == final['segments']
    assert io.writes == writes and len(io.chat_calls) == judgments
    assert edge.pending is None and not edge.pending_path.exists()


@pytest.mark.parametrize('stage', ['queued', 'synthesizing'])
@pytest.mark.parametrize('control', ['start', 'stop'])
def test_final_replay_yields_to_new_start_or_explicit_stop(monkeypatch, tmp_path, scene_completion, stage, control):
    from pi.english_voice import route
    edge, chat, requests, played, _ = failed_final_edge(monkeypatch, tmp_path, scene_completion)
    assert route(edge, chat, '再说一次', .99, b'') == 'repeat'
    utterance = '小陈同学，学英语' if control == 'start' else '结束练习'
    if stage == 'synthesizing':
        replay = pop(edge)
        original_request = edge.request
        def interrupt(path, **kwargs):
            assert path == '/voice/speech'
            assert route(edge, chat, utterance, .99, b'') == control
            return original_request(path, **kwargs)
        edge.request = interrupt
        edge.process(replay)
    else:
        assert route(edge, chat, utterance, .99, b'') == control
    assert not played, 'cancelled final feedback must not play over the next action'
    assert edge.final_reply is None
    if control == 'start':
        assert edge.queue.qsize() == 1 and pop(edge)['action'] == 'start'
    else:
        assert edge.queue.empty(), 'already-confirmed done needs only local cancellation'
    assert route(edge, chat, '再说一次', .99, b'') is None
    assert edge.queue.empty()
    assert [body['action'] for path, body in requests if path == '/voice/turn'] == ['answer']


def test_default_edge_logs_metadata_without_robot_transcript(monkeypatch, tmp_path, caplog):
    import logging
    edge, _ = idle_route_edge(monkeypatch, tmp_path)
    private_reply = '这是仅用于隐私回归的个性化点评原文。'
    edge.request = lambda *args, **kwargs: {'active': False, 'phase': 'done',
        'segments': [{'text': private_reply, 'language': 'zh'}]}
    with caplog.at_level(logging.INFO, logger='english-edge'):
        edge.submit('start')
        edge.process(pop(edge))
    assert private_reply not in caplog.text
    assert 'done' in caplog.text and 'segments=1' in caplog.text


def test_text_mode_explicitly_displays_reply_without_logging_transcript(monkeypatch, tmp_path, caplog, capsys):
    import logging
    idle_route_edge(monkeypatch, tmp_path)  # install test-only endpoint and private state path
    edge = Edge(play_audio=False, start_worker=False, display_text=True)
    reply = 'Hello, this is the visible text-mode question.'
    edge.request = lambda *args, **kwargs: {'active': False, 'phase': 'done',
        'segments': [{'text': reply, 'language': 'en'}]}
    with caplog.at_level(logging.INFO, logger='english-edge'):
        edge.submit('start')
        edge.process(pop(edge))
    assert reply in capsys.readouterr().out
    assert reply not in caplog.text


def test_default_voice_capture_log_does_not_keep_recognized_text(monkeypatch, tmp_path, caplog):
    import logging
    import sys
    from types import SimpleNamespace
    from pi import english_voice
    edge, chat = idle_route_edge(monkeypatch, tmp_path)
    private_utterance = '这句话只用于检查麦克风转写不进入日志'
    edge.local_message = lambda text: None
    monkeypatch.setenv('VOSK_ZH_PATH', str(tmp_path))
    monkeypatch.setenv('CAPTURE_DEVICE', 'test-device')
    monkeypatch.setitem(sys.modules, 'vosk', SimpleNamespace(SetLogLevel=lambda n: None,
        Model=lambda path: object(), KaldiRecognizer=lambda *args: object()))
    class Capture:
        stdout = SimpleNamespace(read=lambda size: b'\x00\x00' * 1600)
        def terminate(self): pass
        def wait(self, **kwargs): pass
    monkeypatch.setattr(english_voice.subprocess, 'Popen', lambda *args, **kwargs: Capture())
    class Activity:
        parts = []
        def __init__(self, **kwargs): pass
        def reset(self): pass
        def feed(self, chunk):
            edge.stop_event.set()
            return b'test-private-audio'
    monkeypatch.setattr(english_voice, 'VoiceActivity', Activity)
    monkeypatch.setattr(english_voice, 'recognize_chinese', lambda *args: (private_utterance, .97))
    ticks = iter([0., 0., 1., 1., 1., 1., 1., 1.])
    monkeypatch.setattr(english_voice.time, 'monotonic', lambda: next(ticks, 1.))
    with caplog.at_level(logging.INFO, logger='english-edge'):
        english_voice.voice_loop(edge, chat)
    assert private_utterance not in caplog.text
    assert 'conf=0.97' in caplog.text
    assert edge.queue.empty(), 'idle environmental audio remains local'


def test_default_chat_handoff_log_does_not_keep_transcript(caplog):
    import logging
    from pi.english_voice import Chat
    utterance = '这句话只用于检查普通聊天转交日志'
    chat = Chat(poll=lambda *args: {'ok': True})
    with caplog.at_level(logging.INFO, logger='english-edge'):
        assert chat.say(utterance, False)
    assert utterance not in caplog.text
    assert str(len(utterance)) in caplog.text

