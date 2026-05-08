"""v0.10: delete_last_turn 同步回滚 agent_streams 历史。"""
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from dzmm.db.base import async_session, get_engine, init_db
from dzmm.db.models import (
    AgentMessage,
    AgentStream,
    Message as MessageRow,
    Session as GameSession,
)
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


async def test_delete_last_turn_rolls_back_agent_messages(http, app):
    """delete_last_turn 把 turn=N 的所有 agent_messages 一并 pop。"""
    sid = await _make_session(http)
    SessionMaker = app.state.session_maker
    async with SessionMaker() as s:
        st = AgentStream(session_id=sid, kind="gm_director", ref="",
                         last_run_turn=2)
        s.add(st)
        await s.flush()
        for t, content in [(1, "a"), (2, "b"), (2, "b2")]:
            s.add(AgentMessage(stream_id=st.id, turn=t, role="user", content=content))
        s.add(MessageRow(session_id=sid, role="user", content="x", turn=1))
        s.add(MessageRow(session_id=sid, role="assistant", content="y", turn=1))
        s.add(MessageRow(session_id=sid, role="user", content="x2", turn=2))
        s.add(MessageRow(session_id=sid, role="assistant", content="y2", turn=2))
        sess = await s.get(GameSession, sid)
        sess.turn_count = 2
        await s.commit()

    r = await http.delete(f"/sessions/{sid}/last_turn")
    assert r.status_code == 204

    async with SessionMaker() as s:
        rows = (await s.execute(select(AgentMessage))).scalars().all()
        assert {r.turn for r in rows} == {1}, "only turn 1 should survive"
        st_after = (await s.execute(
            select(AgentStream).where(AgentStream.session_id == sid)
        )).scalar_one()
        assert st_after.last_run_turn == 1, "stream's last_run_turn rewound"
