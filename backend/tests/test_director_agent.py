import pytest
from sqlalchemy import select

from dzmm.db.base import async_session, get_engine, init_db
from dzmm.db.models import AgentMessage, AgentStream
from dzmm.models.client import ModelClient, StreamChunk, TokenUsage
from dzmm.service.agents.director import run_director


@pytest.fixture
async def session_maker(tmp_path):
    db_url = f"sqlite+aiosqlite:///{tmp_path}/t.db"
    engine = get_engine(db_url)
    await init_db(engine)
    sm = async_session(engine)
    yield sm
    await engine.dispose()


class _StubDirector(ModelClient):
    name = "stub"
    def __init__(self, output: str):
        self._output = output
    async def stream(self, msgs, params):
        yield StreamChunk(delta="", finish_reason="stop")
    async def complete(self, msgs, params):
        return self._output, TokenUsage(input_tokens=10, output_tokens=20)


_DIRECTIVE = """<plot_directive>
- 本回合主推：推进主线事件 #2 — PC 见到老者
- NPC 重点：丽莎 — 主动靠近 PC 警告
- 节奏：悬疑
- 禁止：不再开新场所
</plot_directive>"""


@pytest.mark.asyncio
async def test_run_director_creates_stream_and_persists_turn(session_maker):
    async with session_maker() as s:
        directive, tok_in, tok_out = await run_director(
            s, session_id=1, client=_StubDirector(_DIRECTIVE),
            current_turn=1, snapshot="第 1 回合 snapshot...",
        )
        await s.commit()
    assert "推进主线事件 #2" in directive
    assert tok_in == 10 and tok_out == 20

    async with session_maker() as s:
        streams = (await s.execute(
            select(AgentStream).where(AgentStream.session_id == 1)
        )).scalars().all()
        assert len(streams) == 1
        assert streams[0].kind == "gm_director"
        assert streams[0].last_run_turn == 1
        msgs = (await s.execute(
            select(AgentMessage).where(AgentMessage.stream_id == streams[0].id)
            .order_by(AgentMessage.id)
        )).scalars().all()
        assert [m.role for m in msgs] == ["user", "assistant"]
        assert "snapshot" in msgs[0].content
        assert "推进主线事件 #2" in msgs[1].content


@pytest.mark.asyncio
async def test_run_director_falls_back_on_empty_output(session_maker):
    async with session_maker() as s:
        directive, tok_in, tok_out = await run_director(
            s, session_id=2, client=_StubDirector(""),
            current_turn=1, snapshot="x",
        )
        await s.commit()
    assert directive  # non-empty fallback
    assert tok_in == 0 and tok_out == 0  # fallback returns zero counts
    async with session_maker() as s:
        msgs = (await s.execute(select(AgentMessage))).scalars().all()
        assert msgs == []
