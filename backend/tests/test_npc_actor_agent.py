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


def test_build_npc_actor_messages_includes_new_context_blocks():
    """v0.10.2 — scene_context / recent_dialogue 出现在 user msg 里
    (peer_lines was removed in v0.10.2 — see orchestrator parallel fan-out)."""
    from dzmm.prompts.npc_actor_template import build_npc_actor_messages
    from types import SimpleNamespace
    npc = SimpleNamespace(
        name="丽莎", gender="female", archetype="x",
        description="x", state="x", purpose="x",
        emotion_json="{}",
    )
    msgs = build_npc_actor_messages(
        npc=npc, history=[], plot_directive="d",
        scene_narrative="snar", user_action="ua",
        scene_context="地点：实验室\n同台 NPC：阿伟",
        recent_dialogue="[玩家] 上回合做了 X\n[GM] 然后 Y",
    )
    user_msg = msgs[-1].content
    assert "实验室" in user_msg
    assert "阿伟" in user_msg
    assert "上回合" in user_msg


def test_build_npc_actor_messages_includes_relationship_summary():
    """v0.10.6: relationship_summary 应该出现在 system message 里。"""
    from types import SimpleNamespace
    from dzmm.prompts.npc_actor_template import build_npc_actor_messages
    npc = SimpleNamespace(
        name="丽莎", gender="female", archetype="冷酷商人",
        description="x", state="x", purpose="x",
        emotion_json="{}",
    )
    msgs = build_npc_actor_messages(
        npc=npc, history=[], plot_directive="d",
        scene_narrative="snar", user_action="ua",
        relationship_summary="- favor = -25（冷淡 / 警惕）\n- 近期与 PC 的交互: PC 撒谎被识破",
    )
    sys_content = msgs[0].content
    assert "favor = -25" in sys_content
    assert "PC 撒谎被识破" in sys_content
    # 铁律说明应在
    assert "首先" in sys_content and "archetype" in sys_content


@pytest.mark.asyncio
async def test_run_npc_actor_parses_favor_delta_from_body(session_maker):
    """v0.10.6: NPC actor 现在可以 emit favor_delta；apply_npc_update 在
    state_apply 里实际应用，但 npc_actor 这一步只负责把 npc_update tag
    成功 yield 出来 + speaker/name 强制对齐。这里只测 yield + 强制对齐。"""
    output = (
        '<say speaker="丽莎">「谢谢你」</say>'
        '<npc_update name="丽莎">{"favor_delta": +12, "emotion": {"love": +5}}</npc_update>'
    )
    async with session_maker() as s:
        events = await run_npc_actor(
            s, npc=_npc(), session_id=1,
            plot_directive="d", scene_narrative="x",
            user_action="x", client=_StubNpc(output),
            current_turn=1,
            relationship_summary="- favor = +5（中立 / 一般认识）",
        )
        await s.commit()
    say = [e for e in events if isinstance(e, TagComplete) and e.name == "say"]
    upd = [e for e in events if isinstance(e, TagComplete) and e.name == "npc_update"]
    assert len(say) == 1
    assert len(upd) == 1
    assert "favor_delta" in upd[0].content


@pytest.mark.asyncio
async def test_format_npc_relationship_labels_favor_correctly(session_maker):
    """v0.10.6: _format_npc_relationship 给 favor 打标签 + 列 affinity。"""
    from types import SimpleNamespace
    from dzmm.service.agents.orchestrator import _format_npc_relationship

    npc_friendly = SimpleNamespace(name="A", favor=35, affinity_json='{"信任": 4}')
    npc_neutral = SimpleNamespace(name="B", favor=0, affinity_json="{}")
    npc_hostile = SimpleNamespace(name="C", favor=-40, affinity_json="{}")

    async with session_maker() as s:
        f = await _format_npc_relationship(s, 1, npc_friendly, [])
        n = await _format_npc_relationship(s, 1, npc_neutral, [])
        h = await _format_npc_relationship(s, 1, npc_hostile, [])
    assert "+35" in f and ("友好" in f or "信任" in f)
    assert "+0" in n or "0（中立" in n
    assert "-40" in h and "敌对" in h
    assert "信任:+4" in f
