import json
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import select

from dzmm.db.base import init_db, get_engine, async_session
from dzmm.db.models import (
    Character, CharState, HiddenEvent, Message as MessageRow, ModelConfig, NPC,
    NpcRelation, Session as GameSession, World,
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


async def test_run_turn_falls_back_when_no_narrative_tag(seeded):
    """Reasoning models (deepseek-r1) emit <think>...</think> then plain text
    without <narrative>. We should treat the captured raw text as narrative."""
    engine, SessionMaker, sid = seeded
    output = (
        "<think>I should describe a scene</think>"
        "你站在霓虹反射的雨中，远处传来警报声。"
    )
    client = FakeClient(output)

    events = []
    async with SessionMaker() as s:
        async for ev in run_turn(s, sid, "环顾四周", client):
            events.append(ev)
        await s.commit()

    deltas = [e for e in events if isinstance(e, NarrativeDelta)]
    text = "".join(d.text for d in deltas)
    assert "霓虹" in text, f"fallback narrative not delivered, got: {text!r}"
    assert "<think>" not in text  # stripped


async def test_character_level_injected_in_prompt(seeded):
    engine, SessionMaker, sid = seeded
    captured = FakeClient("<narrative>hi</narrative>")
    async with SessionMaker() as s:
        async for _ in run_turn(s, sid, "x", captured):
            pass
        await s.commit()

    sys_msg = captured.last_messages[0].content
    # Default level is 1; verify the GM sees it.
    assert "Lv 1" in sys_msg
    assert "等级" in sys_msg


async def test_plot_threads_appear_in_next_prompt(seeded):
    engine, SessionMaker, sid = seeded

    async with SessionMaker() as s:
        async for _ in run_turn(
            s, sid, "调查",
            FakeClient(
                "<narrative>你发现了一张神秘地图。</narrative>"
                '<plot_event type="hook_introduced" importance="3">'
                '神秘地图指向 X 区一个废弃工厂'
                '</plot_event>'
            ),
        ):
            pass
        await s.commit()

    captured = FakeClient("<narrative>第二回合</narrative>")
    async with SessionMaker() as s:
        async for _ in run_turn(s, sid, "继续", captured):
            pass
        await s.commit()

    sys_msg = captured.last_messages[0].content
    assert "神秘地图" in sys_msg
    assert "进行中的剧情线" in sys_msg or "hook_introduced" in sys_msg


async def test_pinned_npc_always_in_prompt(seeded):
    """A pinned NPC must appear (full dossier) in key_facts even after a long
    drought — last_seen_turn-based eviction must NOT drop pinned NPCs."""
    engine, SessionMaker, sid = seeded

    async with SessionMaker() as s:
        s.add(NPC(
            session_id=sid,
            name="御坂雪",
            description="21 岁早大学生",
            favor=8,
            state="对你敞开了一些心扉",
            last_seen_turn=1,
            notes_json='[{"turn":1,"text":"在浅草庙会上分享了童年阴影"}]',
            purpose="查清祖母遗物里咒符的来源",
            archetype="外柔内刚的文学少女",
            affinity_json='{"信任":3,"羁绊":2}',
            pinned=True,
        ))
        sess = await s.get(GameSession, sid)
        sess.turn_count = 30
        await s.commit()

    # Bury her with 12 newer NPCs that are NOT pinned.
    async with SessionMaker() as s:
        for i in range(12):
            s.add(NPC(
                session_id=sid,
                name=f"路人{i}",
                description="背景 NPC",
                last_seen_turn=30 + i,
            ))
        await s.commit()

    captured = FakeClient("<narrative>下一回合</narrative>")
    async with SessionMaker() as s:
        async for _ in run_turn(s, sid, "继续", captured):
            pass
        await s.commit()

    sys_msg = captured.last_messages[0].content
    assert "御坂雪" in sys_msg
    assert "外柔内刚的文学少女" in sys_msg
    assert "查清祖母遗物里咒符的来源" in sys_msg
    # Multi-axis affinity should render
    assert "信任+3" in sys_msg
    assert "羁绊+2" in sys_msg


async def test_era_appears_in_next_prompt(seeded):
    """An era declared in turn N must surface in the system prompt of turn N+1."""
    engine, SessionMaker, sid = seeded

    # turn 1: GM declares an era
    async with SessionMaker() as s:
        async for _ in run_turn(
            s, sid, "推进",
            FakeClient(
                "<narrative>新章开始</narrative>"
                '<era_begin name="第二章">新阶段</era_begin>'
            ),
        ):
            pass
        await s.commit()

    # turn 2: capture system prompt
    captured = FakeClient("<narrative>第二回合</narrative>")
    async with SessionMaker() as s:
        async for _ in run_turn(s, sid, "继续", captured):
            pass
        await s.commit()

    sys_msg = captured.last_messages[0].content
    assert "第二章" in sys_msg
    assert "当前章节" in sys_msg


async def test_pc_mood_appears_in_next_prompt(seeded):
    """PC mood declared in turn N must appear in the system prompt of turn N+1."""
    engine, SessionMaker, sid = seeded

    async with SessionMaker() as s:
        async for _ in run_turn(
            s, sid, "受惊",
            FakeClient(
                "<narrative>你脸色发白。</narrative>"
                '<pc_mood>{"tense": 60, "exhausted": 20}</pc_mood>'
            ),
        ):
            pass
        await s.commit()

    captured = FakeClient("<narrative>第二回合</narrative>")
    async with SessionMaker() as s:
        async for _ in run_turn(s, sid, "继续", captured):
            pass
        await s.commit()

    sys_msg = captured.last_messages[0].content
    assert "PC 当前心情" in sys_msg
    assert "tense" in sys_msg
    assert "60" in sys_msg


async def test_npc_relation_appears_in_next_prompt(seeded):
    """A registered NPC relation must surface in the next turn's prompt."""
    engine, SessionMaker, sid = seeded

    async with SessionMaker() as s:
        s.add(NpcRelation(
            session_id=sid,
            npc_a="御坂雪",
            npc_b="卫兵长",
            kind="父女",
            description="失散多年",
            introduced_turn=3,
        ))
        await s.commit()

    captured = FakeClient("<narrative>x</narrative>")
    async with SessionMaker() as s:
        async for _ in run_turn(s, sid, "继续", captured):
            pass
        await s.commit()

    sys_msg = captured.last_messages[0].content
    assert "NPC 关系" in sys_msg
    assert "御坂雪" in sys_msg
    assert "卫兵长" in sys_msg
    assert "父女" in sys_msg


async def test_key_facts_includes_pc_name_lock(seeded):
    """The PC's name must be pinned at the very top of key_facts so the GM
    doesn't drift into using a different name across turns."""
    engine, SessionMaker, sid = seeded
    captured = FakeClient("<narrative>x</narrative>")
    async with SessionMaker() as s:
        async for _ in run_turn(s, sid, "继续", captured):
            pass
        await s.commit()

    sys_msg = captured.last_messages[0].content
    # Riku is the seeded PC name.
    assert "Riku" in sys_msg
    assert "PC 身份" in sys_msg
    # An anti-drift instruction must be present.
    assert "永不可改" in sys_msg or "不得改名" in sys_msg


async def test_key_facts_includes_active_hidden_events(seeded):
    """Active hidden_events are re-injected into key_facts every turn under
    the GM-only "暗中状态" header."""
    engine, SessionMaker, sid = seeded
    async with SessionMaker() as s:
        s.add(HiddenEvent(
            session_id=sid,
            subject="小菱",
            kind="injury",
            severity=2,
            description="云梦泽蒙面人砍伤渗血",
            consequence="再过 5 回合不治会昏迷",
            introduced_turn=2,
            status="active",
        ))
        sess = await s.get(GameSession, sid)
        sess.turn_count = 4
        await s.commit()

    captured = FakeClient("<narrative>x</narrative>")
    async with SessionMaker() as s:
        async for _ in run_turn(s, sid, "继续", captured):
            pass
        await s.commit()

    sys_msg = captured.last_messages[0].content
    assert "暗中状态" in sys_msg
    assert "小菱" in sys_msg
    assert "injury" in sys_msg
    assert "渗血" in sys_msg
    assert "昏迷" in sys_msg
    # turn_age — current_turn is 4, introduced at 2 → t+2
    assert "t+2" in sys_msg


async def test_key_facts_skips_resolved_hidden_events(seeded):
    """Resolved hidden_events must NOT appear in the prompt — they're done."""
    engine, SessionMaker, sid = seeded
    async with SessionMaker() as s:
        s.add(HiddenEvent(
            session_id=sid,
            subject="小菱",
            kind="injury",
            severity=2,
            description="渗血",
            consequence="不治会昏迷",
            introduced_turn=2,
            status="resolved",
            resolved_turn=4,
            resolution="包扎止血",
        ))
        await s.commit()

    captured = FakeClient("<narrative>x</narrative>")
    async with SessionMaker() as s:
        async for _ in run_turn(s, sid, "继续", captured):
            pass
        await s.commit()

    sys_msg = captured.last_messages[0].content
    # The key_facts injection lists each active event as a bullet:
    # "- [小菱·injury·t+N] ..."
    # That bullet must NOT appear when only resolved events exist. The static
    # prompt template has section headers and examples that mention generic
    # "渗血" / "暗中状态(GM only)" — those don't indicate an injected event.
    # The unique signature of an actually-injected hidden_event is the bullet
    # "[<subject>·<kind>·t+<N>]" pattern.
    assert "[小菱·injury·" not in sys_msg
    # The specific consequence text from this event also shouldn't leak.
    assert "包扎止血" not in sys_msg


async def test_message_events_json_persisted(seeded):
    """Every non-narrative tag emitted in a turn lands in Message.events_json
    so the frontend can render inline event chips."""
    engine, SessionMaker, sid = seeded
    output = (
        "<narrative>你受伤了。</narrative>"
        '<state_change>{"hp": -3}</state_change>'
        '<npc_update>{"name":"卫兵长","favor_delta":-2,"state":"敌对"}</npc_update>'
        '<dice skill="格挡" target="12">d20=8，失败</dice>'
    )
    client = FakeClient(output)
    async with SessionMaker() as s:
        async for _ in run_turn(s, sid, "格挡", client):
            pass
        await s.commit()

    async with SessionMaker() as s:
        msg = (await s.execute(
            select(MessageRow)
            .where(MessageRow.session_id == sid, MessageRow.role == "assistant")
            .order_by(MessageRow.id.desc())
        )).scalars().first()
        events = json.loads(msg.events_json)

    assert isinstance(events, list)
    assert len(events) == 3
    types = [e["type"] for e in events]
    assert "state_change" in types
    assert "npc_update" in types
    assert "dice" in types

    dice_ev = next(e for e in events if e["type"] == "dice")
    assert dice_ev["payload"].get("skill") == "格挡"
    assert dice_ev["payload"].get("target") == "12"
    assert "d20=8" in dice_ev["content"]


async def test_message_events_json_empty_when_only_narrative(seeded):
    """If the GM only emits <narrative>, events_json is an empty list."""
    engine, SessionMaker, sid = seeded
    client = FakeClient("<narrative>静谧的一夜。</narrative>")
    async with SessionMaker() as s:
        async for _ in run_turn(s, sid, "睡觉", client):
            pass
        await s.commit()

    async with SessionMaker() as s:
        msg = (await s.execute(
            select(MessageRow)
            .where(MessageRow.session_id == sid, MessageRow.role == "assistant")
            .order_by(MessageRow.id.desc())
        )).scalars().first()
        assert json.loads(msg.events_json) == []


async def test_recall_drains_after_one_use(seeded):
    """Recalled NPC injects full dossier this turn; recall_pending is cleared
    after one use."""
    engine, SessionMaker, sid = seeded

    async with SessionMaker() as s:
        s.add(NPC(
            session_id=sid,
            name="御坂雪",
            description="21 岁早大学生",
            favor=8,
            state="对你敞开了一些心扉",
            last_seen_turn=1,
            notes_json='[]',
            purpose="查清祖母遗物里咒符的来源",
            archetype="外柔内刚的文学少女",
            affinity_json='{"信任":3}',
            pinned=False,
        ))
        sess = await s.get(GameSession, sid)
        sess.turn_count = 50
        sess.recall_pending_json = '["御坂雪"]'
        await s.commit()

    # Bury her under newer NPCs so she wouldn't appear via last_seen alone.
    async with SessionMaker() as s:
        for i in range(12):
            s.add(NPC(
                session_id=sid,
                name=f"路人{i}",
                description="背景 NPC",
                last_seen_turn=40 + i,
            ))
        await s.commit()

    captured = FakeClient("<narrative>下一回合</narrative>")
    async with SessionMaker() as s:
        async for _ in run_turn(s, sid, "继续", captured):
            pass
        await s.commit()

    sys_msg = captured.last_messages[0].content
    assert "御坂雪" in sys_msg
    assert "外柔内刚的文学少女" in sys_msg

    # recall_pending must have been drained.
    async with SessionMaker() as s:
        sess = await s.get(GameSession, sid)
        assert json.loads(sess.recall_pending_json) == []
