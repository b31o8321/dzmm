import pytest
from sqlalchemy import select

from dzmm.db.base import async_session, get_engine, init_db
from dzmm.db.models import AgentMessage
from dzmm.main import create_app
from dzmm.models.client import Message
from dzmm.service.agents.streams import (
    append_message,
    get_or_create_stream,
    load_history,
    rollback_to_turn,
)


@pytest.fixture
async def app(tmp_path):
    db_url = f"sqlite+aiosqlite:///{tmp_path}/t_agent_streams_service.db"
    engine = get_engine(db_url)
    await init_db(engine)
    SessionMaker = async_session(engine)
    app = create_app(SessionMaker)
    app.state.session_maker = SessionMaker
    yield app
    await engine.dispose()


@pytest.mark.asyncio
async def test_get_or_create_stream_idempotent(app):
    SessionMaker = app.state.session_maker
    async with SessionMaker() as s:
        a = await get_or_create_stream(s, 1, "gm_director", "")
        await s.commit()
    async with SessionMaker() as s:
        b = await get_or_create_stream(s, 1, "gm_director", "")
        await s.commit()
        assert a.id == b.id


@pytest.mark.asyncio
async def test_append_and_load_history_returns_message_objects(app):
    SessionMaker = app.state.session_maker
    async with SessionMaker() as s:
        st = await get_or_create_stream(s, 1, "npc", "王五")
        await s.flush()
        await append_message(s, st.id, turn=1, role="user", content="进酒馆")
        await append_message(s, st.id, turn=1, role="assistant", content="瞥了你一眼")
        await append_message(s, st.id, turn=2, role="user", content="坐下")
        await s.commit()
        msgs = await load_history(s, st.id, max_messages=10)
    assert len(msgs) == 3
    assert all(isinstance(m, Message) for m in msgs)
    assert msgs[0].role == "user" and "酒馆" in msgs[0].content
    assert msgs[-1].content == "坐下"


@pytest.mark.asyncio
async def test_load_history_caps_at_max_messages(app):
    SessionMaker = app.state.session_maker
    async with SessionMaker() as s:
        st = await get_or_create_stream(s, 1, "npc", "李四")
        await s.flush()
        for i in range(15):
            await append_message(s, st.id, turn=i, role="user", content=f"u{i}")
        await s.commit()
        msgs = await load_history(s, st.id, max_messages=5)
    assert len(msgs) == 5
    assert msgs[-1].content == "u14"
    assert msgs[0].content == "u10"


@pytest.mark.asyncio
async def test_load_history_keeps_summary_at_head(app):
    """is_summary 行永远排在最前面（无视 turn 顺序），后面跟最近的非 summary 消息。"""
    SessionMaker = app.state.session_maker
    async with SessionMaker() as s:
        st = await get_or_create_stream(s, 1, "npc", "丽莎")
        await s.flush()
        await append_message(
            s, st.id, turn=0, role="system", content="过去的故事摘要", is_summary=True,
        )
        await append_message(s, st.id, turn=5, role="user", content="新对白")
        await append_message(s, st.id, turn=6, role="assistant", content="新回应")
        await s.commit()
        msgs = await load_history(s, st.id, max_messages=10)
    assert msgs[0].role == "system"
    assert "摘要" in msgs[0].content
    assert msgs[1].content == "新对白"
    assert msgs[2].content == "新回应"


@pytest.mark.asyncio
async def test_load_history_does_not_split_pair_after_summary(app):
    SessionMaker = app.state.session_maker
    async with SessionMaker() as s:
        st = await get_or_create_stream(s, 1, "gm_director", "")
        await s.flush()
        await append_message(
            s, st.id, turn=0, role="system", content="长期摘要", is_summary=True,
        )
        for turn in range(1, 6):
            await append_message(s, st.id, turn, "user", f"u{turn}")
            await append_message(s, st.id, turn, "assistant", f"a{turn}")
        await s.commit()
        msgs = await load_history(s, st.id, max_messages=8)

    assert [m.role for m in msgs] == [
        "system", "user", "assistant", "user", "assistant", "user", "assistant",
    ]
    assert msgs[1].content == "u3"
    assert msgs[-1].content == "a5"


