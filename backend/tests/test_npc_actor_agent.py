import pytest
from sqlalchemy import select
from types import SimpleNamespace

from dzmm.db.base import async_session, get_engine, init_db
from dzmm.db.models import AgentMessage, AgentStream
from dzmm.models.client import ModelClient, StreamChunk, TokenUsage
from dzmm.parsing.events import TagComplete
from dzmm.service.agents.npc_actor import run_npc_actor


@pytest.fixture
async def session_maker(tmp_path):
    db_url = f"sqlite+aiosqlite:///{tmp_path}/t.db"
    engine = get_engine(db_url)
    await init_db(engine)
    sm = async_session(engine)
    yield sm
    await engine.dispose()


class _StubNpc(ModelClient):
    name = "stub"
    def __init__(self, output: str):
        self._output = output
    async def stream(self, msgs, params):
        yield StreamChunk(delta="", finish_reason="stop")
    async def complete(self, msgs, params):
        return self._output, TokenUsage()


def _npc(name="丽莎", **kw):
    return SimpleNamespace(
        name=name, gender=kw.get("gender", "female"),
        archetype=kw.get("archetype", "热心邻家少女"),
        description=kw.get("description", "21 岁，话密"),
        state=kw.get("state", "焦虑"),
        purpose=kw.get("purpose", "找弟弟"),
        emotion_json=kw.get("emotion_json", '{"fear": 60}'),
    )


@pytest.mark.asyncio
async def test_run_npc_actor_returns_say_and_npc_update(session_maker):
    output = (
        '<say speaker="丽莎" mood="焦虑">「快走，他们要来了！」</say>'
        '<npc_update name="丽莎">{"emotion": {"fear": +10}}</npc_update>'
    )
    async with session_maker() as s:
        events = await run_npc_actor(
            s, npc=_npc(), session_id=1,
            plot_directive="x", scene_narrative="霓虹下雨",
            user_action="拉她的手", client=_StubNpc(output),
            current_turn=1,
        )
        await s.commit()
    say = [e for e in events if isinstance(e, TagComplete) and e.name == "say"]
    upd = [e for e in events if isinstance(e, TagComplete) and e.name == "npc_update"]
    assert len(say) == 1
    assert say[0].attrs.get("speaker") == "丽莎"
    assert "走" in say[0].content
    assert len(upd) == 1


@pytest.mark.asyncio
async def test_run_npc_actor_noop_returns_empty(session_maker):
    async with session_maker() as s:
        events = await run_npc_actor(
            s, npc=_npc(), session_id=1,
            plot_directive="x", scene_narrative="y",
            user_action="z", client=_StubNpc("<noop/>"),
            current_turn=1,
        )
        await s.commit()
    assert events == []


@pytest.mark.asyncio
async def test_run_npc_actor_persists_history(session_maker):
    async with session_maker() as s:
        await run_npc_actor(
            s, npc=_npc(), session_id=1,
            plot_directive="x", scene_narrative="y",
            user_action="z", client=_StubNpc('<say speaker="丽莎">「在」</say>'),
            current_turn=3,
        )
        await s.commit()

    async with session_maker() as s:
        streams = (await s.execute(
            select(AgentStream).where(
                AgentStream.session_id == 1, AgentStream.kind == "npc"
            )
        )).scalars().all()
        assert len(streams) == 1 and streams[0].ref == "丽莎"
        assert streams[0].last_run_turn == 3
        msgs = (await s.execute(
            select(AgentMessage).where(AgentMessage.stream_id == streams[0].id)
            .order_by(AgentMessage.id)
        )).scalars().all()
        assert [m.role for m in msgs] == ["user", "assistant"]
        assert "y" in msgs[0].content  # scene snippet was persisted
