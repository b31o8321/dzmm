"""GET /sessions/{id}/agents — DebugView "Agents" tab data source."""
import pytest
from httpx import ASGITransport, AsyncClient

from dzmm.db.base import async_session, get_engine, init_db
from dzmm.db.models import AgentMessage, AgentStream
from dzmm.main import create_app


@pytest.fixture
async def app(tmp_path):
    db_url = f"sqlite+aiosqlite:///{tmp_path}/t.db"
    engine = get_engine(db_url)
    await init_db(engine)
    SessionMaker = async_session(engine)
    app = create_app(SessionMaker)
    app.state.session_maker = SessionMaker
    yield app
    await engine.dispose()


@pytest.fixture
async def http(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def _make_session(http):
    r = await http.post("/worlds", json={"name": "W", "content_md": "x"})
    wid = r.json()["id"]
    r = await http.post("/characters", json={
        "world_id": wid, "name": "C", "profile_md": "y",
        "base_stats_json": "{}",
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


async def test_get_session_agents_returns_streams_and_recent_messages(http, app):
    sid = await _make_session(http)
    SessionMaker = app.state.session_maker
    async with SessionMaker() as s:
        st = AgentStream(session_id=sid, kind="npc", ref="丽莎", last_run_turn=3)
        s.add(st)
        await s.flush()
        for t, c in [(1, "u1"), (1, "a1"), (2, "u2"), (2, "a2"), (3, "u3"), (3, "a3")]:
            role = "user" if c.startswith("u") else "assistant"
            s.add(AgentMessage(stream_id=st.id, turn=t, role=role, content=c))
        await s.commit()

    r = await http.get(f"/sessions/{sid}/agents")
    assert r.status_code == 200
    data = r.json()
    assert len(data["streams"]) == 1
    st0 = data["streams"][0]
    assert st0["kind"] == "npc"
    assert st0["ref"] == "丽莎"
    assert st0["last_run_turn"] == 3
    assert len(st0["recent_messages"]) <= 12
    assert st0["recent_messages"][-1]["content"] == "a3"


async def test_get_session_agents_404(http):
    r = await http.get("/sessions/999999/agents")
    assert r.status_code == 404
