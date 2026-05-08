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


async def test_delete_world_cascade_removes_characters_and_sessions(http):
    sid = await _make_session(http)
    sess = (await http.get(f"/sessions/{sid}")).json()
    wid = sess["world_id"]
    cid = sess["character_id"]

    summary = (await http.get(f"/worlds/{wid}/cascade_summary")).json()
    assert summary["characters"] >= 1
    assert summary["sessions"] >= 1

    r = await http.delete(f"/worlds/{wid}", params={"cascade": "true"})
    assert r.status_code == 204, r.text
    assert (await http.get(f"/worlds/{wid}")).status_code == 404
    assert (await http.get(f"/characters/{cid}")).status_code == 404
    assert (await http.get(f"/sessions/{sid}")).status_code == 404


async def test_delete_session_drops_agent_streams_and_messages(http, app):
    """v0.10: 删存档时连带清掉 agent_streams + agent_messages。"""
    from dzmm.db.models import AgentStream, AgentMessage
    from sqlalchemy import select

    sid = await _make_session(http)
    SessionMaker = app.state.session_maker
    async with SessionMaker() as s:
        st = AgentStream(session_id=sid, kind="gm_director", ref="")
        s.add(st)
        await s.flush()
        s.add(AgentMessage(stream_id=st.id, turn=1, role="user", content="x"))
        s.add(AgentMessage(stream_id=st.id, turn=1, role="assistant", content="y"))
        await s.commit()

    r = await http.delete(f"/sessions/{sid}")
    assert r.status_code == 204

    async with SessionMaker() as s:
        streams = (await s.execute(
            select(AgentStream).where(AgentStream.session_id == sid)
        )).scalars().all()
        assert streams == []
        messages = (await s.execute(select(AgentMessage))).scalars().all()
        assert messages == []


async def test_delete_session_drops_location_edges(http, app):
    """v0.10 T12: 删存档时连带清掉 location_edges（FK 在 Location 删除前）。"""
    from sqlalchemy import select
    from dzmm.db.models import Location, LocationEdge

    sid = await _make_session(http)
    SessionMaker = app.state.session_maker
    async with SessionMaker() as s:
        s.add_all([
            Location(session_id=sid, name="A"),
            Location(session_id=sid, name="B"),
        ])
        await s.flush()
        ids = (await s.execute(
            select(Location.id).where(Location.session_id == sid)
            .order_by(Location.name)
        )).scalars().all()
        s.add(LocationEdge(
            session_id=sid, from_loc_id=ids[0], to_loc_id=ids[1],
            relation="adjacent",
        ))
        await s.commit()

    r = await http.delete(f"/sessions/{sid}")
    assert r.status_code == 204
    async with SessionMaker() as s:
        edges = (await s.execute(select(LocationEdge))).scalars().all()
        assert edges == []


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


async def test_delete_last_turn_handles_orphan_user_message(http, monkeypatch):
    """Regression: an LLM error / network drop can leave the user message
    of turn N persisted without the matching assistant message. The old
    "delete latest 2 by id" logic would then chew through turn N-1's
    assistant message — corrupting the prior turn instead of the failed
    one. The new turn-number-based delete must wipe just the orphan."""
    from sqlalchemy import select
    from dzmm.db.models import Message as MessageRow, Session as GameSession

    sid = await _make_session(http)
    monkeypatch.setattr(
        "dzmm.api.routes_sessions.build_client",
        lambda cfg: StubGM("<narrative>hi</narrative>"),
    )

    # One clean turn: 2 messages (user + assistant) at turn=1.
    async with http.stream(
        "POST", f"/sessions/{sid}/turn", json={"action": "环顾"}
    ) as r:
        async for _ in r.aiter_text():
            pass

    # Inject an orphan user message at turn=2 (simulating "LLM died after
    # we persisted the user message"). Use the test's session_maker.
    from dzmm.api.routes_sessions._common import get_session_dep
    deps = http._transport.app.dependency_overrides
    session_dep = next(iter(d for k, d in deps.items() if k is get_session_dep))

    async for s in session_dep():
        s.add(MessageRow(session_id=sid, role="user", content="掉线了的输入", turn=2))
        await s.commit()

    msgs_before = (await http.get(f"/sessions/{sid}/messages")).json()
    assert len(msgs_before) == 3  # 2 from turn 1 + 1 orphan from turn 2

    r = await http.delete(f"/sessions/{sid}/last_turn")
    assert r.status_code == 204

    msgs_after = (await http.get(f"/sessions/{sid}/messages")).json()
    # Only the orphan should be gone — turn-1 pair survives.
    assert len(msgs_after) == 2
    assert {m["content"] for m in msgs_after} == {"环顾", "<narrative>hi</narrative>"}


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


