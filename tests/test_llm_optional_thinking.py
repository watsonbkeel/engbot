"""Optional thinking compatibility with strict, explicit HTTP test fixtures.

OpenAI's documented Chat Completions body has no `thinking` field; DeepSeek
documents it and defaults it to enabled. These are synthetic error responses,
not observations from a live OpenAI account. All DNS and external HTTP are local
test substitutes; the actual Providers and public save/generate code run.
"""
import asyncio
import json
import time
from types import SimpleNamespace

import httpx
import pytest

from english_class.providers import ProviderError, Providers, validate_llm_url
from english_class.public_api import create_app


CUSTOM = {"base_url": "https://strict.example/v1", "model": "standard-chat-fixture",
          "api_key": "not-a-real-provider-key-1234", "thinking": False}
MESSAGES = [{"role": "system", "content": 'Return JSON {"correct":true}.'},
            {"role": "user", "content": "apple"}]
UNSUPPORTED = {"error": {"message": "Unrecognized request argument supplied: thinking",
                          "type": "invalid_request_error", "param": None, "code": None}}
SCENE = {"name": "书店", "robot_role": "店员", "student_role": "顾客",
         "goal": "询问一本书，说明选择并道谢。", "opening": "Hello, please!"}


@pytest.fixture
def strict_endpoint(monkeypatch):
    real_client = httpx.AsyncClient
    h = SimpleNamespace(calls=[], options=[], resolutions=[], status=400, error=UNSUPPORTED,
                        reject_without=False, delay=0, accept_thinking=False,
                        content='{"correct":true}', real_client=real_client)

    def resolve(url):
        h.resolutions.append(url)
        return url, ("8.8.8.8", "1.1.1.1")

    async def handle(request):
        payload = json.loads(request.content)
        h.calls.append((request, payload))
        if h.delay:
            await asyncio.sleep(h.delay)
        if not h.accept_thinking and ("thinking" in payload or h.reject_without):
            return httpx.Response(h.status, json=h.error)
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop",
            "message": {"content": h.content}}]})

    def client(*args, **kwargs):
        h.options.append(dict(kwargs))
        kwargs.setdefault("transport", httpx.MockTransport(handle))
        return real_client(*args, **kwargs)

    monkeypatch.setattr("english_class.providers._resolve_llm_endpoint", resolve)
    monkeypatch.setattr(httpx, "AsyncClient", client)
    h.provider = Providers(llm_key="")
    monkeypatch.setattr(h.provider, "check_llm_url", lambda url: validate_llm_url(
        url, resolve=lambda host, port, **kwargs: [(2, 1, 6, "", ("8.8.8.8", port))]))
    return h


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [
    UNSUPPORTED,
    {"error": {"message": "Unsupported parameter: 'thinking'.", "param": "thinking",
               "code": "unsupported_parameter", "type": "invalid_request_error"}},
    {"error": {"message": "Unknown parameter: thinking", "param": "thinking",
               "code": "unknown_parameter", "type": "invalid_request_error"}},
    {"error": {"message": "Unknown parameter: 'thinking'.", "param": None,
               "code": None, "type": "invalid_request_error"}},
])
async def test_disabled_thinking_retries_explicitly_unsupported_field_only(strict_endpoint, error):
    h = strict_endpoint
    h.error = error
    result = await h.provider.chat(MESSAGES, True, llm=CUSTOM)
    assert result == '{"correct":true}'
    assert len(h.calls) == 2
    first, second = h.calls
    assert first[1]["thinking"] == {"type": "disabled"}
    assert second[1] == {k: v for k, v in first[1].items() if k != "thinking"}
    assert first[0].url == second[0].url == httpx.URL("https://8.8.8.8/v1/chat/completions")
    for request, payload in h.calls:
        assert request.headers["host"] == "strict.example"
        assert request.headers["authorization"] == "Bearer " + CUSTOM["api_key"]
        assert request.extensions["sni_hostname"] == "strict.example"
        assert payload["model"] == CUSTOM["model"]
        assert payload["response_format"] == {"type": "json_object"}
    assert h.resolutions == [CUSTOM["base_url"]]
    assert h.options[0]["trust_env"] is False and h.options[0]["follow_redirects"] is False
    assert h.options[0]["timeout"].read == 45
    assert CUSTOM["thinking"] is False


@pytest.mark.asyncio
async def test_supported_disabled_thinking_is_retained_without_retry(strict_endpoint):
    h = strict_endpoint
    h.accept_thinking = True
    assert await h.provider.chat(MESSAGES, True, llm=CUSTOM) == '{"correct":true}'
    assert len(h.calls) == 1
    assert h.calls[0][1]["thinking"] == {"type": "disabled"}


