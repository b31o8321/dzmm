from collections.abc import AsyncIterator

import pytest
from sqlalchemy import select

from dzmm.db.base import init_db, get_engine, async_session
from dzmm.db.models import (
    Character, CharState, Message as MessageRow, ModelConfig,
    Session as GameSession, StorySummary, World,
)
from dzmm.models.client import GenerationParams, Message, ModelClient, StreamChunk, TokenUsage
from dzmm.service.summarizer import (
    maybe_summarize,
    SUMMARIZE_AFTER_TURNS,
    SUMMARIZE_KEEP_RECENT,
    SUMMARIZE_TRIGGER_TURNS,
)


class FakeSummarizer(ModelClient):
    name = "fakesum"

    def __init__(self, output: str):
        self.output = output
        self.called_with: list[Message] | None = None

    async def stream(
        self, messages: list[Message], params: GenerationParams
    ) -> AsyncIterator[StreamChunk]:
        self.called_with = messages
        yield StreamChunk(delta=self.output, finish_reason="stop",
                          usage=TokenUsage(input_tokens=100, output_tokens=50))


@pytest.fixture
async def seeded_with_messages(tmp_path):
    engine = get_engine(f"sqlite+aiosqlite:///{tmp_path}/t.db")
    await init_db(engine)
    SessionMaker = async_session(engine)
    async with SessionMaker() as s:
        world = World(name="W", content_md="x", style="dark",
                      rules_json='{"mode":"light"}')
        char = Character(world=world, name="C", profile_md="y",
                         base_stats_json='{}')
        cfg = ModelConfig(name="m", type="ollama",
                          base_url="http://localhost:11434", model_name="qwen")
        s.add_all([world, char, cfg])
        await s.flush()
        sess = GameSession(name="run", world_id=world.id, character_id=char.id,
                           gm_model_config_id=cfg.id, summarizer_model_config_id=cfg.id)
        s.add(sess)
        await s.flush()
        s.add(CharState(session_id=sess.id))
        for t in range(1, SUMMARIZE_AFTER_TURNS + 1):
            s.add(MessageRow(session_id=sess.id, role="user", content=f"行动 {t}", turn=t))
            s.add(MessageRow(session_id=sess.id, role="assistant",
                             content=f"<narrative>结果 {t}</narrative>", turn=t))
        sess.turn_count = SUMMARIZE_AFTER_TURNS
        await s.commit()
        yield engine, SessionMaker, sess.id
    await engine.dispose()


async def test_summarize_creates_story_summary(seeded_with_messages):
    engine, SessionMaker, sid = seeded_with_messages
    summary_text = "PC 经历了 10 个回合的探索，遇见了若干 NPC。"
    client = FakeSummarizer(summary_text)

    async with SessionMaker() as s:
        result = await maybe_summarize(s, sid, client)
        await s.commit()

    assert result is True

    async with SessionMaker() as s:
        ss = (await s.execute(
            select(StorySummary).where(StorySummary.session_id == sid)
        )).scalar_one()
        assert ss.summary_text == summary_text
        last_msg = (await s.execute(
            select(MessageRow).where(MessageRow.session_id == sid)
            .order_by(MessageRow.id.desc()).limit(1)
        )).scalar_one()
        assert ss.last_summarized_msg_id == last_msg.id


async def test_summarize_skips_when_below_threshold(tmp_path):
    engine = get_engine(f"sqlite+aiosqlite:///{tmp_path}/t.db")
    await init_db(engine)
    SessionMaker = async_session(engine)
    async with SessionMaker() as s:
        world = World(name="W", content_md="x", style="dark")
        char = Character(world=world, name="C", profile_md="y", base_stats_json="{}")
        cfg = ModelConfig(name="m", type="ollama",
                          base_url="http://localhost:11434", model_name="q")
        s.add_all([world, char, cfg])
        await s.flush()
        sess = GameSession(name="r", world_id=world.id, character_id=char.id,
                           gm_model_config_id=cfg.id, summarizer_model_config_id=cfg.id,
                           turn_count=2)
        s.add(sess)
        await s.commit()
        sid = sess.id

    client = FakeSummarizer("should not be called")
    async with SessionMaker() as s:
        result = await maybe_summarize(s, sid, client)
        await s.commit()

    assert result is False
    assert client.called_with is None
    await engine.dispose()


