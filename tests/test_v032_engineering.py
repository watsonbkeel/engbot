"""v0.3.2 engineering regressions; all provider replacements stay in tests."""
import copy
import logging

import pytest
from fastapi.testclient import TestClient

from english_class.brain_api import create_brain
from english_class.providers import validate_wav, pcm_wav
from pi.english_voice import BrainRequestError, route
from tests.test_v3_reliability import DatabaseIO, EDGE_TOKEN, HEADERS, edge_with_identity, idle_route_edge, pop, turn


@pytest.fixture
def io_with_audio_validation(db):
    db.add_student('s001', 'local-parent-token-1234567', 'local-brain-token-12345678')
    db.save_config('s001', {**db.config('s001'), 'practice_words': 1})

    class ValidatingIO(DatabaseIO):
        async def transcribe(self, wav, language):
            # The real public provider validates these bytes before any ASR call.
            validate_wav(wav)
            return await super().transcribe(wav, language)

    return ValidatingIO(db)


def test_invalid_audio_is_rejected_without_poisoning_next_turn(io_with_audio_validation):
    """Validation after recovery.begin leaves an unrecoverable pending request."""
    app = create_brain(io_with_audio_validation, EDGE_TOKEN)
    with TestClient(app) as client:
        started = turn(client, 'start').json()
        identity = {k: started[k] for k in ('session_id', 'question_id')}
        rejected = client.post('/voice/audio', headers=HEADERS, params={
            **identity, 'request_id': 'invalid-audio-032'}, content=b'not a WAV file')
        assert rejected.status_code == 422, rejected.text
        assert app.state.recovery.pending is None
        assert io_with_audio_validation.asr_calls == 0
        accepted = client.post('/voice/audio', headers=HEADERS, params={
            **identity, 'request_id': 'valid-audio-032'}, content=pcm_wav(b'\0' * 3200))
        assert accepted.status_code == 200, accepted.text
        assert accepted.json()['phase'] == 'recall'
        assert io_with_audio_validation.db.progress('s001')['words'][0]['valid_count'] == 1


def test_stale_question_error_does_not_write_lesson_text_to_default_logs(monkeypatch, tmp_path, caplog):
    """Logging HTTP detail leaks the stale response's full current question."""
    edge = edge_with_identity(monkeypatch, tmp_path)
    secret = 'Private classroom example: my sister is called Ada.'
    current = {**copy.deepcopy(edge.last_result), 'question_id': 'question-two',
               'segments': [{'text': secret, 'language': 'en'}]}

    def stale(*args, **kwargs):
        raise BrainRequestError(409, {'code': 'stale_question', 'message': 'old recording', 'current': current})

    monkeypatch.setattr(edge, 'request', stale)
    edge.submit(wav=b'test-only-stale-audio')
    with caplog.at_level(logging.INFO, logger='english-edge'):
        edge.process(pop(edge))
    assert edge.pending is None
    assert edge.last_result['segments'][0]['text'] == secret
    assert secret not in caplog.text
    assert '409' in caplog.text


def test_pi_can_rerecord_after_brain_rejects_invalid_audio(io_with_audio_validation, monkeypatch, tmp_path):
    """Route -> Pi worker -> brain rejection must leave the same question usable."""
    app = create_brain(io_with_audio_validation, EDGE_TOKEN)
    edge, chat = idle_route_edge(monkeypatch, tmp_path)
    messages = []
    monkeypatch.setattr(edge, 'local_message', messages.append)
    with TestClient(app) as client:
        def request(path, *, body=None, content=None, params=None, raw=False):
            response = client.post(path, headers=HEADERS, json=body, content=content, params=params)
            if response.status_code >= 400:
                raise BrainRequestError(response.status_code, response.json()['detail'])
            return response.content if raw else response.json()

        monkeypatch.setattr(edge, 'request', request)
        edge.submit('start')
        edge.process(pop(edge))
        question = copy.deepcopy(edge.last_result)
        assert route(edge, chat, '', .99, b'truncated WAV', question=question) == 'answer'
        edge.process(pop(edge))
        assert edge.pending is None and app.state.recovery.pending is None
        assert edge.last_result['question_id'] == question['question_id']
        assert '重新回答' in messages[-1]
        assert '正在确认' not in messages[-1]
        assert route(edge, chat, '', .99, pcm_wav(b'\0' * 3200), question=question) == 'answer'
        edge.process(pop(edge))
        assert edge.pending is None and edge.phase == 'recall'
        assert io_with_audio_validation.db.progress('s001')['words'][0]['valid_count'] == 1