@pytest.mark.asyncio
async def test_rollback_to_turn_drops_later_messages(app):
    """delete_last_turn 回滚：把 turn > N 的所有 agent_messages 删掉。"""
    SessionMaker = app.state.session_maker
    async with SessionMaker() as s:
        st1 = await get_or_create_stream(s, 1, "gm_director", "")
        st2 = await get_or_create_stream(s, 1, "npc", "丽莎")
        await s.flush()
        for st in (st1, st2):
            for t in (1, 2, 3, 4):
                await append_message(s, st.id, turn=t, role="user", content=f"t{t}")
        await s.commit()
        await rollback_to_turn(s, session_id=1, max_keep_turn=2)
        await s.commit()
        rows = (await s.execute(select(AgentMessage))).scalars().all()
    assert len(rows) == 4  # 2 streams × 2 turns
    assert all(r.turn <= 2 for r in rows)


@pytest.mark.asyncio
async def test_compress_if_needed_folds_old_into_summary(app):
    """超过 threshold 后，旧消息被压成 1 条 is_summary 行；最新 keep_recent 条保留。"""
    from dzmm.models.client import ModelClient, StreamChunk, TokenUsage
    from dzmm.service.agents.streams import compress_if_needed

    class _StubSummarizer(ModelClient):
        name = "stub"
        async def stream(self, msgs, params):
            yield StreamChunk(delta="", finish_reason="stop")
        async def complete(self, msgs, params):
            return "压缩后的剧情摘要：丽莎从警惕到信任。", TokenUsage()

    SessionMaker = app.state.session_maker
    async with SessionMaker() as s:
        st = await get_or_create_stream(s, 1, "npc", "丽莎")
        await s.flush()
        for i in range(12):
            await append_message(s, st.id, turn=i, role="user", content=f"u{i}")
            await append_message(s, st.id, turn=i, role="assistant", content=f"a{i}")
        await s.commit()
        await compress_if_needed(
            s, st.id, _StubSummarizer(),
            threshold=20, keep_recent=4,
        )
        await s.commit()
        rows = (await s.execute(
            select(AgentMessage)
            .where(AgentMessage.stream_id == st.id)
            .order_by(AgentMessage.id.asc())
        )).scalars().all()

    summaries = [r for r in rows if r.is_summary]
    recents = [r for r in rows if not r.is_summary]
    assert len(summaries) == 1
    assert "摘要" in summaries[0].content
    assert len(recents) == 4
    assert recents[-1].content == "a11"


@pytest.mark.asyncio
async def test_compress_no_op_when_under_threshold(app):
    from dzmm.models.client import ModelClient, StreamChunk
    from dzmm.service.agents.streams import compress_if_needed

    class _NeverCalled(ModelClient):
        name = "never"
        async def stream(self, msgs, params):
            yield StreamChunk(delta="", finish_reason="stop")
        async def complete(self, msgs, params):
            raise AssertionError("should not be called")

    SessionMaker = app.state.session_maker
    async with SessionMaker() as s:
        st = await get_or_create_stream(s, 1, "npc", "李四")
        await s.flush()
        for i in range(5):
            await append_message(s, st.id, turn=i, role="user", content=f"u{i}")
        await s.commit()
        await compress_if_needed(s, st.id, _NeverCalled(), threshold=20, keep_recent=4)
        await s.commit()


@pytest.mark.asyncio
async def test_recompression_replaces_prior_summary(app):
    from dzmm.models.client import ModelClient, StreamChunk, TokenUsage
    from dzmm.service.agents.streams import compress_if_needed

    prompts: list[str] = []

    class _StubSummarizer(ModelClient):
        name = "stub"

        async def stream(self, msgs, params):
            yield StreamChunk(delta="", finish_reason="stop")

        async def complete(self, msgs, params):
            prompts.append(msgs[-1].content)
            return f"第 {len(prompts)} 次摘要", TokenUsage()

    SessionMaker = app.state.session_maker
    async with SessionMaker() as s:
        st = await get_or_create_stream(s, 1, "npc", "丽莎")
        await s.flush()
        for i in range(6):
            await append_message(s, st.id, turn=i, role="user", content=f"u{i}")
        await compress_if_needed(s, st.id, _StubSummarizer(), threshold=4, keep_recent=2)
        await s.commit()
        for i in range(6, 11):
            await append_message(s, st.id, turn=i, role="user", content=f"u{i}")
        await compress_if_needed(s, st.id, _StubSummarizer(), threshold=4, keep_recent=2)
        await s.commit()
        summaries = (await s.execute(
            select(AgentMessage).where(
                AgentMessage.stream_id == st.id,
                AgentMessage.is_summary == True,  # noqa: E712
            )
        )).scalars().all()

    assert len(summaries) == 1
    assert summaries[0].content == "第 2 次摘要"
    assert "第 1 次摘要" in prompts[1]
