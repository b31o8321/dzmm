import pytest
from collections.abc import AsyncIterator
from httpx import ASGITransport, AsyncClient

from dzmm.db.base import init_db, get_engine, async_session
from dzmm.main import create_app
from dzmm.models.client import GenerationParams, Message, ModelClient, StreamChunk, TokenUsage


@pytest.fixture
async def app(tmp_path):
    db_url = f"sqlite+aiosqlite:///{tmp_path}/t.db"
    engine = get_engine(db_url)
    await init_db(engine)
    SessionMaker = async_session(engine)
    app = create_app(SessionMaker)
    yield app
    await engine.dispose()


@pytest.fixture
async def http(app):
    async with AsyncClient(transport=ASGITransport(app=app),
                           base_url="http://test") as c:
        yield c


# ========== Task 14: worlds, characters, model_configs ==========

async def test_create_and_list_world(http):
    r = await http.post("/worlds", json={
        "name": "Cyberpunk", "content_md": "Neon city.", "style": "dark"
    })
    assert r.status_code == 200, r.text
    wid = r.json()["id"]

    r = await http.get("/worlds")
    assert r.status_code == 200
    items = r.json()
    assert any(w["id"] == wid for w in items)


async def test_create_character_for_world(http):
    r = await http.post("/worlds", json={"name": "W", "content_md": "x"})
    wid = r.json()["id"]
    r = await http.post("/characters", json={
        "world_id": wid, "name": "Riku", "profile_md": "黑客",
        "base_stats_json": '{"hp":20,"sanity":15}'
    })
    assert r.status_code == 200
    cid = r.json()["id"]

    r = await http.get(f"/characters?world_id={wid}")
    assert r.status_code == 200
    assert any(c["id"] == cid for c in r.json())


