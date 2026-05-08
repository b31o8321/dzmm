"""Tests for v0.10 multi-agent stateful streams (AgentStream + AgentMessage).

Uses the same fixture pattern as test_api.py / test_factions.py — each test
file defines its own `app` fixture (no shared conftest fixture).
"""
import pytest
from sqlalchemy import select

from dzmm.db.base import init_db, get_engine, async_session
from dzmm.db.models import AgentStream, AgentMessage
from dzmm.main import create_app


# ── fixtures (mirrors test_api.py) ────────────────────────────────────────

@pytest.fixture
async def app(tmp_path):
    db_url = f"sqlite+aiosqlite:///{tmp_path}/t_agent_streams.db"
    engine = get_engine(db_url)
    await init_db(engine)
    SessionMaker = async_session(engine)
    app = create_app(SessionMaker)
    app.state.session_maker = SessionMaker
    yield app
    await engine.dispose()


@pytest.mark.asyncio
async def test_agent_stream_unique_per_session_kind_ref(app):
    """同一 (session_id, kind, ref) 只能有一条 stream — 用于 get_or_create 幂等。"""
    SessionMaker = app.state.session_maker
    async with SessionMaker() as s:
        s.add(AgentStream(session_id=1, kind="npc", ref="王五"))
        await s.commit()
        s.add(AgentStream(session_id=1, kind="npc", ref="王五"))
        with pytest.raises(Exception):  # IntegrityError or similar
            await s.commit()


@pytest.mark.asyncio
async def test_agent_message_belongs_to_stream(app):
    SessionMaker = app.state.session_maker
    async with SessionMaker() as s:
        stream = AgentStream(session_id=1, kind="gm_director", ref="")
        s.add(stream)
        await s.flush()
        s.add(AgentMessage(
            stream_id=stream.id, turn=3, role="user",
            content="snapshot at turn 3",
        ))
        await s.commit()

        rows = (await s.execute(
            select(AgentMessage).where(AgentMessage.stream_id == stream.id)
        )).scalars().all()
        assert len(rows) == 1
        assert rows[0].turn == 3