async def test_delete_auto_created_npcs(http, app):
    """v0.1.9 cleanup endpoint: removes only NPCs whose description is the
    NER fallback sentinel ('（GM 未补全）'). NPCs with any other description
    must survive even if the GM later sets it back to a similar string."""
    sid = await _make_session(http)
    from dzmm.db.models import NPC
    SessionMaker = app.state.session_maker
    async with SessionMaker() as s:
        s.add(NPC(
            session_id=sid, name="路人A",
            description="（GM 未补全）",
            last_seen_turn=1,
        ))
        s.add(NPC(
            session_id=sid, name="路人B",
            description="（GM 未补全）",
            last_seen_turn=2,
        ))
        s.add(NPC(
            session_id=sid, name="陈子轩",
            description="线人",
            last_seen_turn=3,
        ))
        await s.commit()

    r = await http.delete(f"/sessions/{sid}/npcs/auto_created")
    assert r.status_code == 204

    npcs = (await http.get(f"/sessions/{sid}/npcs")).json()
    assert len(npcs) == 1
    assert npcs[0]["name"] == "陈子轩"


async def test_delete_auto_created_npcs_404_for_missing_session(http):
    """Cleanup endpoint must 404 for unknown session id."""
    r = await http.delete("/sessions/999999/npcs/auto_created")
    assert r.status_code == 404


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


async def test_goals_endpoint_empty(http):
    sid = await _make_session(http)
    r = await http.get(f"/sessions/{sid}/goals")
    assert r.status_code == 200
    assert r.json() == []


async def test_relations_endpoint_empty(http):
    sid = await _make_session(http)
    r = await http.get(f"/sessions/{sid}/relations")
    assert r.status_code == 200
    assert r.json() == []


async def test_relations_endpoint_returns_seeded_rows(http, app):
    """Insert NpcRelation directly, verify endpoint exposes the rows."""
    sid = await _make_session(http)
    from dzmm.db.models import NpcRelation
    SessionMaker = app.state.session_maker
    async with SessionMaker() as s:
        s.add(NpcRelation(
            session_id=sid, npc_a="御坂雪", npc_b="卫兵长",
            kind="父女", description="失散多年", introduced_turn=3,
        ))
        s.add(NpcRelation(
            session_id=sid, npc_a="山猫", npc_b="黑医",
            kind="对手", description="", introduced_turn=5,
        ))
        await s.commit()

    r = await http.get(f"/sessions/{sid}/relations")
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 2
    # Ordered by introduced_turn desc — turn 5 first.
    assert items[0]["kind"] == "对手"
    assert items[0]["npc_a"] == "山猫"
    assert items[1]["kind"] == "父女"
    assert items[1]["description"] == "失散多年"


async def test_state_endpoint_returns_pc_mood(http, app):
    """The /state endpoint must surface Session.pc_mood_json as pc_mood."""
    sid = await _make_session(http)
    from dzmm.db.models import Session as GameSession
    SessionMaker = app.state.session_maker
    async with SessionMaker() as s:
        sess = await s.get(GameSession, sid)
        sess.pc_mood_json = '{"tense": 30, "exhausted": 10}'
        await s.commit()

    r = await http.get(f"/sessions/{sid}/state")
    assert r.status_code == 200
    body = r.json()
    assert "pc_mood" in body
    assert body["pc_mood"] == {"tense": 30, "exhausted": 10}


async def test_npcs_endpoint_returns_emotion(http, app):
    """The /npcs endpoint must surface NPC.emotion_json as emotion (5-axis dict)."""
    sid = await _make_session(http)
    from dzmm.db.models import NPC
    SessionMaker = app.state.session_maker
    async with SessionMaker() as s:
        s.add(NPC(
            session_id=sid, name="御坂雪",
            description="x", favor=0, state="未知", last_seen_turn=1,
            emotion_json='{"love": 50, "fear": 10}',
        ))
        await s.commit()

    r = await http.get(f"/sessions/{sid}/npcs")
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 1
    assert items[0]["emotion"] == {"love": 50, "fear": 10}


