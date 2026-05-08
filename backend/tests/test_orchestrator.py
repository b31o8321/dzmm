import pytest
from sqlalchemy import select

from dzmm.db.base import async_session, get_engine, init_db
from dzmm.db.models import AgentStream, NPC
from dzmm.models.client import ModelClient, StreamChunk, TokenUsage
from dzmm.parsing.events import NarrativeDelta, TagComplete
from dzmm.service.agents.orchestrator import run_turn_v10


@pytest.fixture
async def session_maker(tmp_path):
    db_url = f"sqlite+aiosqlite:///{tmp_path}/t.db"
    engine = get_engine(db_url)
    await init_db(engine)
    sm = async_session(engine)
    yield sm
    await engine.dispose()


class _MultiClient(ModelClient):
    """Returns different output based on prompt content. Director / Scene /
    NPC prompts have distinct headers we match on."""
    name = "multi"

    async def stream(self, msgs, params):
        # Scene path streams narrative
        text = "<narrative>巷子潮湿。</narrative>"
        yield StreamChunk(delta=text, finish_reason="stop")

    async def complete(self, msgs, params):
        joined = "\n".join(m.content for m in msgs)
        if "剧情导演" in joined:
            return ("<plot_directive>\n- 主推：见老者\n- NPC：丽莎主动\n"
                    "- 节奏：悬疑\n- 禁止：不开新场所\n</plot_directive>",
                    TokenUsage())
        if "扮演 TRPG 中的 NPC" in joined:
            return ('<say speaker="丽莎" mood="紧张">「快走！」</say>',
                    TokenUsage())
        return "", TokenUsage()


@pytest.mark.asyncio
async def test_run_turn_v10_yields_director_then_scene_then_npc(session_maker):
    from dzmm.db.models import Character, ModelConfig, Session as GameSession, World
    async with session_maker() as s:
        w = World(name="W", content_md="赛博朋克")
        c = Character(world_id=1, name="Riku", profile_md="hacker",
                      base_stats_json='{"hp":20}')
        m = ModelConfig(name="x", type="ollama", base_url="x", model_name="y")
        s.add_all([w, c, m])
        await s.flush()
        sess = GameSession(name="t", world_id=w.id, character_id=c.id,
                           gm_model_config_id=m.id, summarizer_model_config_id=m.id)
        s.add(sess)
        await s.flush()
        s.add(NPC(session_id=sess.id, name="丽莎", pinned=True,
                  archetype="热心邻家少女", description="21 岁",
                  purpose="找弟弟", state="焦虑",
                  gender="female", emotion_json='{"fear":60}'))
        await s.commit()
        sid = sess.id

    client = _MultiClient()
    events = []
    async with session_maker() as s:
        async for ev in run_turn_v10(
            s, session_id=sid, user_action="冲进巷子",
            scene_client=client, director_client=client,
            npc_client=client,
            world_md="赛博朋克", character_md="Riku - hacker",
            live_state_text='{"hp":20}', key_facts="第 1 回合",
            recent_messages=[],
        ):
            events.append(ev)
        await s.commit()

    narratives = [e for e in events if isinstance(e, NarrativeDelta)]
    tags = [e for e in events if isinstance(e, TagComplete)]
    assert any("巷子" in n.text for n in narratives)
    assert any(t.name == "say" and t.attrs.get("speaker") == "丽莎" for t in tags)

    async with session_maker() as s:
        streams = (await s.execute(
            select(AgentStream).where(AgentStream.session_id == sid)
        )).scalars().all()
        kinds = {(st.kind, st.ref) for st in streams}
        assert ("gm_director", "") in kinds
        assert ("npc", "丽莎") in kinds


@pytest.mark.asyncio
async def test_compress_streams_folds_old_messages(session_maker):
    """超过 threshold 后，旧消息被压成 1 条 summary + 最近 keep_recent 条原文保留。"""
    from sqlalchemy import select
    from dzmm.db.models import AgentMessage
    from dzmm.models.client import ModelClient, StreamChunk, TokenUsage
    from dzmm.service.agents.streams import (
        append_message, compress_if_needed, get_or_create_stream,
    )

    class _Sum(ModelClient):
        name = "s"
        async def stream(self, msgs, params):
            yield StreamChunk(delta="", finish_reason="stop")
        async def complete(self, msgs, params):
            return "摘要", TokenUsage()

    async with session_maker() as s:
        st = await get_or_create_stream(s, 1, "npc", "丽莎")
        await s.flush()
        for i in range(50):
            await append_message(s, st.id, turn=i, role="user", content=f"u{i}")
            await append_message(s, st.id, turn=i, role="assistant", content=f"a{i}")
        await s.commit()
        await compress_if_needed(s, st.id, _Sum(), threshold=25, keep_recent=8)
        await s.commit()
        rows = (await s.execute(
            select(AgentMessage).where(AgentMessage.stream_id == st.id)
        )).scalars().all()
    assert sum(1 for r in rows if r.is_summary) == 1
    assert sum(1 for r in rows if not r.is_summary) == 8
