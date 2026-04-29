from collections.abc import AsyncIterator

import pytest
from sqlalchemy import select

from dzmm.db.base import init_db, get_engine, async_session
from dzmm.db.models import (
    Character, CharState, Message as MessageRow, ModelConfig,
    Session as GameSession, StorySummary, World,
)
from dzmm.models.client import GenerationParams, Message, ModelClient, StreamChunk, TokenUsage
from dzmm.service.summarizer import maybe_summarize, SUMMARIZE_AFTER_TURNS


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