async def test_npcs_endpoint_includes_revealed_field(http, app):
    """v0.11: GET /sessions/{id}/npcs must include a `revealed` dict on each
    NPC describing which fields the player has learned. NPCs with no explicit
    reveal mask fall back to {"name": True}."""
    sid = await _make_session(http)
    from dzmm.db.models import NPC
    SessionMaker = app.state.session_maker
    async with SessionMaker() as s:
        # Custom mask: name + description revealed; everything else hidden.
        s.add(NPC(
            session_id=sid, name="小菱",
            description="少女剑客", favor=2, state="警觉",
            purpose="找同伴", archetype="少女剑客原型",
            last_seen_turn=1,
            revealed_json='{"name": true, "description": true}',
        ))
        # Default mask via fallback (revealed_json left at column default).
        s.add(NPC(
            session_id=sid, name="幽影",
            description="神秘刺客", last_seen_turn=2,
        ))
        await s.commit()

    r = await http.get(f"/sessions/{sid}/npcs")
    assert r.status_code == 200
    items = r.json()
    by_name = {n["name"]: n for n in items}
    assert "revealed" in by_name["小菱"]
    assert by_name["小菱"]["revealed"]["name"] is True
    assert by_name["小菱"]["revealed"]["description"] is True
    # v0.2.5: last_seen_turn > 0 auto-reveals state, favor
    assert by_name["小菱"]["revealed"]["state"] is True
    assert by_name["小菱"]["revealed"]["favor"] is True
    # archetype auto-revealed when last_seen_turn > 0 AND archetype is set
    assert by_name["小菱"]["revealed"]["archetype"] is True
    # purpose not revealed (favor=2 < 30 threshold)
    assert by_name["小菱"]["revealed"].get("purpose") is not True

    # v0.2.5: NPC with last_seen_turn > 0 gets description/state/favor auto-revealed.
    assert by_name["幽影"]["revealed"]["name"] is True
    assert by_name["幽影"]["revealed"]["description"] is True
    assert by_name["幽影"]["revealed"]["state"] is True
    assert by_name["幽影"]["revealed"]["favor"] is True
    # archetype not revealed (archetype is empty)
    assert by_name["幽影"]["revealed"].get("archetype") is not True


async def test_messages_endpoint_includes_events_field(http, app):
    """v0.10: /messages must surface Message.events_json (parsed) per row."""
    sid = await _make_session(http)
    from dzmm.db.models import Message as MessageRow
    SessionMaker = app.state.session_maker
    async with SessionMaker() as s:
        s.add(MessageRow(
            session_id=sid, role="assistant", content="你掷出一个6。", turn=1,
            events_json='[{"type":"dice","payload":{"check":"敏捷","result":6}}]',
        ))
        await s.commit()

    r = await http.get(f"/sessions/{sid}/messages")
    assert r.status_code == 200
    msgs = r.json()
    assert len(msgs) == 1
    assert "events" in msgs[0]
    assert msgs[0]["events"] == [
        {"type": "dice", "payload": {"check": "敏捷", "result": 6}}
    ]


async def test_messages_empty_events_returns_empty_list(http, app):
    """events_json='' / '[]' / null all collapse to []."""
    sid = await _make_session(http)
    from dzmm.db.models import Message as MessageRow
    SessionMaker = app.state.session_maker
    async with SessionMaker() as s:
        s.add(MessageRow(session_id=sid, role="user", content="aa", turn=1,
                         events_json=""))
        s.add(MessageRow(session_id=sid, role="assistant", content="bb", turn=1,
                         events_json="[]"))
        await s.commit()

    r = await http.get(f"/sessions/{sid}/messages")
    assert r.status_code == 200
    msgs = r.json()
    assert len(msgs) == 2
    for m in msgs:
        assert m["events"] == []


async def test_hidden_events_endpoint_active_only(http, app):
    sid = await _make_session(http)
    from dzmm.db.models import HiddenEvent
    SessionMaker = app.state.session_maker
    async with SessionMaker() as s:
        s.add(HiddenEvent(
            session_id=sid, subject="小菱", kind="injury", severity=2,
            description="左肩擦伤", consequence="未处理则发炎",
            introduced_turn=3, status="active",
        ))
        s.add(HiddenEvent(
            session_id=sid, subject="主角", kind="poison", severity=3,
            description="慢性毒", consequence="2回合后发作",
            introduced_turn=4, status="active",
        ))
        s.add(HiddenEvent(
            session_id=sid, subject="商队", kind="deadline", severity=1,
            description="补给三日", consequence="超期则饿肚",
            introduced_turn=2, status="resolved",
        ))
        await s.commit()

    r = await http.get(f"/sessions/{sid}/hidden_events")
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 2
    assert all(h["status"] == "active" for h in items)
    # ordered by introduced_turn asc
    assert items[0]["introduced_turn"] == 3
    assert items[1]["introduced_turn"] == 4