async def test_create_model_config_with_api_key(http, monkeypatch):
    stored = {}

    def fake_store(ref, value):
        stored[ref] = value

    monkeypatch.setattr("dzmm.api.routes_models.store_api_key", fake_store)

    r = await http.post("/model_configs", json={
        "name": "doubao", "type": "openai_compat",
        "base_url": "https://x", "model_name": "ep",
        "api_key": "sk-secret",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["api_key_ref"] is not None
    assert "api_key" not in body
    assert "sk-secret" not in r.text
    assert stored.get(body["api_key_ref"]) == "sk-secret"


async def test_create_model_config_without_key(http):
    r = await http.post("/model_configs", json={
        "name": "local", "type": "ollama",
        "base_url": "http://localhost:11434", "model_name": "qwen2.5:7b",
    })
    assert r.status_code == 200
    assert r.json()["api_key_ref"] is None


# ========== Task 15: sessions + turn SSE ==========

class StubGM(ModelClient):
    name = "stub"

    def __init__(self, output: str):
        self.output = output

    async def stream(
        self, messages: list[Message], params: GenerationParams
    ) -> AsyncIterator[StreamChunk]:
        yield StreamChunk(delta=self.output)
        yield StreamChunk(delta="", finish_reason="stop",
                          usage=TokenUsage(input_tokens=5, output_tokens=10))


async def _make_session(http):
    r = await http.post("/worlds", json={"name": "W", "content_md": "x", "style": "dark"})
    wid = r.json()["id"]
    r = await http.post("/characters", json={
        "world_id": wid, "name": "C", "profile_md": "y",
        "base_stats_json": '{"hp":20,"sanity":15}',
    })
    cid = r.json()["id"]
    r = await http.post("/model_configs", json={
        "name": "local", "type": "ollama",
        "base_url": "http://localhost:11434", "model_name": "qwen2.5:7b",
    })
    mcid = r.json()["id"]
    r = await http.post("/sessions", json={
        "name": "run1", "world_id": wid, "character_id": cid,
        "gm_model_config_id": mcid, "summarizer_model_config_id": mcid,
    })
    return r.json()["id"]


async def test_create_session(http):
    sid = await _make_session(http)
    assert isinstance(sid, int)

    r = await http.get(f"/sessions/{sid}")
    assert r.status_code == 200
    assert r.json()["turn_count"] == 0


async def test_turn_streams_sse(http, monkeypatch):
    sid = await _make_session(http)
    output = ('<narrative>你站在街口。</narrative>'
              '<state_change>{"sanity":-1}</state_change>')

    def fake_build_client(cfg):
        return StubGM(output)

    monkeypatch.setattr("dzmm.api.routes_sessions.build_client", fake_build_client)

    async with http.stream("POST", f"/sessions/{sid}/turn",
                           json={"action": "环顾四周"}) as r:
        assert r.status_code == 200
        text = ""
        async for chunk in r.aiter_text():
            text += chunk

    assert "你站在街口" in text
    assert "narrative" in text  # SSE event names appear in stream

    r = await http.get(f"/sessions/{sid}")
    assert r.json()["turn_count"] == 1


async def test_update_world(http):
    r = await http.post("/worlds", json={"name": "W", "content_md": "x"})
    wid = r.json()["id"]
    r = await http.put(f"/worlds/{wid}", json={
        "name": "W2", "content_md": "y", "style": "horror", "rules_mode": "standard"
    })
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "W2"
    assert r.json()["style"] == "horror"


async def test_delete_world_cascading_refusal(http):
    r = await http.post("/worlds", json={"name": "W", "content_md": "x"})
    wid = r.json()["id"]
    r = await http.post("/characters", json={
        "world_id": wid, "name": "C", "profile_md": "y", "base_stats_json": "{}"
    })
    assert r.status_code == 200
    r = await http.delete(f"/worlds/{wid}")
    assert r.status_code == 409, r.text


async def test_delete_world_succeeds_when_unused(http):
    r = await http.post("/worlds", json={"name": "Wempty", "content_md": "x"})
    wid = r.json()["id"]
    r = await http.delete(f"/worlds/{wid}")
    assert r.status_code == 204, r.text
    r = await http.get(f"/worlds/{wid}")
    assert r.status_code == 404


async def test_update_character(http):
    r = await http.post("/worlds", json={"name": "W", "content_md": "x"})
    wid = r.json()["id"]
    r = await http.post("/characters", json={
        "world_id": wid, "name": "C", "profile_md": "y", "base_stats_json": "{}"
    })
    cid = r.json()["id"]
    r = await http.put(f"/characters/{cid}", json={
        "world_id": wid, "name": "C2", "profile_md": "updated",
        "base_stats_json": '{"hp":30}'
    })
    assert r.status_code == 200
    assert r.json()["name"] == "C2"


async def test_delete_character_blocked_by_session(http):
    sid = await _make_session(http)
    chars = (await http.get("/characters")).json()
    cid = chars[0]["id"]
    r = await http.delete(f"/characters/{cid}")
    assert r.status_code == 409


async def test_update_model_config_no_key_change(http):
    r = await http.post("/model_configs", json={
        "name": "local", "type": "ollama",
        "base_url": "http://localhost:11434", "model_name": "qwen2.5:7b",
    })
    mid = r.json()["id"]
    r = await http.put(f"/model_configs/{mid}", json={
        "name": "local-v2", "type": "ollama",
        "base_url": "http://localhost:11434", "model_name": "llama3:8b",
        "timeout": 120
    })
    assert r.status_code == 200
    assert r.json()["name"] == "local-v2"
    assert r.json()["model_name"] == "llama3:8b"
    assert r.json()["timeout"] == 120


async def test_delete_model_config_blocked_by_session(http):
    sid = await _make_session(http)
    sess = (await http.get(f"/sessions/{sid}")).json()
    r = await http.delete(f"/model_configs/{sess['gm_model_config_id']}")
    assert r.status_code == 409


async def test_delete_unused_model_config(http):
    r = await http.post("/model_configs", json={
        "name": "x", "type": "ollama",
        "base_url": "http://x", "model_name": "y",
    })
    mid = r.json()["id"]
    r = await http.delete(f"/model_configs/{mid}")
    assert r.status_code == 204
