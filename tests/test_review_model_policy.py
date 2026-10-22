"""Real public routes and SQLite; only the external model boundary is controlled."""
import asyncio
import json
import logging

import httpx
import pytest
from fastapi.testclient import TestClient

from conftest import headers
from english_class.providers import ProviderError, pcm_wav
from english_class.public_api import create_app

SCENE = {'name': 'My shop', 'robot_role': 'Customer', 'student_role': 'Shopkeeper',
         'goal': 'Welcome the customer and sell two pencils.', 'opening': 'Welcome!'}
KEY = 'fixture-private-key-never-log-1298'
SETTINGS = {'base_url': 'https://fixture.example/v1', 'model': 'fixture-model', 'api_key': KEY}
CHAT = {'messages': [{'role': 'user', 'content': 'private-learner-utterance-735'}], 'json_output': True}


class BoundaryProvider:
    llm_model = 'fixture-platform'
    llm_key = 'fixture-platform-key-never-log'

    def __init__(self):
        self.calls = []
        self.fail_custom = False
        self.fail_platform = False
        self.content = json.dumps(SCENE)
        self.delay = 0
        self.transcriptions = 0

    def check_llm_url(self, value):
        return value

    async def chat(self, messages, json_output=False, llm=None, timeout=45):
        self.calls.append('student' if llm else 'platform')
        if self.delay:
            await asyncio.sleep(self.delay)
        if llm and self.fail_custom:
            raise ProviderError('自带模型密钥无效：' + KEY, code='HTTP401')
        if not llm and self.fail_platform:
            raise ProviderError('平台暂不可用', code='HTTP503')
        if 'VOCABULARY_JUDGE' in messages[0]['content']:
            return '{"correct":true}'
        return self.content

    async def transcribe(self, data, language):
        self.transcriptions += 1
        return {'text': '', 'unclear': True, 'confidence': None, 'provider': 'fixture'}


@pytest.fixture
def policy(db):
    db.add_student('s001', 'Parent_A_very_long_token', 'Brain_A_very_long_token')
    db.add_student('s002', 'Parent_B_very_long_token', 'Brain_B_very_long_token')
    provider = BoundaryProvider()
    app = create_app(db, provider)
    with TestClient(app) as client:
        yield client, provider, db, app


def save(client, **extra):
    return client.put('/api/llm?student_id=s001', headers=headers(), json={**SETTINGS, **extra})


def chat(client):
    return client.post('/internal/chat?student_id=s001', headers=headers('brain'), json=CHAT)


def generate(client):
    return client.post('/api/scene/generate?student_id=s001', headers=headers(),
                       json={'description': '我当文具店员，由我询问顾客的需要', 'grade': 4})


def test_custom_failure_does_not_send_to_platform_without_opt_in(policy):
    client, provider, db, _ = policy
    assert save(client).status_code == 200
    provider.calls.clear()
    provider.fail_custom = True
    response = chat(client)
    assert response.status_code == 503
    assert provider.calls == ['student']
    assert response.json()['error_code'] == 'CustomModelUnavailable'
    assert response.headers['x-request-id'] == response.json()['request_id']
    assert KEY not in response.text
    row = client.get('/api/llm?student_id=s001', headers=headers()).json()
    assert row['allow_platform_fallback'] is False
    assert row['last_status'] == 'error' and KEY not in row['last_error']


def test_opt_in_fallback_reports_actual_provider_without_exposing_key(policy):
    client, provider, db, _ = policy
    result = save(client, allow_platform_fallback=True)
    assert result.status_code == 200, result.text
    assert result.json()['allow_platform_fallback'] is True
    provider.calls.clear()
    provider.fail_custom = True
    response = chat(client)
    assert response.status_code == 200
    assert provider.calls == ['student', 'platform']
    assert response.json()['provider'] == 'platform'
    assert response.json()['fallback_used'] is True
    assert response.json()['fallback_code'] == 'HTTP401'
    assert KEY not in response.text
    assert db.llm('s001')['last_status'] == 'fallback'