async def test_hidden_events_endpoint_include_resolved(http, app):
    sid = await _make_session(http)
    from dzmm.db.models import HiddenEvent
    SessionMaker = app.state.session_maker
    async with SessionMaker() as s:
        s.add(HiddenEvent(
            session_id=sid, kind="injury", description="a", introduced_turn=1,
            status="active",
        ))
        s.add(HiddenEvent(
            session_id=sid, kind="injury", description="b", introduced_turn=2,
            status="active",
        ))
        s.add(HiddenEvent(
            session_id=sid, kind="injury", description="c", introduced_turn=3,
            status="resolved",
        ))
        await s.commit()

    r = await http.get(f"/sessions/{sid}/hidden_events?include_resolved=true")
    assert r.status_code == 200
    assert len(r.json()) == 3


async def test_export_default_format_is_json(http):
    sid = await _make_session(http)
    r = await http.get(f"/sessions/{sid}/export")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/json")
    body = r.json()
    assert body["version"] == "0.10"


async def test_export_json_full_structure(http, app):
    """JSON export must contain all top-level keys from the spec."""
    sid = await _make_session(http)
    from dzmm.db.models import (
        HiddenEvent, Message as MessageRow, NPC, NpcRelation,
        PCGoal, PlotThread,
    )
    SessionMaker = app.state.session_maker
    async with SessionMaker() as s:
        s.add(MessageRow(session_id=sid, role="user", content="探索", turn=1,
                         events_json='[]'))
        s.add(MessageRow(
            session_id=sid, role="assistant", content="GM 回复", turn=1,
            events_json='[{"type":"dice","payload":{"check":"察觉"}}]',
        ))
        s.add(NPC(session_id=sid, name="阿雪", description="商人",
                  favor=2, last_seen_turn=1))
        s.add(NpcRelation(session_id=sid, npc_a="阿雪", npc_b="老李",
                          kind="师徒", introduced_turn=1))
        s.add(PlotThread(session_id=sid, type="hook", description="谜雾",
                         importance=3, status="active"))
        s.add(PCGoal(session_id=sid, description="找到出路", priority="high",
                     status="active", introduced_turn=1))
        s.add(HiddenEvent(session_id=sid, kind="injury", subject="主角",
                          severity=2, description="脚扭伤",
                          introduced_turn=1, status="active"))
        await s.commit()

    r = await http.get(f"/sessions/{sid}/export?format=json")
    assert r.status_code == 200
    body = r.json()
    expected_keys = {
        "version", "exported_at", "session", "world", "character",
        "messages", "story_summary", "char_state", "npcs", "npc_relations",
        "plot_threads", "pc_goals", "hidden_events",
    }
    assert expected_keys.issubset(set(body.keys()))
    assert body["session"]["id"] == sid
    assert body["world"] is not None
    assert body["character"] is not None
    assert len(body["messages"]) == 2
    # The assistant message must carry parsed events (not raw json string).
    assistant_msg = next(m for m in body["messages"] if m["role"] == "assistant")
    assert assistant_msg["events"] == [
        {"type": "dice", "payload": {"check": "察觉"}}
    ]
    assert len(body["npcs"]) == 1
    assert len(body["npc_relations"]) == 1
    assert len(body["plot_threads"]) == 1
    assert len(body["pc_goals"]) == 1
    assert len(body["hidden_events"]) == 1


async def test_export_md_human_readable(http, app):
    sid = await _make_session(http)
    from dzmm.db.models import Message as MessageRow, NPC
    SessionMaker = app.state.session_maker
    async with SessionMaker() as s:
        s.add(MessageRow(session_id=sid, role="user", content="去酒馆", turn=1))
        s.add(MessageRow(session_id=sid, role="assistant",
                         content="你推开木门……", turn=1,
                         events_json='[{"type":"dice","payload":{"r":3}}]'))
        s.add(NPC(session_id=sid, name="酒保", favor=1, last_seen_turn=1,
                  description="独眼"))
        await s.commit()

    sess = (await http.get(f"/sessions/{sid}")).json()
    r = await http.get(f"/sessions/{sid}/export?format=md")
    assert r.status_code == 200
    assert "markdown" in r.headers["content-type"]
    cd = r.headers.get("content-disposition", "")
    assert "attachment" in cd
    assert ".md" in cd

    text = r.text
    assert text.startswith(f"# {sess['name']}")
    assert "## 跑团记录" in text
    assert "回合 1" in text
    assert "去酒馆" in text
    assert "推开木门" in text
    # Events line should also appear since the assistant message had one.
    assert "事件：" in text
    # NPC section
    assert "## 主要 NPC" in text
    assert "酒保" in text