@pytest.mark.asyncio
async def test_custom_llm_connection_cannot_reresolve_into_private_network(monkeypatch):
    """Exercise real HTTPX/HTTPCore/AnyIO DNS, intercept only final TCP opening."""
    import ipaddress
    import socket
    from anyio._backends._asyncio import AsyncIOBackend
    from english_class.providers import ProviderError, Providers

    resolutions = []
    destinations = []

    def rebinding_dns(host, port, family=0, type=0, proto=0, flags=0):
        assert host in ('rebind.example.test', b'rebind.example.test')
        address = '8.8.8.8' if not resolutions else '127.0.0.1'
        resolutions.append(address)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (address, port))]

    async def blocked_connect(cls, host, port, local_address=None):
        destinations.append(host)
        raise OSError('test: all TCP attempts intercepted, no network opened')

    for name in ('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'http_proxy', 'https_proxy', 'all_proxy'):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(socket, 'getaddrinfo', rebinding_dns)
    monkeypatch.setattr(AsyncIOBackend, 'connect_tcp', classmethod(blocked_connect))
    providers = Providers()
    with pytest.raises(ProviderError):
        await providers.chat([], llm={'base_url': 'https://rebind.example.test',
                                      'api_key': 'test-only-key', 'model': 'test'}, timeout=1)
    assert resolutions == ['8.8.8.8'], 'HTTP must not resolve the hostname a second time'
    assert destinations == ['8.8.8.8'], 'the real TCP path must attempt the validated IP'
    assert all(ipaddress.ip_address(host).is_global for host in destinations), destinations


@pytest.mark.asyncio
@pytest.mark.parametrize('base,addresses,host_header,sni,port,fail_first', [
    ('https://custom.example.test/v1', ['8.8.8.8'], 'custom.example.test', 'custom.example.test', 443, False),
    ('https://custom.example.test:8443/v1', ['8.8.8.8', '1.1.1.1'], 'custom.example.test:8443', 'custom.example.test', 8443, True),
    ('https://[2606:4700:4700::1111]:8443/v1', ['2606:4700:4700::1111'], '[2606:4700:4700::1111]:8443', '2606:4700:4700::1111', 8443, False),
])
async def test_custom_llm_pins_public_ips_preserves_tls_and_host_and_ignores_proxy(
        monkeypatch, base, addresses, host_header, sni, port, fail_first):
    """Real HTTPX request bytes/TLS arguments; socket and peer remain test-only."""
    import json
    import socket
    import ssl
    import httpcore
    from httpcore._backends.auto import AutoBackend
    from english_class.providers import Providers

    connections = []
    tls = []
    writes = []
    body = json.dumps({'choices': [{'message': {'content': '{"correct":true}'}, 'finish_reason': 'stop'}]}).encode()

    class RecordingStream(httpcore.AsyncMockStream):
        async def write(self, buffer, timeout=None):
            writes.append(buffer)

        async def start_tls(self, ssl_context, server_hostname=None, timeout=None):
            tls.append((server_hostname, ssl_context.check_hostname, ssl_context.verify_mode))
            return self

    async def connect(self, host, port, **kwargs):
        connections.append((host, port))
        if host not in addresses or (fail_first and len(connections) == 1):
            raise httpcore.ConnectError('test-only failed connection; no sockets opened')
        return RecordingStream([b'HTTP/1.1 200 OK\r\nContent-Length: ' + str(len(body)).encode() +
                                b'\r\nContent-Type: application/json\r\n\r\n' + body])

    def resolve(host, requested_port, family=0, type=0, proto=0, flags=0):
        assert host == sni
        return [(socket.AF_INET6 if ':' in address else socket.AF_INET, socket.SOCK_STREAM, 6, '',
                 (address, requested_port)) for address in addresses]

    for name in ('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'http_proxy', 'https_proxy', 'all_proxy'):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv('HTTPS_PROXY', 'http://test-proxy.invalid:3128')
    monkeypatch.delenv('NO_PROXY', raising=False)
    monkeypatch.delenv('no_proxy', raising=False)
    monkeypatch.setattr(socket, 'getaddrinfo', resolve)
    monkeypatch.setattr(AutoBackend, 'connect_tcp', connect)
    providers = Providers()
    assert await providers.chat([], llm={'base_url': base, 'api_key': 'test-only-key', 'model': 'test'}, timeout=1) == '{"correct":true}'
    assert connections == [(address, port) for address in addresses]
    assert tls == [(sni, True, ssl.CERT_REQUIRED)]
    request_bytes = b''.join(writes)
    assert b'POST /v1/chat/completions HTTP/1.1\r\n' in request_bytes
    assert ('host: ' + host_header + '\r\n').encode() in request_bytes.lower()


@pytest.mark.asyncio
async def test_custom_llm_address_failover_shares_one_total_deadline(monkeypatch):
    import asyncio
    import time
    import httpcore
    from httpcore._backends.auto import AutoBackend
    from english_class.providers import ProviderError, Providers

    destinations = []
    never = asyncio.Event()

    async def connect(self, host, port, **kwargs):
        destinations.append(host)
        if len(destinations) == 1:
            await asyncio.sleep(.01)
            raise httpcore.ConnectError('test-only first address unavailable')
        await never.wait()

    monkeypatch.setattr('english_class.providers._resolve_llm_endpoint',
                        lambda url: (url, ('8.8.8.8', '1.1.1.1')))
    monkeypatch.setattr(AutoBackend, 'connect_tcp', connect)
    started = time.monotonic()
    with pytest.raises(ProviderError) as caught:
        await Providers().chat([], llm={'base_url': 'https://custom.example.test',
                                        'api_key': 'test-only-key', 'model': 'test'}, timeout=.15)
    assert caught.value.code == 'Timeout'
    assert destinations == ['8.8.8.8', '1.1.1.1']
    assert time.monotonic() - started < .5


@pytest.mark.asyncio
async def test_custom_llm_mixed_public_private_answers_are_rejected_before_connect(monkeypatch):
    import socket
    import httpcore
    from httpcore._backends.auto import AutoBackend
    from english_class.providers import ProviderError, Providers

    destinations = []

    def resolve(host, port, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (address, port))
                for address in ('8.8.8.8', '127.0.0.1')]

    async def connect(self, host, port, **kwargs):
        destinations.append(host)
        raise httpcore.ConnectError('test-only blocked connection')

    monkeypatch.setattr(socket, 'getaddrinfo', resolve)
    monkeypatch.setattr(AutoBackend, 'connect_tcp', connect)
    with pytest.raises(ProviderError) as caught:
        await Providers().chat([], llm={'base_url': 'https://mixed.example.test',
                                        'api_key': 'test-only-key', 'model': 'test'})
    assert caught.value.code == 'InvalidAddress'
    assert destinations == []


@pytest.mark.asyncio
async def test_trusted_platform_model_retains_environment_proxy_support(monkeypatch):
    import httpcore
    from httpcore._backends.auto import AutoBackend
    from english_class.providers import ProviderError, Providers

    destinations = []

    async def connect(self, host, port, **kwargs):
        destinations.append((host, port))
        raise httpcore.ConnectError('test-only blocked connection')

    for name in ('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'http_proxy', 'https_proxy', 'all_proxy', 'NO_PROXY', 'no_proxy'):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv('HTTPS_PROXY', 'http://test-proxy.invalid:3128')
    monkeypatch.setattr(AutoBackend, 'connect_tcp', connect)
    with pytest.raises(ProviderError):
        await Providers(llm_base='https://platform.example.test', llm_key='test-only-key').chat([])
    assert destinations == [('test-proxy.invalid', 3128)]