@pytest.mark.parametrize('value', ['true', 1, None])
def test_fallback_requires_a_real_boolean(policy, value):
    client, _, db, _ = policy
    assert save(client, allow_platform_fallback=value).status_code == 422
    assert db.llm('s001') is None


def test_malformed_custom_json_also_respects_disabled_fallback(policy):
    client, provider, _, _ = policy
    assert save(client).status_code == 200
    provider.calls.clear()
    provider.content = 'not json'
    response = chat(client)
    assert response.status_code == 503
    assert provider.calls == ['student']


def test_success_and_explicit_delete_keep_platform_use_clear(policy):
    client, provider, _, _ = policy
    assert save(client, allow_platform_fallback=True).status_code == 200
    response = chat(client)
    assert response.json()['provider'] == 'student'
    assert response.json()['fallback_used'] is False
    result = client.delete('/api/llm?student_id=s001', headers=headers())
    assert result.json()['mode'] == 'platform'
    assert result.json()['allow_platform_fallback'] is False
    assert chat(client).json()['provider'] == 'platform'


def test_fallback_shares_one_total_request_deadline(policy):
    client, provider, db, app = policy
    assert save(client, allow_platform_fallback=True).status_code == 200
    provider.fail_custom = True
    provider.delay = .065

    async def run():
        from english_class.llm_service import ModelService
        service = ModelService(db, provider)
        with pytest.raises(ProviderError) as error:
            await service.chat('s001', CHAT['messages'], True, timeout=.10)
        assert error.value.code == 'Timeout'

    asyncio.run(run())


def test_scene_still_returns_exact_five_fields_with_fallback_in_headers(policy):
    client, provider, _, _ = policy
    assert save(client, allow_platform_fallback=True).status_code == 200
    provider.fail_custom = True
    response = generate(client)
    assert response.status_code == 200
    assert response.json() == SCENE
    assert response.headers['x-model-provider'] == 'platform'
    assert response.headers['x-model-fallback'] == 'true'
    assert KEY not in response.text and KEY not in str(response.headers)


def test_scene_usage_distinguishes_attempts_from_successes_and_stays_scoped(policy):
    client, provider, _, _ = policy
    usage = lambda: client.get('/api/scene/usage?student_id=s001', headers=headers())
    assert usage().status_code == 200
    assert usage().json()['attempts'] == 0
    provider.content = '{"error":"请把场景目标写清楚"}'
    assert generate(client).status_code == 422
    provider.content = json.dumps(SCENE)
    assert generate(client).status_code == 200
    view = usage().json()
    assert (view['attempts'], view['successes'], view['remaining'], view['limit']) == (2, 1, 18, 20)
    assert client.get('/api/scene/usage?student_id=s002', headers=headers()).status_code == 403
    assert client.get('/api/scene/usage?student_id=s001', headers=headers('brain')).status_code == 403
    assert client.get('/api/scene/usage?student_id=s002', headers=headers(student='B')).json()['attempts'] == 0


def test_failed_custom_generation_counts_attempt_without_success_or_fallback(policy):
    client, provider, _, _ = policy
    assert save(client).status_code == 200
    provider.fail_custom = True
    provider.calls.clear()
    assert generate(client).status_code == 503
    assert provider.calls == ['student']
    view = client.get('/api/scene/usage?student_id=s001', headers=headers()).json()
    assert (view['attempts'], view['successes']) == (1, 0)


def test_http_and_model_diagnostics_have_ids_and_no_secrets_or_child_text(policy, caplog):
    client, provider, _, _ = policy
    assert save(client).status_code == 200
    provider.fail_custom = True
    caplog.clear()
    with caplog.at_level(logging.INFO, logger='english-class'):
        response = chat(client)
    assert response.status_code == 503
    request_id = response.headers['x-request-id']
    entries = [json.loads(record.message) for record in caplog.records if record.name.startswith('english-class.')]
    assert any(x.get('event') == 'model_request' and x['request_id'] == request_id for x in entries)
    assert any(x.get('event') == 'http_request' and x['request_id'] == request_id and x['status'] == 503 for x in entries)
    for forbidden in (KEY, provider.llm_key, 'Brain_A_very_long_token', CHAT['messages'][0]['content'], 's001'):
        assert forbidden not in caplog.text
    assert all(isinstance(x['latency_ms'], (float, int)) for x in entries)


