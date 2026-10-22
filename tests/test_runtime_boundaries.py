"""Runtime boundary regressions; external provider substitutes remain in tests."""
import asyncio
import struct
import threading
import time

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from english_class.brain_api import create_brain
from english_class.client import PublicClient, ServiceError
from english_class.providers import ProviderError, Providers, pcm_wav, validate_wav
from english_class.public_api import create_app
from tests.test_http_integration import running
from tests.test_v3_reliability import DatabaseIO, EDGE_TOKEN, HEADERS, turn


def corrupt_chunk_wav():
    # RIFF declares 100 bytes, while its JUNK subchunk claims 4 GiB.
    return b'RIFF' + struct.pack('<I', 100) + b'WAVEJUNK' + struct.pack('<I', 0xffffffff) + b'\0' * 12


def test_riff_chunk_bounds_are_an_input_error():
    with pytest.raises(ValueError, match='无法读取WAV音频'):
        validate_wav(corrupt_chunk_wav())


def test_corrupt_riff_is_422_at_public_and_brain_without_pending_turn(db):
    db.add_student('s001', 'Parent_A_very_long_token', 'Brain_A_very_long_token')
    provider = Providers()
    with TestClient(create_app(db, provider), raise_server_exceptions=False) as public:
        response = public.post('/internal/asr', params={'student_id': 's001'},
                               headers={'Authorization': 'Bearer Brain_A_very_long_token',
                                        'Content-Type': 'audio/wav'}, content=corrupt_chunk_wav())
        assert response.status_code == 422, response.text
    io = DatabaseIO(db)
    brain = create_brain(io, EDGE_TOKEN)
    with TestClient(brain, raise_server_exceptions=False) as client:
        current = turn(client, 'start').json()
        identity = {key: current[key] for key in ('session_id', 'question_id')}
        response = client.post('/voice/audio', headers=HEADERS,
                               params={**identity, 'request_id': 'corrupt-riff-boundary'},
                               content=corrupt_chunk_wav())
        assert response.status_code == 422, response.text
        assert brain.state.recovery.pending is None
        assert io.asr_calls == 0
        retry = client.post('/voice/audio', headers=HEADERS,
                            params={**identity, 'request_id': 'valid-riff-boundary'},
                            content=pcm_wav(b'\0' * 3200))
        assert retry.status_code == 200, retry.text


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', ['chat', 'asr', 'tts'])
async def test_invalid_provider_url_is_safe_configuration_error(operation):
    provider = Providers(llm_base='http://invalid:port', llm_key='test-only',
                         asr_backend='http', asr_base='http://invalid:port', asr_model='test-only',
                         asr_min_rms=0, tts_backend='http', tts_base='http://invalid:port',
                         tts_key='test-only', tts_model='test-only')
    with pytest.raises(ProviderError) as error:
        if operation == 'chat':
            await provider.chat([])
        elif operation == 'asr':
            await provider.transcribe(pcm_wav(b'\0' * 320), 'en')
        else:
            await provider.speak([{'text': 'Hello.', 'language': 'en'}])
    assert error.value.code == 'InvalidConfiguration'
    assert 'http://invalid:port' not in str(error.value)
    assert 'test-only' not in str(error.value)


async def close_if_supported(client):
    close = getattr(client, 'aclose', None)
    if close is not None:
        await close()


@pytest.mark.asyncio
@pytest.mark.parametrize('body', [[], 'oops', None, 5, {}, {'detail': []}, {'detail': {'input': 'private lesson'}}])
async def test_public_client_normalizes_arbitrary_json_error_bodies(monkeypatch, body):
    real_client = httpx.AsyncClient
    calls = []

    def upstream(request):
        calls.append(request)
        return httpx.Response(503, json=body)

    monkeypatch.setattr(httpx, 'AsyncClient',
                        lambda **kwargs: real_client(transport=httpx.MockTransport(upstream), **kwargs))
    client = PublicClient('http://public.test', 's001', 'fixture-token')
    try:
        with pytest.raises(ServiceError, match='公共服务返回 503') as error:
            await client.request('POST', '/api/progress', body={}, event_key='same-key')
        assert 'private lesson' not in str(error.value)
        assert len(calls) == 1  # A failed POST is not automatically retried.
        assert calls[0].headers['Idempotency-Key'] == 'same-key'
    finally:
        await close_if_supported(client)