@pytest.mark.asyncio
async def test_explicitly_enabled_unsupported_thinking_is_never_removed(strict_endpoint):
    h = strict_endpoint
    with pytest.raises(ProviderError, match="关闭") as failure:
        await h.provider.chat(MESSAGES, True, llm={**CUSTOM, "thinking": True})
    assert failure.value.code == "UnsupportedThinking"
    assert len(h.calls) == 1 and h.calls[0][1]["thinking"] == {"type": "enabled"}


@pytest.mark.asyncio
@pytest.mark.parametrize("status,error", [
    (400, {"error": {"message": "Unsupported parameter: temperature", "param": "temperature", "code": "unsupported_parameter"}}),
    (400, {"error": {"message": "Unsupported value: thinking.type='disabled'", "param": "thinking", "code": "unsupported_value"}}),
    (400, {"error": {"message": "Unsupported parameter: 'thinking' value is disabled", "param": "thinking", "code": "unsupported_value"}}),
    (400, {"error": {"message": "Unsupported value: thinking.type", "param": "thinking.type", "code": "unsupported_parameter"}}),
    (400, {"error": {"message": "Invalid JSON message; thinking about the input did not help", "code": "invalid_request_error"}}),
    (400, {"error": {"message": "Unsupported parameter: thinking_budget", "param": None, "code": None}}),
    (400, {"error": {"message": "Unsupported parameter: thinking.type", "param": None, "code": None}}),
    (400, {"error": {"message": "Unknown parameter: 'thinking.budget'", "param": None, "code": None}}),
    (400, {"error": {"message": "Unsupported parameter: 'thinking' value is disabled", "param": None, "code": None}}),
    (400, {"error": {"message": "Unknown parameter: 'thinking\"", "param": None, "code": None}}),
    (400, {"error": "Unknown parameter: thinking"}),
    (401, UNSUPPORTED), (403, UNSUPPORTED), (404, UNSUPPORTED), (429, UNSUPPORTED), (500, UNSUPPORTED),
])
async def test_other_errors_never_trigger_optional_thinking_retry(strict_endpoint, status, error):
    h = strict_endpoint
    h.status, h.error = status, error
    with pytest.raises(ProviderError):
        await h.provider.chat(MESSAGES, True, llm=CUSTOM)
    assert len(h.calls) == 1


@pytest.mark.asyncio
async def test_optional_thinking_retry_is_limited_to_one(strict_endpoint):
    h = strict_endpoint
    h.reject_without = True
    with pytest.raises(ProviderError):
        await h.provider.chat(MESSAGES, True, llm=CUSTOM)
    assert len(h.calls) == 2
    assert "thinking" in h.calls[0][1] and "thinking" not in h.calls[1][1]


@pytest.mark.asyncio
async def test_optional_retry_shares_original_total_timeout(strict_endpoint):
    h = strict_endpoint
    h.delay = 0.06
    started = time.monotonic()
    with pytest.raises(ProviderError) as failure:
        await h.provider.chat(MESSAGES, True, llm=CUSTOM, timeout=0.1)
    assert failure.value.code == "Timeout"
    assert len(h.calls) == 2
    assert time.monotonic() - started < 0.2
    assert h.resolutions == [CUSTOM["base_url"]]


@pytest.mark.asyncio
async def test_student_can_save_and_generate_with_optional_thinking_off(strict_endpoint, db, monkeypatch):
    h = strict_endpoint
    monkeypatch.delenv("PI_SSH_HOST", raising=False)
    monkeypatch.delenv("PI_SSH_HOSTS", raising=False)
    db.add_student("s001", "parent-thinking-fixture", "brain-thinking-fixture")
    headers = {"Authorization": "Bearer parent-thinking-fixture"}
    async with h.real_client(transport=httpx.ASGITransport(app=create_app(db, h.provider)), base_url="http://public.test") as client:
        saved = await client.put("/api/llm?student_id=s001", headers=headers, json=CUSTOM)
        assert saved.status_code == 200, saved.text
        assert saved.json()["thinking"] is False and CUSTOM["api_key"] not in saved.text
        assert db.llm("s001")["thinking"] is False
        assert h.options[0]["timeout"].read == 20
        h.content = json.dumps(SCENE, ensure_ascii=False)
        generated = await client.post("/api/scene/generate?student_id=s001", headers=headers,
            json={"description": "在书店买一本书并道谢", "grade": 1})
        assert generated.status_code == 200 and generated.json() == SCENE, generated.text
        h.content = '{"correct":true}'
        prior = db.llm("s001")
        rejected = await client.put("/api/llm?student_id=s001", headers=headers,
            json={**CUSTOM, "thinking": True, "model": "new-fixture-model"})
        assert rejected.status_code == 422 and "关闭" in rejected.text
        assert db.llm("s001") == prior
        assert all(r.headers["authorization"] == "Bearer " + CUSTOM["api_key"] for r, _ in h.calls)
