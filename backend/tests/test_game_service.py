import json
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import select

from dzmm.db.base import init_db, get_engine, async_session
from dzmm.db.models import (
    Character, CharState, Message as MessageRow, ModelConfig,
    Session as GameSession, World,
)
from dzmm.models.client import GenerationParams, Message, ModelClient, StreamChunk, TokenUsage
from dzmm.parsing.events import NarrativeDelta, TagComplete
from dzmm.service.game import run_turn


class FakeClient(ModelClient):
    name = "fake"

    def __init__(self, output: str, usage: TokenUsage | None = None):
        self.output = output
        self.usage = usage or TokenUsage(input_tokens=10, output_tokens=20)
        self.last_messages: list[Message] | None = None

    async def stream(
        self, messages: list[Message], params: GenerationParams
    ) -> AsyncIterator[StreamChunk]:
        self.last_messages = messages
        for ch in self.output:
            yield StreamChunk(delta=ch)
        yield StreamChunk(delta="", finish_reason="stop", usage=self.usage)


@pytest.fixture
async def seeded(tmp_path):
    engine = get_engine(f"sqlite+aiosqlite:///{tmp_path}/t.db")
    await init_db(engine)
    SessionMaker = async_session(engine)
    async with SessionMaker() as s:
        world = World(name="W", content_md="赛博朋克", style="dark",
                      rules_json='{"mode":"light"}')
        char = Character(world=world, name="Riku", profile_md="义体黑客",
                         base_stats_json='{"hp":20,"sanity":15}')
        cfg = ModelConfig(name="m", type="ollama",
                          base_url="http://localhost:11434", model_name="qwen")
        s.add_all([world, char, cfg])
        await s.flush()
        sess = GameSession(name="run", world_id=world.id, character_id=char.id,
                           gm_model_config_id=cfg.id, summarizer_model_config_id=cfg.id)
        s.add(sess)
        await s.flush()
        s.add(CharState(session_id=sess.id,
                        stats_json='{"hp":20,"sanity":15}',
                        inventory_json="[]"))
        await s.commit()
        yield engine, SessionMaker, sess.id
    await engine.dispose()


async def test_run_turn_streams_narrative_and_persists(seeded):
    engine, SessionMaker, sid = seeded
    output = (
        "<narrative>你站在霓虹反射的雨中。</narrative>"
        '<state_change>{"sanity": -1}</state_change>'
    )
    client = FakeClient(output)

    events = []
    async with SessionMaker() as s:
        async for ev in run_turn(s, sid, "环顾四周", client):
            events.append(ev)
        await s.commit()

    deltas = [e for e in events if isinstance(e, NarrativeDelta)]
    assert "".join(d.text for d in deltas) == "你站在霓虹反射的雨中。"
    tags = [e for e in events if isinstance(e, TagComplete)]
    assert any(t.name == "state_change" for t in tags)

    async with SessionMaker() as s:
        cs = (await s.execute(
            select(CharState).where(CharState.session_id == sid)
        )).scalar_one()
        stats = json.loads(cs.stats_json)
        assert stats["sanity"] == 14

        msgs = (await s.execute(
            select(MessageRow).where(MessageRow.session_id == sid)
            .order_by(MessageRow.id)
        )).scalars().all()
        assert len(msgs) == 2
        assert msgs[0].role == "user"
        assert msgs[0].content == "环顾四周"
        assert msgs[1].role == "assistant"
        assert msgs[1].content == output
        assert msgs[1].tokens_in == 10
        assert msgs[1].tokens_out == 20

        sess = await s.get(GameSession, sid)
        assert sess.turn_count == 1


async def test_run_turn_includes_recent_history_in_prompt(seeded):
    engine, SessionMaker, sid = seeded
    client1 = FakeClient("<narrative>第一回合</narrative>")
    async with SessionMaker() as s:
        async for _ in run_turn(s, sid, "动作1", client1):
            pass
        await s.commit()

    client2 = FakeClient("<narrative>第二回合</narrative>")
    async with SessionMaker() as s:
        async for _ in run_turn(s, sid, "动作2", client2):
            pass
        await s.commit()

    contents = [m.content for m in client2.last_messages]
    assert "动作1" in contents
    assert "<narrative>第一回合</narrative>" in contents
    assert contents[-1] == "动作2"