@pytest.mark.asyncio
async def test_public_client_reuses_real_connections_and_keeps_tokens_scoped():
    upstream = FastAPI()
    observed = []

    @upstream.get('/api/config')
    async def config(request: Request):
        observed.append((request.query_params['student_id'], request.headers['Authorization'], request.client.port))
        return {'ok': True}

    with running(upstream) as url:
        first = PublicClient(url, 'first', 'first-fixture-token')
        second = PublicClient(url, 'second', 'second-fixture-token')
        try:
            for _ in range(3):
                await first.config()
            await second.config()
            await first.config()
            assert len({port for sid, _, port in observed if sid == 'first'}) == 1
            assert {token for sid, token, _ in observed if sid == 'first'} == {'Bearer first-fixture-token'}
            assert {token for sid, token, _ in observed if sid == 'second'} == {'Bearer second-fixture-token'}
        finally:
            await close_if_supported(first)
            await close_if_supported(second)


def test_brain_lifespan_closes_client_before_reuse_on_a_new_event_loop(monkeypatch):
    monkeypatch.setattr('english_class.brain_api.HEARTBEAT_THROTTLE', 0)
    real_client = httpx.AsyncClient
    sessions = []
    calls = []

    def upstream(request):
        calls.append(request)
        return httpx.Response(200, json={'ok': True})

    def session(**kwargs):
        client = real_client(transport=httpx.MockTransport(upstream), **kwargs)
        sessions.append(client)
        return client

    monkeypatch.setattr(httpx, 'AsyncClient', session)
    io = PublicClient('http://public.test', 's001', 'fixture-token')
    app = create_brain(io, EDGE_TOKEN)
    assert sessions == []  # Construction outside an event loop stays lazy.
    for cycle in range(2):
        with TestClient(app) as client:
            assert client.get('/health').status_code == 200
            assert len(sessions) == cycle + 1
            assert not sessions[-1].is_closed
        assert sessions[-1].is_closed
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_brain_shutdown_stops_heartbeat_before_closing_io(db, monkeypatch):
    class ClosingIO(DatabaseIO):
        closed = False
        calls_after_close = 0

        async def heartbeat(self, pi=False):
            if self.closed:
                self.calls_after_close += 1
            return await super().heartbeat(pi=pi)

        async def aclose(self):
            self.closed = True

    monkeypatch.setattr('english_class.brain_api.HEARTBEAT_SECONDS', .005)
    monkeypatch.setattr('english_class.brain_api.HEARTBEAT_THROTTLE', 0)
    io = ClosingIO(db)
    app = create_brain(io, EDGE_TOKEN)
    async with app.router.lifespan_context(app):
        await asyncio.sleep(.015)
    count = len(io.heartbeats)
    await asyncio.sleep(.015)
    assert io.closed
    assert io.calls_after_close == 0
    assert len(io.heartbeats) == count
    assert not any(task.get_name() == 'brain-heartbeat' for task in asyncio.all_tasks())


@pytest.mark.asyncio
async def test_cloud_asr_capacity_is_shared_across_provider_instances(monkeypatch):
    providers = [Providers(asr_backend='http', asr_base='https://asr.test', asr_model='fixture',
                           asr_min_rms=0) for _ in range(2)]
    active = maximum = 0
    entered = asyncio.Event()
    release = asyncio.Event()

    async def upstream(data, language):
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        if active >= 4:
            entered.set()
        try:
            await release.wait()
            return {'text': 'apple', 'confidence': None, 'unclear': False, 'provider': 'http'}
        finally:
            active -= 1

    for provider in providers:
        monkeypatch.setattr(provider, '_http_asr', upstream)
    requests = [asyncio.create_task(providers[index % 2].transcribe(pcm_wav(b'\0' * 320), 'en'))
                for index in range(10)]
    try:
        await asyncio.wait_for(entered.wait(), .5)
        await asyncio.sleep(.01)
    finally:
        release.set()
        results = await asyncio.gather(*requests, return_exceptions=True)
    assert maximum == 4
    assert sum(isinstance(result, ProviderError) and result.code == 'Busy' for result in results) == 6
    assert sum(isinstance(result, dict) for result in results) == 4


