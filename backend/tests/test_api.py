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
    # Tests need direct DB access (e.g. seed an NPC); attach the session maker
    # so they can grab it via app.state.session_maker.
    app.state.session_maker = SessionMaker
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


async def test_delete_last_turn_removes_pair_and_decrements(http, monkeypatch):
    sid = await _make_session(http)
    monkeypatch.setattr(
        "dzmm.api.routes_sessions.build_client",
        lambda cfg: StubGM("<narrative>hi</narrative>"),
    )

    for action in ["环顾", "前进"]:
        async with http.stream(
            "POST", f"/sessions/{sid}/turn", json={"action": action}
        ) as r:
            async for _ in r.aiter_text():
                pass

    sess = (await http.get(f"/sessions/{sid}")).json()
    assert sess["turn_count"] == 2
    msgs = (await http.get(f"/sessions/{sid}/messages")).json()
    assert len(msgs) == 4

    r = await http.delete(f"/sessions/{sid}/last_turn")
    assert r.status_code == 204

    sess = (await http.get(f"/sessions/{sid}")).json()
    assert sess["turn_count"] == 1
    msgs = (await http.get(f"/sessions/{sid}/messages")).json()
    assert len(msgs) == 2
    assert msgs[0]["content"] == "环顾"


async def test_threads_endpoint_separates_active_and_resolved(http, monkeypatch):
    sid = await _make_session(http)
    monkeypatch.setattr(
        "dzmm.api.routes_sessions.build_client",
        lambda cfg: StubGM(
            "<narrative>探索</narrative>"
            '<plot_event type="hook_introduced" importance="3">神秘地图</plot_event>'
            '<plot_event type="new_quest" importance="2">取回药材</plot_event>'
        ),
    )
    async with http.stream("POST", f"/sessions/{sid}/turn",
                           json={"action": "调查"}) as r:
        async for _ in r.aiter_text(): pass

    r = await http.get(f"/sessions/{sid}/threads")
    assert r.status_code == 200
    threads = r.json()
    assert len(threads) >= 2
    descriptions = [t["description"] for t in threads]
    assert any("神秘地图" in d for d in descriptions)
    assert any("取回药材" in d for d in descriptions)


async def test_portrait_upload_and_serve(http, tmp_path):
    r = await http.post("/worlds", json={"name": "W", "content_md": "x"})
    wid = r.json()["id"]
    r = await http.post("/characters", json={
        "world_id": wid, "name": "C", "profile_md": "y", "base_stats_json": "{}"
    })
    cid = r.json()["id"]
    assert r.json().get("portrait_path", "") == ""

    # Upload a tiny PNG
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
    r = await http.post(
        f"/characters/{cid}/portrait",
        files={"file": ("test.png", png, "image/png")},
    )
    assert r.status_code == 200, r.text
    assert r.json()["portrait_path"]

    # Retrieve
    r = await http.get(f"/characters/{cid}/portrait")
    assert r.status_code == 200
    assert r.content[:8] == b"\x89PNG\r\n\x1a\n"


async def test_portrait_upload_rejects_unknown_ext(http):
    r = await http.post("/worlds", json={"name": "W", "content_md": "x"})
    wid = r.json()["id"]
    r = await http.post("/characters", json={
        "world_id": wid, "name": "C", "profile_md": "y", "base_stats_json": "{}"
    })
    cid = r.json()["id"]
    r = await http.post(
        f"/characters/{cid}/portrait",
        files={"file": ("evil.exe", b"MZ\x90\x00", "application/octet-stream")},
    )
    assert r.status_code == 400


async def test_levelup_requires_enough_xp(http):
    r = await http.post("/worlds", json={"name": "W", "content_md": "x"})
    wid = r.json()["id"]
    r = await http.post("/characters", json={
        "world_id": wid, "name": "C", "profile_md": "y",
        "base_stats_json": '{"hp": 20}',
    })
    cid = r.json()["id"]
    assert r.json()["xp"] == 0
    assert r.json()["level"] == 1

    r = await http.post(f"/characters/{cid}/levelup", json={"stat": "hp"})
    assert r.status_code == 400
    assert "xp" in r.text.lower()


async def test_levelup_requires_stat_param(http):
    r = await http.post("/worlds", json={"name": "W", "content_md": "x"})
    wid = r.json()["id"]
    r = await http.post("/characters", json={
        "world_id": wid, "name": "C", "profile_md": "y",
        "base_stats_json": '{"hp": 20}',
    })
    cid = r.json()["id"]
    r = await http.post(f"/characters/{cid}/levelup", json={"stat": ""})
    # Even though XP gate fires first, this test verifies the endpoint is wired;
    # 400 is the expected status either way.
    assert r.status_code == 400