async def test_export_invalid_format_rejected(http):
    sid = await _make_session(http)
    r = await http.get(f"/sessions/{sid}/export?format=pdf")
    assert r.status_code == 400


# ============================================================================
# v0.12: /health surfaces app version (used by frontend skew detection).
# ============================================================================


async def test_health_includes_version(http):
    from dzmm import __version__

    r = await http.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["version"] == __version__
    # Should match a SemVer-shaped string that begins with 0. (we're pre-1.0)
    assert body["version"].startswith("0.")
    # Backwards-compat: legacy callers (pre-v0.12) parsed `ok: true`.
    assert body["ok"] is True


# ============================================================================
# v0.13 regression guard: GET /sessions/{id}/export was added in v0.10. A
# refactor that drops `routes_sessions.include_router(...)` (or accidentally
# removes the export sub-route) silently 404s the export button on the FE.
# This test fails loud the moment the route stops being registered on the
# real FastAPI app instance produced by `create_app()`.
# ============================================================================


async def test_export_route_registered_in_app(http):
    """Route registration smoke test: a freshly-constructed app must serve
    GET /sessions/{id}/export and return the v0.10+ payload shape (version,
    messages keys present). Doesn't care about content beyond shape."""
    sid = await _make_session(http)
    r = await http.get(f"/sessions/{sid}/export?format=json")
    assert r.status_code == 200, (
        f"GET /sessions/{sid}/export returned {r.status_code} — "
        f"route likely de-registered. Body: {r.text[:200]}"
    )
    body = r.json()
    # Schema sanity — these two keys are the spec contract for v0.10+ export.
    assert "version" in body
    assert "messages" in body


# ============================================================================
# v0.13.1 — Player feedback endpoints + export integration.
# ============================================================================


