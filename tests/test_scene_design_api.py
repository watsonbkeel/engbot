"""Student-designed scenes through actual APIs, Tutor and provider serialization.

Only DNS and provider HTTP responses are explicit test doubles. These tests do
not contact a real provider, use a real key, or measure model teaching quality.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from english_class.brain_api import create_brain
from english_class.client import PublicClient
from english_class.dictionary import Dictionary
from english_class.providers import Providers, validate_llm_url
from english_class.public_api import create_app
from english_class.store import Store


ROOT = Path(__file__).resolve().parents[1]
DESIGNS = [
    {"student": "museum", "grade": 2, "difficulty": "basic", "thinking": False,
     "description": "我是参观化石馆的小访客，想问讲解员恐龙有多大、吃什么。",
     "scene": {"name": "化石馆", "robot_role": "博物馆讲解员", "student_role": "小访客",
               "goal": "向讲解员问好，询问恐龙大小和食物，练习大小与食物词，最后道谢。",
               "opening": "Hello, guide!"}},
    {"student": "forest", "grade": 5, "difficulty": "standard", "thinking": True,
     "description": "我是护林员，机器人是迷路的小狐狸，我要问路并带它回树洞。",
     "scene": {"name": "狐狸回家", "robot_role": "迷路的小狐狸", "student_role": "护林员",
               "goal": "安慰狐狸，询问树洞的位置，说明走路方向，确认到家，练习方位词。",
               "opening": "Hello, little fox!"}},
    {"student": "weather", "grade": 8, "difficulty": "challenge", "thinking": True,
     "description": "我要在学校气象站向值班老师报告天气，并一起决定是否进行户外观测。",
     "scene": {"name": "学校气象站", "robot_role": "气象站值班老师", "student_role": "学生观测员",
               "goal": "报告温度与天气，询问观测安排，说明建议及理由，练习天气词与计划表达。",
               "opening": "Good morning, teacher!"}},
]


def parent_headers(student):
    return {"Authorization": f"Bearer parent-{student}-fixture-token"}


def settings(design):
    student = design["student"]
    return {"base_url": f"https://{student}.example/v1/chat/completions/",
            "model": f"fixture/{student}-model",
            "api_key": f"not-a-real-{student}-provider-key-1234",
            "thinking": design["thinking"]}


@pytest.fixture
def scene_system(tmp_path, monkeypatch):
    monkeypatch.delenv("PI_SSH_HOST", raising=False)
    monkeypatch.delenv("PI_SSH_HOSTS", raising=False)
    monkeypatch.setenv("LISTENING_DIR", str(tmp_path / "unused-listening"))
    store = Store(tmp_path / "scene.sqlite3", Dictionary(ROOT / "data/dictionary.json"))
    for design in DESIGNS:
        student = design["student"]
        store.add_student(student, f"parent-{student}-fixture-token", f"brain-{student}-fixture-token")
    provider = Providers(llm_base="https://platform.example/v1",
                         llm_model="platform-fixture-model",
                         llm_key="not-a-real-platform-provider-key-1234")
    # Fixed, non-network DNS fixture. Production URL validation still runs.
    resolver = lambda host, port, **kwargs: [(2, 1, 6, "", ("8.8.8.8", port))]
    checked_url = lambda url: validate_llm_url(url, resolve=resolver)
    monkeypatch.setattr(provider, "check_llm_url", checked_url)
    monkeypatch.setattr("english_class.providers._resolve_llm_endpoint",
                        lambda url: (checked_url(url), ("8.8.8.8",)))
    app = create_app(store, provider)
    public_transport = httpx.ASGITransport(app=app)
    real_client = httpx.AsyncClient
    calls, public_requests, overrides = [], [], {}

    def completion(content, status=200, finish="stop"):
        return httpx.Response(status, json={"choices": [{"finish_reason": finish,
            "message": {"content": content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)}}]})

    async def dispatch(request):
        if request.url.host == "public.test":
            public_requests.append(request)
            return await public_transport.handle_async_request(request)
        payload = json.loads(request.content)
        system = payload["messages"][0]["content"]
        task = ("probe" if "VOCABULARY_JUDGE" in system else
                "review" if "SCENE_REVIEW" in system else
                "dialogue" if "SCENE_DIALOGUE" in system else "generate")
        host = request.headers["host"]
        calls.append({"request": request, "payload": payload, "task": task, "host": host})
        # Every provider request stays in this fixture; never open a socket.
        assert host in {"platform.example", *(f"{d['student']}.example" for d in DESIGNS)}
        if (host, task) in overrides:
            return completion(**overrides[host, task])
        if task == "probe":
            return completion({"correct": True})
        data = json.loads(payload["messages"][-1]["content"])
        if task == "generate":
            design = next(d for d in DESIGNS if d["description"] == data["description"])
            return completion(design["scene"])
        if task == "review":
            return completion({"praise": "You completed your role-play task.", "tips": ["Try one new detail next time."]})
        return completion({"reply": [{"text": "Thank you. Our task is complete." if data["closing"]
                                                   else "What would you like to ask next?", "language": "en"}],
                           "relevant": bool(data["answer"]), "modelled": [], "word_evidence": []})

    def routed_client(*args, **kwargs):
        kwargs.setdefault("transport", httpx.MockTransport(dispatch))
        return real_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", routed_client)
    return SimpleNamespace(store=store, provider=provider, app=app, calls=calls,
                           public_requests=public_requests, overrides=overrides,
                           client=lambda: real_client(transport=public_transport, base_url="http://public.test"))


async def save_model(client, design, **changes):
    return await client.put(f"/api/llm?student_id={design['student']}",
                            headers=parent_headers(design["student"]), json={**settings(design), **changes})


async def generate(client, design):
    return await client.post(f"/api/scene/generate?student_id={design['student']}",
                             headers=parent_headers(design["student"]),
                             json={"description": design["description"], "grade": design["grade"]})


@pytest.mark.asyncio
async def test_three_students_save_generate_edit_and_complete_own_scene(scene_system):
    h = scene_system
    async with h.client() as parent:
        for design in DESIGNS:
            student = design["student"]
            saved = await save_model(parent, design)
            assert saved.status_code == 200, saved.text
            assert settings(design)["api_key"] not in saved.text
            card = await generate(parent, design)
            assert card.status_code == 200 and card.json() == design["scene"], card.text
            # A draft is not implicitly applied to the next lesson.
            cfg_path = f"/api/config?student_id={student}"
            cfg = (await parent.get(cfg_path, headers=parent_headers(student))).json()
            assert cfg["scene"] is None
            edited = {**card.json(), "goal": card.json()["goal"] + "由我选择最后一个问题。"}
            cfg.update(grade=design["grade"], semester=1, mode="scene", scene=edited,
                       difficulty=design["difficulty"], chinese_help=False)
            saved_cfg = await parent.put(cfg_path, headers=parent_headers(student), json=cfg)
            assert saved_cfg.status_code == 200 and saved_cfg.json()["scene"] == edited, saved_cfg.text
            assert Store(h.store.path, h.store.dictionary).config(student)["scene"] == edited

            io = PublicClient("http://public.test", student, f"brain-{student}-fixture-token")
            brain = create_brain(io, f"edge-{student}-fixture-token")
            headers = {"Authorization": f"Bearer edge-{student}-fixture-token"}
            current = None
            async with brain.router.lifespan_context(brain), httpx.AsyncClient(transport=httpx.ASGITransport(app=brain), base_url="http://brain.test") as edge:
                async def turn(text="", action="answer", serial=0):
                    nonlocal current
                    body = {"request_id": f"{student}-turn-{serial}", "action": action, "text": text}
                    if action == "answer" and current:
                        body.update({k: current[k] for k in ("session_id", "question_id")})
                    response = await edge.post("/voice/turn", headers=headers, json=body)
                    assert response.status_code == 200, response.text
                    assert settings(design)["api_key"] not in response.text
                    current = response.json()
                    return current

                started = await turn(action="start")
                assert started["scene_opening_pending"] is True
                assert started["segments"][-1]["text"] == edited["opening"]
                await turn(edited["opening"], serial=1)
                limit = {"basic": 6, "standard": 8, "challenge": 10}[design["difficulty"]]
                for serial in range(2, limit + 2):
                    await turn("Thank you for helping me.", serial=serial)
                assert current["phase"] == "done" and current["active"] is False
                assert current["dialog_count"] == limit
                assert "task is complete" in current["segments"][0]["text"]
                assert settings(design)["api_key"] not in json.dumps(brain.state.tutor.export_state())

            own = [c for c in h.calls if c["host"] == f"{student}.example"]
            assert {c["task"] for c in own} == {"probe", "generate", "dialogue", "review"}
            for call in own:
                request, payload = call["request"], call["payload"]
                assert str(request.url) == "https://8.8.8.8/v1/chat/completions"
                assert request.headers["authorization"] == "Bearer " + settings(design)["api_key"]
                assert request.extensions["sni_hostname"] == f"{student}.example"
                assert payload["model"] == settings(design)["model"]
                assert payload["thinking"] == {"type": "enabled" if design["thinking"] else "disabled"}
                assert payload["response_format"] == {"type": "json_object"}
                if call["task"] in ("dialogue", "review"):
                    data = json.loads(payload["messages"][-1]["content"])
                    assert data["scene"] == edited
                    assert edited["goal"] not in payload["messages"][0]["content"]
                if call["task"] == "generate":
                    assert json.loads(payload["messages"][-1]["content"]) == {
                        "description": design["description"], "grade": design["grade"]}

            view = await parent.get(f"/api/llm?student_id={student}", headers=parent_headers(student))
            assert view.json()["thinking"] is design["thinking"]
            assert view.json()["last_status"] == "ok"
            assert settings(design)["api_key"] not in view.text
    assert all(c["host"] != "platform.example" for c in h.calls)
    for request in h.public_requests:
        assert request.headers["authorization"].startswith("Bearer brain-")
        assert not any(settings(d)["api_key"].encode() in request.content for d in DESIGNS)


@pytest.mark.asyncio
@pytest.mark.parametrize("content,status,finish", [
    ("not JSON", 200, "stop"), ([], 200, "stop"), ({"correct": "yes"}, 200, "stop"),
    ({"ok": True}, 200, "stop"), ({"correct": True}, 200, "length"),
    ({"error": "bad credential"}, 401, "stop"),
])
async def test_bad_replacement_model_preserves_previous_settings(scene_system, content, status, finish):
    h, design = scene_system, DESIGNS[0]
    async with h.client() as client:
        assert (await save_model(client, design)).status_code == 200
        original = h.store.llm(design["student"])
        h.overrides["museum.example", "probe"] = {"content": content, "status": status, "finish": finish}
        rejected = await save_model(client, design, model="broken-model", api_key="fixture-replacement-key-5678", thinking=True)
        assert rejected.status_code == 422 and "未保存" in rejected.text
        assert h.store.llm(design["student"]) == original
        assert not any(c["host"] == "platform.example" for c in h.calls)


@pytest.mark.asyncio
async def test_key_reuse_and_student_authorization_are_scoped(scene_system):
    h, design = scene_system, DESIGNS[0]
    async with h.client() as client:
        assert (await save_model(client, design)).status_code == 200
        assert (await save_model(client, design, base_url="https://museum.example/v1/", api_key=None,
                                 model="replacement-fixture-model", thinking=True)).status_code == 200
        assert h.calls[-1]["request"].headers["authorization"] == "Bearer " + settings(design)["api_key"]
        count = len(h.calls)
        changed = await save_model(client, design, base_url="https://forest.example/v1", api_key=None)
        assert changed.status_code == 422 and "更换" in changed.text
        for headers, student in [(parent_headers("forest"), "museum"),
                                 ({"Authorization": "Bearer brain-museum-fixture-token"}, "museum")]:
            assert (await client.post(f"/api/scene/generate?student_id={student}", headers=headers,
                json={"description": design["description"], "grade": 2})).status_code == 403
            assert (await client.put(f"/api/llm?student_id={student}", headers=headers,
                json=settings(design))).status_code == 403
            assert (await client.get(f"/api/llm?student_id={student}", headers=headers)).status_code == 403
        assert len(h.calls) == count
        assert h.store.llm("forest") is None


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [
    {"robot_role": ""}, {"goal": " "}, {"opening": "你好"}, {"opening": "x" * 61},
    {"name": "x" * 41}, {"unexpected": "extra field"},
])
async def test_invalid_generated_scene_is_explicit_and_does_not_replace_config(scene_system, change):
    h, design = scene_system, DESIGNS[0]
    async with h.client() as client:
        assert (await save_model(client, design)).status_code == 200
        before = h.store.config("museum")
        h.overrides["museum.example", "generate"] = {"content": {**design["scene"], **change}}
        result = await generate(client, design)
        assert result.status_code == 422 and "格式" in result.text
        assert h.store.config("museum") == before
        assert not any(c["host"] == "platform.example" for c in h.calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("custom_failure", [{"content": [], "status": 200},
                                           {"content": {"error": "provider unavailable"}, "status": 503}])
async def test_generation_fallback_uses_platform_without_leaking_student_key(scene_system, custom_failure):
    h, design = scene_system, DESIGNS[0]
    async with h.client() as client:
        assert (await save_model(client, design, allow_platform_fallback=True)).status_code == 200
        h.overrides["museum.example", "generate"] = custom_failure
        result = await generate(client, design)
        assert result.status_code == 200 and result.json() == design["scene"]
        assert [c["host"] for c in h.calls[-2:]] == ["museum.example", "platform.example"]
        fallback = h.calls[-1]
        assert fallback["request"].headers["authorization"] == "Bearer " + h.provider.llm_key
        assert fallback["payload"]["model"] == h.provider.llm_model
        assert settings(design)["api_key"] not in fallback["request"].content.decode()
        status = (await client.get("/api/llm?student_id=museum", headers=parent_headers("museum"))).json()
        assert status["last_status"] == "fallback" and status["last_error"]


@pytest.mark.asyncio
async def test_custom_model_does_not_require_platform_and_failure_is_not_fake_success(scene_system):
    h, design = scene_system, DESIGNS[0]
    h.provider.llm_key = ""
    async with h.client() as client:
        missing = await generate(client, design)
        assert missing.status_code == 503 and "LLM_API_KEY" in missing.text
        assert h.calls == []
        assert (await save_model(client, design)).status_code == 200
        generated = await generate(client, design)
        assert generated.status_code == 200 and generated.json() == design["scene"]
        h.overrides["museum.example", "generate"] = {"content": {"error": "bad key"}, "status": 401}
        failed = await generate(client, design)
        assert failed.status_code == 503
        row = h.store.llm("museum")
        assert row["last_status"] == "error" and "密钥" in row["last_error"]
        assert h.store.config("museum")["scene"] is None
        assert not any(c["host"] == "platform.example" for c in h.calls)


@pytest.mark.asyncio
async def test_malformed_dialogue_can_retry_same_opening_without_losing_scene(scene_system):
    h, design = scene_system, DESIGNS[0]
    async with h.client() as client:
        assert (await save_model(client, design)).status_code == 200
        cfg = h.store.config("museum")
        cfg.update(mode="scene", scene=design["scene"])
        assert (await client.put("/api/config?student_id=museum", headers=parent_headers("museum"), json=cfg)).status_code == 200
    io = PublicClient("http://public.test", "museum", "brain-museum-fixture-token")
    brain = create_brain(io, "edge-museum-fixture-token")
    headers = {"Authorization": "Bearer edge-museum-fixture-token"}
    async with brain.router.lifespan_context(brain), httpx.AsyncClient(transport=httpx.ASGITransport(app=brain), base_url="http://brain.test") as edge:
        start = await edge.post("/voice/turn", headers=headers, json={"request_id": "museum-start-fixture", "action": "start"})
        assert start.status_code == 200
        opening = {"request_id": "museum-opening-fixture", "text": design["scene"]["opening"],
                   **{k: start.json()[k] for k in ("session_id", "question_id")}}
        h.overrides["museum.example", "dialogue"] = {"content": {"reply": [], "relevant": True}}
        assert (await edge.post("/voice/turn", headers=headers, json=opening)).status_code == 503
        assert brain.state.tutor.scene_opening_pending and brain.state.tutor.dialog_count == 0
        del h.overrides["museum.example", "dialogue"]
        recovered = await edge.post("/voice/turn", headers=headers, json=opening)
        assert recovered.status_code == 200, recovered.text
        assert not recovered.json()["scene_opening_pending"]
        assert brain.state.tutor.config["scene"] == design["scene"]
        assert h.store.progress("museum")["words"] == []
        count = len(h.calls)
        replay = await edge.post("/voice/turn", headers=headers, json=opening)
        assert replay.json() == recovered.json() and len(h.calls) == count