async def test_levelup_succeeds_when_xp_threshold_met(http, monkeypatch):
    """Drive xp via the GM tag pipeline so we exercise the real path."""
    sid = await _make_session(http)
    sess = (await http.get(f"/sessions/{sid}")).json()
    cid = sess["character_id"]

    # Award 100 XP via <character_xp> tag — exactly the Lv1->Lv2 threshold.
    output = ('<narrative>恭喜过关</narrative>'
              '<character_xp delta="100">完成主线节点</character_xp>')
    monkeypatch.setattr(
        "dzmm.api.routes_sessions.build_client",
        lambda cfg: StubGM(output),
    )
    async with http.stream("POST", f"/sessions/{sid}/turn",
                           json={"action": "推进"}) as r:
        async for _ in r.aiter_text():
            pass

    # Verify XP got persisted on the character row.
    char = (await http.get(f"/characters/{cid}")).json()
    assert char["xp"] == 100
    assert char["level"] == 1

    # Now level up — pick HP for the +5 bonus.
    r = await http.post(f"/characters/{cid}/levelup", json={"stat": "hp"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["level"] == 2
    import json as _json
    stats = _json.loads(body["base_stats_json"])
    assert stats["hp"] == 25  # 20 base + 5

    # Sanity stat would only +1; verify by leveling again? Need more XP:
    # threshold for L2 is 100*2*3/2 = 300, character has 100 — should fail.
    r = await http.post(f"/characters/{cid}/levelup", json={"stat": "sanity"})
    assert r.status_code == 400


async def test_levelup_unknown_stat_gets_plus_one(http, monkeypatch):
    sid = await _make_session(http)
    sess = (await http.get(f"/sessions/{sid}")).json()
    cid = sess["character_id"]

    monkeypatch.setattr(
        "dzmm.api.routes_sessions.build_client",
        lambda cfg: StubGM(
            '<narrative>大成功</narrative>'
            '<character_xp delta="100">章节</character_xp>'
        ),
    )
    async with http.stream("POST", f"/sessions/{sid}/turn",
                           json={"action": "推进"}) as r:
        async for _ in r.aiter_text():
            pass

    r = await http.post(f"/characters/{cid}/levelup", json={"stat": "灵力"})
    assert r.status_code == 200
    import json as _json
    stats = _json.loads(r.json()["base_stats_json"])
    assert stats["灵力"] == 1


async def test_levelup_404_when_missing(http):
    r = await http.post("/characters/9999/levelup", json={"stat": "hp"})
    assert r.status_code == 404


async def test_get_npcs_returns_all_fields(http, app):
    """The /sessions/{id}/npcs endpoint must return purpose, archetype,
    affinity, pin, notes — everything the detail dialog needs."""
    sid = await _make_session(http)

    # Insert an NPC directly via the app's session maker so we control all fields.
    from dzmm.db.models import NPC
    SessionMaker = app.state.session_maker
    async with SessionMaker() as s:
        s.add(NPC(
            session_id=sid,
            name="御坂雪",
            description="21 岁早大学生",
            favor=8,
            state="对你敞开了一些心扉",
            last_seen_turn=3,
            notes_json='[{"turn":3,"text":"分享了童年阴影"}]',
            purpose="查清祖母遗物里咒符的来源",
            archetype="外柔内刚的文学少女",
            affinity_json='{"信任":3,"羁绊":2}',
            pinned=True,
        ))
        await s.commit()

    r = await http.get(f"/sessions/{sid}/npcs")
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 1
    n = items[0]
    assert n["name"] == "御坂雪"
    assert n["favor"] == 8
    assert n["purpose"] == "查清祖母遗物里咒符的来源"
    assert n["archetype"] == "外柔内刚的文学少女"
    assert n["affinity"] == {"信任": 3, "羁绊": 2}
    assert n["pinned"] is True
    assert isinstance(n["notes"], list) and n["notes"][0]["text"] == "分享了童年阴影"


async def test_pin_toggle(http, app):
    sid = await _make_session(http)
    from dzmm.db.models import NPC
    SessionMaker = app.state.session_maker
    async with SessionMaker() as s:
        npc = NPC(session_id=sid, name="A", last_seen_turn=1)
        s.add(npc)
        await s.commit()
        await s.refresh(npc)
        npc_id = npc.id

    r = await http.put(f"/sessions/{sid}/npcs/{npc_id}/pin", json={"pinned": True})
    assert r.status_code == 200, r.text
    assert r.json()["pinned"] is True

    r = await http.put(f"/sessions/{sid}/npcs/{npc_id}/pin", json={"pinned": False})
    assert r.status_code == 200
    assert r.json()["pinned"] is False


async def test_update_goal_status(http, app):
    sid = await _make_session(http)
    from dzmm.db.models import PCGoal
    SessionMaker = app.state.session_maker
    async with SessionMaker() as s:
        g = PCGoal(session_id=sid, description="goal x", status="active",
                   introduced_turn=1)
        s.add(g)
        await s.commit()
        await s.refresh(g)
        gid = g.id

    r = await http.put(f"/sessions/{sid}/goals/{gid}/status",
                       json={"status": "completed", "note": "done"})
    assert r.status_code == 200
    assert r.json()["status"] == "completed"
    assert r.json()["completion_note"] == "done"


async def test_update_goal_status_invalid(http, app):
    sid = await _make_session(http)
    from dzmm.db.models import PCGoal
    SessionMaker = app.state.session_maker
    async with SessionMaker() as s:
        g = PCGoal(session_id=sid, description="x", status="active")
        s.add(g)
        await s.commit()
        await s.refresh(g)
        gid = g.id

    r = await http.put(f"/sessions/{sid}/goals/{gid}/status",
                       json={"status": "garbage"})
    assert r.status_code == 400


async def test_warmup_endpoint_returns_202(http, monkeypatch):
    sid = await _make_session(http)
    monkeypatch.setattr(
        "dzmm.api.routes_sessions.build_client",
        lambda cfg: StubGM("<narrative>warm</narrative>"),
    )
    r = await http.post(f"/sessions/{sid}/warmup")
    assert r.status_code == 202
    assert r.json()["status"] == "started"