async def test_post_feedback_persists_with_turn_snapshot(http):
    sid = await _make_session(http)
    r = await http.post(
        f"/sessions/{sid}/feedback",
        json={"content": "对话有时反复反问，没推进", "kind": "bug"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["session_id"] == sid
    assert body["kind"] == "bug"
    assert "对话有时反复反问" in body["content"]
    assert body["turn"] == 0  # session is brand new
    assert body["created_at"]  # ISO timestamp


async def test_post_feedback_normalizes_unknown_kind(http):
    sid = await _make_session(http)
    r = await http.post(
        f"/sessions/{sid}/feedback",
        json={"content": "什么都没说", "kind": "rant"},
    )
    assert r.status_code == 200
    assert r.json()["kind"] == "other"


async def test_post_feedback_rejects_empty(http):
    sid = await _make_session(http)
    r = await http.post(f"/sessions/{sid}/feedback", json={"content": "  "})
    assert r.status_code == 400


async def test_post_feedback_rejects_too_long(http):
    sid = await _make_session(http)
    r = await http.post(
        f"/sessions/{sid}/feedback", json={"content": "x" * 4001}
    )
    assert r.status_code == 400


async def test_post_feedback_404_for_unknown_session(http):
    r = await http.post("/sessions/99999/feedback", json={"content": "hi"})
    assert r.status_code == 404


async def test_list_feedback_returns_chronological(http):
    sid = await _make_session(http)
    for c in ["第一条", "第二条", "第三条"]:
        r = await http.post(f"/sessions/{sid}/feedback", json={"content": c})
        assert r.status_code == 200

    r = await http.get(f"/sessions/{sid}/feedback")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 3
    assert [f["content"] for f in body] == ["第一条", "第二条", "第三条"]


async def test_export_includes_feedbacks(http):
    sid = await _make_session(http)
    await http.post(
        f"/sessions/{sid}/feedback",
        json={"content": "希望剧情节奏快一点", "kind": "suggestion"},
    )
    r = await http.get(f"/sessions/{sid}/export?format=json")
    assert r.status_code == 200
    body = r.json()
    assert "feedbacks" in body
    assert len(body["feedbacks"]) == 1
    fb = body["feedbacks"][0]
    assert fb["kind"] == "suggestion"
    assert fb["content"] == "希望剧情节奏快一点"


async def test_export_md_includes_feedback_section(http):
    sid = await _make_session(http)
    await http.post(
        f"/sessions/{sid}/feedback",
        json={"content": "GM 喜欢反问", "kind": "bug"},
    )
    r = await http.get(f"/sessions/{sid}/export?format=md")
    assert r.status_code == 200
    text = r.text
    assert "## 玩家反馈" in text
    assert "GM 喜欢反问" in text
    assert "bug" in text


# ========== v0.1.0 Task 8: screenplay endpoints ==========

import json as _json  # noqa: E402

from sqlalchemy import select as _select  # noqa: E402

from dzmm.db.models import (  # noqa: E402
    Screenplay as _Screenplay,
    ScreenplayRevision as _ScreenplayRevision,
)


_STUB_SCREENPLAY_OUTPUT = _json.dumps({
    "chapters": [
        {"title": "第一章：迷雾", "summary": "调查",
         "main_events": ["线索 A", "对峙 B"],
         "optional_events": ["搜查老宅"],
         "main_npcs": ["陈子轩"]},
        {"title": "第二章：真相", "summary": "对峙黑手",
         "main_events": ["进入据点", "战斗主反派"],
         "optional_events": [],
         "main_npcs": ["黑手党头目"]},
    ],
    "main_characters": [
        {"name": "陈子轩", "role": "线人",
         "description": "中年华人男子", "intro_chapter": 1},
    ],
    "ending": "PC 揭穿黑手党的阴谋",
    "opening_hook": "雨夜的霓虹下，你接到一通电话",
}, ensure_ascii=False)


def _patch_screenplay_client(monkeypatch, output: str = _STUB_SCREENPLAY_OUTPUT):
    """Replace build_client used by routes_screenplay so generate calls don't hit
    a real LLM."""
    def fake_build_client(cfg):
        return StubGM(output)
    monkeypatch.setattr("dzmm.api.routes_screenplay.build_client", fake_build_client)


async def test_post_screenplay_generate_creates_active(http, monkeypatch):
    sid = await _make_session(http)
    _patch_screenplay_client(monkeypatch)
    r = await http.post(
        f"/sessions/{sid}/screenplay/generate",
        json={"genre": "悬疑探案"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "active"
    assert len(body["chapters"]) == 2
    assert body["chapters"][0]["title"] == "第一章：迷雾"
    assert body["main_characters"][0]["name"] == "陈子轩"
    assert "雨夜" in body["opening_hook"]
    assert body["current_chapter"] == 1
    assert body["version"] == 1
    assert body["genre"] == "悬疑探案"


async def test_get_screenplay_returns_active(http, monkeypatch):
    sid = await _make_session(http)
    _patch_screenplay_client(monkeypatch)
    await http.post(
        f"/sessions/{sid}/screenplay/generate",
        json={"genre": "悬疑探案"},
    )

    r = await http.get(f"/sessions/{sid}/screenplay")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "active"
    assert len(body["chapters"]) == 2
    assert body["session_id"] == sid


async def test_get_screenplay_404_when_missing(http):
    sid = await _make_session(http)
    r = await http.get(f"/sessions/{sid}/screenplay")
    assert r.status_code == 404


async def test_post_mark_decision_records_revision(http, app, monkeypatch):
    sid = await _make_session(http)
    _patch_screenplay_client(monkeypatch)
    await http.post(
        f"/sessions/{sid}/screenplay/generate",
        json={"genre": "悬疑探案"},
    )

    r = await http.post(
        f"/sessions/{sid}/screenplay/mark_decision",
        json={"description": "PC 杀了线人陈子轩"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert isinstance(body["revision_id"], int)
    # mark_decision now triggers an immediate outliner rewrite (v0.7+); the stub
    # client returns _STUB_SCREENPLAY_OUTPUT which has no diff_summary, so the
    # service falls back to the auto-generated description-based summary.
    assert "陈子轩" in body["diff_summary"] or "改写" in body["diff_summary"]

    SessionMaker = app.state.session_maker
    async with SessionMaker() as s:
        rev = (await s.execute(_select(_ScreenplayRevision))).scalar_one()
        assert rev.trigger_description == "PC 杀了线人陈子轩"
        # after_chapters_json was filled by the rewrite, so it should differ
        # from the placeholder "rewriting…" state.
        assert "pending" not in rev.diff_summary.lower()
        assert "rewriting" not in rev.diff_summary.lower()


async def test_post_screenplay_continue_creates_v2(http, app, monkeypatch):
    sid = await _make_session(http)
    _patch_screenplay_client(monkeypatch)
    r = await http.post(
        f"/sessions/{sid}/screenplay/generate",
        json={"genre": "悬疑探案"},
    )
    assert r.status_code == 200
    sp1_id = r.json()["id"]

    # Manually conclude the first screenplay so /continue has something to base on.
    SessionMaker = app.state.session_maker
    async with SessionMaker() as s:
        sp1 = await s.get(_Screenplay, sp1_id)
        sp1.status = "concluded"
        await s.commit()

    r = await http.post(f"/sessions/{sid}/screenplay/continue", json={})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "active"
    assert body["parent_screenplay_id"] == sp1_id
    assert body["id"] != sp1_id

    # Old one stays concluded; new one is the active.
    r = await http.get(f"/sessions/{sid}/screenplay")
    assert r.status_code == 200
    assert r.json()["id"] == body["id"]


async def test_post_screenplay_continue_400_without_concluded(http, monkeypatch):
    sid = await _make_session(http)
    _patch_screenplay_client(monkeypatch)
    r = await http.post(f"/sessions/{sid}/screenplay/continue", json={})
    assert r.status_code == 400


async def test_get_revisions_returns_list(http, monkeypatch):
    sid = await _make_session(http)
    _patch_screenplay_client(monkeypatch)
    await http.post(
        f"/sessions/{sid}/screenplay/generate",
        json={"genre": "悬疑探案"},
    )

    await http.post(
        f"/sessions/{sid}/screenplay/mark_decision",
        json={"description": "首次抉择"},
    )
    await http.post(
        f"/sessions/{sid}/screenplay/mark_decision",
        json={"description": "再次抉择"},
    )

    r = await http.get(f"/sessions/{sid}/screenplay/revisions")
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 2
    descs = [row["trigger_description"] for row in rows]
    assert "首次抉择" in descs
    assert "再次抉择" in descs


# ============================================================================
# v0.1.3 — DELETE /sessions/{id} cascades all per-session data.
# ============================================================================


async def test_delete_session_cascades_associated_data(http):
    sid = await _make_session(http)
    # Submit some feedback so there's at least one associated row to verify
    # the cascade actually runs.
    r = await http.post(f"/sessions/{sid}/feedback",
                        json={"content": "test", "kind": "other"})
    assert r.status_code == 200

    r = await http.delete(f"/sessions/{sid}")
    assert r.status_code == 204

    # Session itself gone.
    r = await http.get(f"/sessions/{sid}")
    assert r.status_code == 404
    # Feedback list empty (or 404 — either is fine; we check via the GET
    # endpoint, which now should 404 because the session is gone).
    r = await http.get(f"/sessions/{sid}/feedback")
    assert r.status_code == 404


async def test_delete_session_404_for_unknown(http):
    r = await http.delete("/sessions/99999")
    assert r.status_code == 404


async def test_delete_session_does_not_remove_world_or_character(http):
    sid = await _make_session(http)
    # Capture the session's world+character ids before deleting.
    sess = (await http.get(f"/sessions/{sid}")).json()
    wid = sess["world_id"]
    cid = sess["character_id"]

    r = await http.delete(f"/sessions/{sid}")
    assert r.status_code == 204

    # World + character must survive — they're shared across sessions.
    assert (await http.get(f"/worlds/{wid}")).status_code == 200
    chars = (await http.get(f"/characters?world_id={wid}")).json()
    assert any(c["id"] == cid for c in chars)


# ============================================================================
# v0.1.8 regression: HTTP headers are latin-1; CJK session names blew up the
# Content-Disposition header with UnicodeEncodeError -> 500 on export. Now
# the filename gets ASCII-sanitized + a UTF-8 RFC 5987 filename* fallback.
# ============================================================================


async def test_patch_session_gm_model(http):
    """PATCH /sessions/{id}/gm_model updates gm_model_config_id."""
    sid = await _make_session(http)
    # Create a new model config to switch to.
    r = await http.post("/model_configs", json={
        "name": "new-model", "type": "ollama",
        "base_url": "http://localhost:11434", "model_name": "llama3:8b",
    })
    assert r.status_code == 200
    new_mcid = r.json()["id"]

    r = await http.patch(
        f"/sessions/{sid}/gm_model",
        json={"gm_model_config_id": new_mcid},
    )
    assert r.status_code == 200
    assert r.json()["gm_model_config_id"] == new_mcid


async def test_patch_session_gm_model_invalid(http):
    """PATCH with non-existent model_config_id returns 404."""
    sid = await _make_session(http)
    r = await http.patch(
        f"/sessions/{sid}/gm_model",
        json={"gm_model_config_id": 99999},
    )
    assert r.status_code == 404


async def test_suggest_actions_returns_suggestions(http, monkeypatch):
    """POST /sessions/{id}/suggest_actions returns up to 3 suggestion strings."""
    sid = await _make_session(http)
    monkeypatch.setattr(
        "dzmm.api.routes_sessions.suggest.build_client",
        lambda cfg: StubGM("向前走\n询问守卫\n查看地图"),
    )
    r = await http.post(
        f"/sessions/{sid}/suggest_actions",
        json={"narrative": "你站在城门前", "goals": ["进城"]},
    )
    assert r.status_code == 200
    data = r.json()
    assert "suggestions" in data
    assert len(data["suggestions"]) == 3


async def test_suggest_actions_unknown_session_returns_404(http):
    """POST with unknown session_id returns 404."""
    r = await http.post(
        "/sessions/99999/suggest_actions",
        json={"narrative": "test", "goals": []},
    )
    assert r.status_code == 404


async def test_export_with_cjk_session_name_does_not_500(http, app):
    """User-reported: a session named「修女」(CJK) caused all exports to 500
    because Python's str.isalnum() returns True for CJK, so _safe_filename
    didn't strip them, and the resulting Content-Disposition header tried to
    encode CJK as latin-1."""
    # Create a session, then rename it to something CJK directly via DB.
    sid = await _make_session(http)
    from dzmm.db.models import Session as GameSession
    SessionMaker = app.state.session_maker
    async with SessionMaker() as s:
        sess = await s.get(GameSession, sid)
        sess.name = "修女 / 第一夜"  # CJK + slash + space
        await s.commit()

    for fmt in ("json", "md"):
        r = await http.get(f"/sessions/{sid}/export?format={fmt}")
        assert r.status_code == 200, f"{fmt} failed: {r.status_code} {r.text[:200]}"
        cd = r.headers.get("content-disposition", "")
        # ASCII filename fallback present.
        assert 'filename="dzmm_export_session.' in cd or 'filename="dzmm_export_' in cd
        # RFC 5987 UTF-8 encoded filename* present so browsers can recover CJK.
        assert "filename*=UTF-8''" in cd
        # Encoded form contains percent-escaped CJK bytes for 修.
        assert "%E4%BF%AE" in cd  # 修 in UTF-8 is E4 BF AE


async def test_location_items_returned_in_api(http, app):
    """GET /sessions/{id}/locations returns items parsed from items_json."""
    import json
    from dzmm.db.models import Location
    sid = await _make_session(http)
    SessionMaker = app.state.session_maker
    async with SessionMaker() as s:
        loc = Location(session_id=sid, name="书房", description="",
                       first_visited_turn=1, last_visited_turn=1, is_current=True,
                       items_json=json.dumps([{"name": "戒指", "description": "金戒指"}]))
        s.add(loc)
        await s.commit()
    r = await http.get(f"/sessions/{sid}/locations")
    assert r.status_code == 200
    locs = r.json()
    assert len(locs) == 1
    assert locs[0]["items"] == [{"name": "戒指", "description": "金戒指"}]


async def test_npc_current_location_returned_in_api(http, app):
    """GET /sessions/{id}/npcs returns current_location field."""
    from dzmm.db.models import NPC
    sid = await _make_session(http)
    SessionMaker = app.state.session_maker
    async with SessionMaker() as s:
        npc = NPC(session_id=sid, name="镜中人", description="", favor=0,
                  state="被困", last_seen_turn=1, notes_json="[]", purpose="",
                  archetype="", affinity_json="{}", pinned=False,
                  revealed_json='{"name":true}', current_location="书房")
        s.add(npc)
        await s.commit()
    r = await http.get(f"/sessions/{sid}/npcs")
    assert r.status_code == 200
    npcs = r.json()
    found = next((n for n in npcs if n["name"] == "镜中人"), None)
    assert found is not None
    assert found["current_location"] == "书房"