def test_unknown_runtime_failure_returns_safe_code_and_request_id(policy):
    client, provider, _, _ = policy

    async def broken(*args, **kwargs):
        raise RuntimeError('sensitive-provider-runtime-' + KEY)

    provider.chat = broken
    response = chat(client)
    assert response.status_code == 500
    assert response.json()['error_code'] == 'InternalError'
    assert response.headers['x-request-id'] == response.json()['request_id']
    assert KEY not in response.text and 'sensitive-provider-runtime' not in response.text


def test_asr_rejects_explicit_wrong_media_type_before_provider(policy):
    client, provider, _, _ = policy
    response = client.post('/internal/asr?student_id=s001',
                           headers={**headers('brain'), 'Content-Type': 'application/json'},
                           content=pcm_wav(b'\x00\x00' * 16000))
    assert response.status_code == 415
    assert response.json()['error_code'] == 'UnsupportedAudioType'
    assert provider.transcriptions == 0


def test_asr_validates_audio_even_with_a_provider_adapter(policy):
    client, provider, _, _ = policy
    response = client.post('/internal/asr?student_id=s001',
                           headers={**headers('brain'), 'Content-Type': 'audio/wav'}, content=b'not-a-wave')
    assert response.status_code == 422
    assert response.json()['error_code'] == 'InvalidAudio'
    assert provider.transcriptions == 0


def test_asr_stream_wait_is_bounded_without_calling_provider(policy, monkeypatch):
    _, provider, _, app = policy
    import english_class.public_api as public
    monkeypatch.setattr(public, 'AUDIO_UPLOAD_SECONDS', .01, raising=False)

    async def chunks():
        yield b'RIFF'
        await asyncio.sleep(.1)
        yield b'rest'

    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            response = await client.post('/internal/asr?student_id=s001',
                                        headers={**headers('brain'), 'Content-Type': 'audio/wav'}, content=chunks())
        assert response.status_code == 408
        assert response.json()['error_code'] == 'AudioUploadTimeout'

    asyncio.run(run())
    assert provider.transcriptions == 0


def test_scene_timeout_updates_model_status_usage_and_correlated_error(policy, monkeypatch, caplog):
    client, provider, db, _ = policy
    assert save(client).status_code == 200
    import english_class.public_api as public
    monkeypatch.setattr(public, 'SCENE_GENERATION_SECONDS', .015)
    provider.delay = .2
    with caplog.at_level(logging.INFO, logger='english-class'):
        response = generate(client)
    assert response.status_code == 503
    assert response.json()['error_code'] == 'Timeout'
    assert response.json()['request_id'] == response.headers['x-request-id']
    assert db.llm('s001')['last_status'] == 'error'
    assert '时限' in db.llm('s001')['last_error']
    usage = db.scene_generation_usage('s001')
    assert (usage['attempts'], usage['successes']) == (1, 0)
    events = [json.loads(r.message) for r in caplog.records if r.name == 'english-class.requests']
    assert any(e['event'] == 'model_request' and e['error_code'] == 'Timeout' for e in events)


@pytest.mark.parametrize('invalid', [
    {'api_key': KEY * 20},
    {'api_key': {'secret': KEY}},
    {'allow_platform_fallback': 'true'},
])
def test_request_validation_does_not_echo_keys_and_preserves_safe_diagnostics(policy, invalid):
    client, _, _, _ = policy
    response = save(client, **invalid)
    assert response.status_code == 422
    assert KEY not in response.text
    value = response.json()
    assert value['error_code'] == 'InvalidRequest'
    assert value['request_id'] == response.headers['x-request-id']
    assert isinstance(value['detail'], list) and value['detail']
    assert all(set(item) == {'loc', 'type', 'msg'} for item in value['detail'])