async def test_summary_compression_triggers_above_threshold(seeded_with_messages):
    """When the generated summary is too long, a second compression pass runs;
    importance>=2 events get persisted to the Timeline table."""
    engine, SessionMaker, sid = seeded_with_messages
    from dzmm.db.models import Timeline as TLModel
    from dzmm.service.summarizer import COMPRESSION_TRIGGER_CHARS

    long_text = "卷起的剧情" * 1000  # ~5000 chars > 4000 trigger
    short_text = (
        "PC 经历了赛博朋克城市的多个事件，遇到了义体黑客阿山，"
        "在九龙黑街揭穿了一桩义体走私案。\n\n"
        '<event importance="3">PC 与黑客阿山达成同盟</event>\n'
        '<event importance="2">PC 救出了被绑架的少女小雨</event>\n'
        '<event importance="1">在便利店买了个泡面</event>\n'
    )

    class TwoStageClient(ModelClient):
        name = "two-stage"

        def __init__(self):
            self.calls = 0

        async def stream(self, messages, params):
            self.calls += 1
            # First call → bloated summary; second call (compression) → shorter
            output = long_text if self.calls == 1 else short_text
            yield StreamChunk(delta=output, finish_reason="stop",
                              usage=TokenUsage(input_tokens=10, output_tokens=len(output)))

    client = TwoStageClient()
    async with SessionMaker() as s:
        result = await maybe_summarize(s, sid, client)
        await s.commit()

    assert result is True
    assert client.calls == 2  # one bloated + one compression

    async with SessionMaker() as s:
        ss = (await s.execute(
            select(StorySummary).where(StorySummary.session_id == sid)
        )).scalar_one()
        # Compressed summary is much shorter
        assert len(ss.summary_text) < COMPRESSION_TRIGGER_CHARS

        # Two importance>=2 events persisted
        tl = (await s.execute(
            select(TLModel).where(TLModel.session_id == sid)
        )).scalars().all()
        assert len(tl) == 2
        importances = sorted(t.importance for t in tl)
        assert importances == [2, 3]
        texts = [t.event_text for t in tl]
        assert any("阿山" in t for t in texts)
        assert any("小雨" in t for t in texts)


# ----------------------------------------------------------------------------
# v0.2.1 — long-context fix: summarizer should trigger every 10 turns of new
# material, not wait for 20+ messages to accumulate.
# ----------------------------------------------------------------------------


def test_summarize_trigger_constants_present():
    """The v0.2.1 knobs must be exposed for callers (and for messages.py to
    keep its retention window in concert)."""
    assert SUMMARIZE_TRIGGER_TURNS == 10
    assert SUMMARIZE_KEEP_RECENT == 6
    # Old name kept as alias so external code keeps importing.
    assert SUMMARIZE_AFTER_TURNS == 10


async def test_summarize_triggers_at_10_turns(seeded_with_messages):
    """Seeded fixture creates exactly 10 turns (20 messages) — that's the new
    minimum threshold. maybe_summarize should fire."""
    engine, SessionMaker, sid = seeded_with_messages
    client = FakeSummarizer("摘要：玩家完成了 10 回合冒险。")
    async with SessionMaker() as s:
        result = await maybe_summarize(s, sid, client)
        await s.commit()
    assert result is True
    assert client.called_with is not None  # LLM actually invoked


async def test_summarize_skips_at_9_turns(tmp_path):
    """One turn below threshold → must NOT fire (avoid wasteful summarizer
    calls when the story has barely started)."""
    engine = get_engine(f"sqlite+aiosqlite:///{tmp_path}/t9.db")
    await init_db(engine)
    SessionMaker = async_session(engine)
    async with SessionMaker() as s:
        world = World(name="W", content_md="x", style="dark")
        char = Character(world=world, name="C", profile_md="y", base_stats_json="{}")
        cfg = ModelConfig(name="m", type="ollama",
                          base_url="http://localhost:11434", model_name="q")
        s.add_all([world, char, cfg])
        await s.flush()
        sess = GameSession(name="r", world_id=world.id, character_id=char.id,
                           gm_model_config_id=cfg.id, summarizer_model_config_id=cfg.id,
                           turn_count=9)
        s.add(sess)
        await s.flush()
        for t in range(1, 10):
            s.add(MessageRow(session_id=sess.id, role="user", content=f"a{t}", turn=t))
            s.add(MessageRow(session_id=sess.id, role="assistant", content=f"r{t}", turn=t))
        await s.commit()
        sid = sess.id

    client = FakeSummarizer("should not be called")
    async with SessionMaker() as s:
        result = await maybe_summarize(s, sid, client)
        await s.commit()

    assert result is False
    assert client.called_with is None
    await engine.dispose()