async def wait_thread_event(event):
    async with asyncio.timeout(.5):
        while not event.is_set():
            await asyncio.sleep(.001)


@pytest.mark.asyncio
@pytest.mark.parametrize('abandon', ['deadline', 'cancel'])
async def test_local_asr_retains_capacity_until_real_worker_finishes(monkeypatch, abandon):
    # A cancelled waiter cannot enqueue more recognizers or start a cloud call
    # while its old worker is still running; one slot makes this observable.
    monkeypatch.setattr('english_class.providers._ASR_CAPACITY', threading.BoundedSemaphore(1), raising=False)
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    local = Providers(asr_backend='vosk')
    local.asr_local_timeout = .03 if abandon == 'deadline' else 1
    cloud = Providers(asr_backend='http', asr_base='https://asr.test', asr_model='fixture', asr_min_rms=0)

    def recognizer(pcm, rate, language):
        entered.set()
        try:
            release.wait(.5)
            return {'text': 'apple', 'confidence': .9, 'unclear': False, 'provider': 'vosk'}
        finally:
            finished.set()

    async def upstream(data, language):
        return {'text': 'apple', 'confidence': None, 'unclear': False, 'provider': 'http'}

    monkeypatch.setattr(local, '_vosk', recognizer)
    monkeypatch.setattr(cloud, '_http_asr', upstream)
    task = asyncio.create_task(local.transcribe(pcm_wav(b'\0' * 320), 'en'))
    try:
        await wait_thread_event(entered)
        if abandon == 'cancel':
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            with pytest.raises(ProviderError) as error:
                await asyncio.wait_for(task, .2)
            assert error.value.code == 'Timeout'
        for provider in (local, cloud):
            with pytest.raises(ProviderError) as error:
                await asyncio.wait_for(provider.transcribe(pcm_wav(b'\0' * 320), 'en'), .1)
            assert error.value.code == 'Busy'
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
        await wait_thread_event(finished)
    # Wait for the executor's completion callback, not merely the worker body.
    async with asyncio.timeout(.5):
        while True:
            try:
                result = await cloud.transcribe(pcm_wav(b'\0' * 320), 'en')
                break
            except ProviderError as error:
                assert error.code == 'Busy'
                await asyncio.sleep(.001)
    assert result['provider'] == 'http'


@pytest.mark.asyncio
async def test_cloud_timeout_keeps_separate_local_fallback_budget(monkeypatch):
    provider = Providers(asr_backend='http', asr_base='https://asr.test', asr_model='fixture',
                         asr_min_rms=0, asr_timeout=.02, asr_fallback='vosk')
    provider.asr_local_timeout = .2

    async def upstream(data, language):
        await asyncio.Event().wait()

    def recognizer(pcm, rate, language):
        time.sleep(.04)
        return {'text': 'apple', 'confidence': .9, 'unclear': False, 'provider': 'vosk'}

    monkeypatch.setattr(provider, '_http_asr', upstream)
    monkeypatch.setattr(provider, '_vosk', recognizer)
    result = await asyncio.wait_for(provider.transcribe(pcm_wav(b'\0' * 320), 'en'), .3)
    assert result['provider'] == 'vosk-fallback'
    assert result['fallback_reason'] == 'Timeout'


def test_local_asr_timeout_has_an_explicit_environment_setting(monkeypatch):
    monkeypatch.setenv('ASR_LOCAL_TIMEOUT', '12.5')
    assert Providers.from_env().asr_local_timeout == 12.5
