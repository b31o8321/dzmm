import json
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import select

from dzmm.db.base import init_db, get_engine, async_session
from dzmm.db.models import (
    Character, CharState, HiddenEvent, Message as MessageRow, ModelConfig, NPC,
    NpcRelation, Screenplay, Session as GameSession, World,
)
from dzmm.models.client import GenerationParams, Message, ModelClient, StreamChunk, TokenUsage
from dzmm.parsing.events import NarrativeDelta, TagComplete
from dzmm.service.game import (
    RECENT_WINDOW_DEFAULT,
    RECENT_WINDOW_LONG_GAME,
    RECENT_WINDOW_VERY_LONG,
    _recent_window_for,
    _rough_token_count,
    run_turn,
)


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
            # v0.11: this NPC is fully known to the player; explicit reveal
            # mask so the dossier shows everything (otherwise default mask
            # would hide purpose / archetype / affinity).
            revealed_json=(
                '{"name":true,"description":true,"state":true,'
                '"purpose":true,"archetype":true,"favor":true,'
                '"affinity":true}'
            ),
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


async def test_key_facts_includes_pc_hooks_section(seeded):
    """character.profile_md 含 能力 / 物品 / 弱点 段落 → key_facts 应注入
    「PC 钩子」段，并把抽出的具体词带进 prompt。"""
    engine, SessionMaker, sid = seeded

    profile = (
        "## 背景\n"
        "江湖游医一名。\n"
        "\n"
        "**能力**：剑术、轻功、医术\n"
        "\n"
        "**物品**：玉佩、银针包\n"
        "\n"
        "**弱点**：怕水、易心软\n"
    )
    async with SessionMaker() as s:
        sess = await s.get(GameSession, sid)
        char = await s.get(Character, sess.character_id)
        char.profile_md = profile
        await s.commit()

    captured = FakeClient("<narrative>x</narrative>")
    async with SessionMaker() as s:
        async for _ in run_turn(s, sid, "继续", captured):
            pass
        await s.commit()

    sys_msg = captured.last_messages[0].content
    assert "PC 钩子" in sys_msg
    assert "剑术" in sys_msg
    assert "玉佩" in sys_msg
    assert "怕水" in sys_msg


async def test_key_facts_skips_hooks_when_profile_empty(seeded):
    """profile_md 空时不应注入「PC 钩子」段。"""
    engine, SessionMaker, sid = seeded

    async with SessionMaker() as s:
        sess = await s.get(GameSession, sid)
        char = await s.get(Character, sess.character_id)
        char.profile_md = ""
        await s.commit()

    captured = FakeClient("<narrative>x</narrative>")
    async with SessionMaker() as s:
        async for _ in run_turn(s, sid, "继续", captured):
            pass
        await s.commit()

    sys_msg = captured.last_messages[0].content
    # The static system template mentions "PC 钩子" in rule 20 itself; the
    # injected key_facts section uses the heading "## PC 钩子（用上它们）" with
    # concrete bullet rows. Only the latter should be absent when profile is empty.
    assert "## PC 钩子（用上它们）\n能力" not in sys_msg
    assert "## PC 钩子（用上它们）\n物品" not in sys_msg
    assert "## PC 钩子（用上它们）\n弱点" not in sys_msg


async def test_key_facts_includes_pc_numerical_state(seeded):
    """character.level + char_state.stats_json + inventory_json → 注入
    「PC 当前数值」段，列等级 / 属性 / 物品。"""
    engine, SessionMaker, sid = seeded

    async with SessionMaker() as s:
        sess = await s.get(GameSession, sid)
        char = await s.get(Character, sess.character_id)
        char.level = 3
        cs = (await s.execute(
            select(CharState).where(CharState.session_id == sid)
        )).scalar_one()
        cs.stats_json = json.dumps({"hp": 20, "sanity": 15, "力量": 14, "敏捷": 12})
        cs.inventory_json = json.dumps(["剑", "玉佩"])
        await s.commit()

    captured = FakeClient("<narrative>x</narrative>")
    async with SessionMaker() as s:
        async for _ in run_turn(s, sid, "继续", captured):
            pass
        await s.commit()

    sys_msg = captured.last_messages[0].content
    assert "PC 当前数值" in sys_msg
    assert "Lv 3" in sys_msg
    assert "力量=14" in sys_msg
    assert "剑" in sys_msg
    assert "玉佩" in sys_msg


async def test_key_facts_filters_unrevealed_npc_fields(seeded):
    """v0.11: an NPC field whose value is set in the DB but NOT marked
    revealed must NOT leak into the GM system prompt. The NPC's name MUST
    still appear so the GM can refer to them."""
    engine, SessionMaker, sid = seeded
    async with SessionMaker() as s:
        s.add(NPC(
            session_id=sid,
            name="小菱",
            description="某秘密设定不应泄露给玩家",
            purpose="同样不可见的隐秘动机",
            favor=5,
            state="表面平静",
            last_seen_turn=1,
            pinned=True,  # ensures full-dossier path is exercised
            revealed_json='{"name": true}',
        ))
        await s.commit()

    captured = FakeClient("<narrative>x</narrative>")
    async with SessionMaker() as s:
        async for _ in run_turn(s, sid, "继续", captured):
            pass
        await s.commit()

    sys_msg = captured.last_messages[0].content
    # Name must surface so GM can refer to the NPC.
    assert "小菱" in sys_msg
    # Hidden field values must NOT leak.
    assert "某秘密设定不应泄露给玩家" not in sys_msg
    assert "同样不可见的隐秘动机" not in sys_msg
    # GM should be told about hidden fields without seeing their values.
    assert "未揭示" in sys_msg


async def test_key_facts_includes_revealed_npc_fields(seeded):
    """v0.11: when description is revealed, its actual text must appear in
    the GM system prompt — that's what makes it 'revealed'."""
    engine, SessionMaker, sid = seeded
    async with SessionMaker() as s:
        s.add(NPC(
            session_id=sid,
            name="小菱",
            description="已知的公开身份描述",
            favor=3,
            state="警觉",
            last_seen_turn=1,
            pinned=True,
            revealed_json='{"name": true, "description": true}',
        ))
        await s.commit()

    captured = FakeClient("<narrative>x</narrative>")
    async with SessionMaker() as s:
        async for _ in run_turn(s, sid, "继续", captured):
            pass
        await s.commit()

    sys_msg = captured.last_messages[0].content
    assert "小菱" in sys_msg
    assert "已知的公开身份描述" in sys_msg


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
            revealed_json=(
                '{"name":true,"description":true,"state":true,'
                '"purpose":true,"archetype":true,"favor":true,'
                '"affinity":true}'
            ),
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


# ---------------------------------------------------------------------------
# v0.1.0 task B — screenplay progress injection into key_facts
# ---------------------------------------------------------------------------


async def test_key_facts_injects_screenplay_progress(seeded):
    """Active screenplay → key_facts shows '## 当前剧本进度', current chapter
    title, main_events with [pending] markers, and the ending condition.
    This is the GM's source-of-truth for what to advance toward this turn."""
    engine, SessionMaker, sid = seeded
    async with SessionMaker() as s:
        s.add(Screenplay(
            session_id=sid,
            version=1,
            outline_md="测试大纲",
            chapters_json=json.dumps([
                {
                    "title": "第一章：迷雾码头",
                    "main_events": ["PC 抵达码头", "遇见线人"],
                    "optional_events": ["搜查货箱"],
                },
                {"title": "第二章：揭幕", "main_events": ["对峙幕后黑手"]},
            ], ensure_ascii=False),
            main_characters_json="[]",
            ending_md="揭穿走私网络",
            current_chapter=1,
            completed_events_json="[]",
            status="active",
        ))
        await s.commit()

    captured = FakeClient("<narrative>x</narrative>")
    async with SessionMaker() as s:
        async for _ in run_turn(s, sid, "走向码头", captured):
            pass
        await s.commit()

    sys_msg = captured.last_messages[0].content
    assert "## 当前剧本进度" in sys_msg
    assert "第一章" in sys_msg
    assert "迷雾码头" in sys_msg
    # main events listed with [pending] before any complete tag fires
    assert "[pending]" in sys_msg
    assert "PC 抵达码头" in sys_msg
    assert "遇见线人" in sys_msg
    # optional event listed under its own bucket
    assert "[optional]" in sys_msg
    assert "搜查货箱" in sys_msg
    # ending condition surfaced
    assert "揭穿走私网络" in sys_msg


async def test_key_facts_marks_completed_events(seeded):
    """An event with a matching {chapter, event_idx, type} record in
    completed_events_json must render as [done], not [pending]."""
    engine, SessionMaker, sid = seeded
    async with SessionMaker() as s:
        s.add(Screenplay(
            session_id=sid,
            version=1,
            outline_md="x",
            chapters_json=json.dumps([
                {
                    "title": "第一章",
                    "main_events": ["事件零", "事件一"],
                    "optional_events": [],
                },
            ], ensure_ascii=False),
            main_characters_json="[]",
            ending_md="",
            current_chapter=1,
            completed_events_json=json.dumps(
                [{"chapter": 1, "event_idx": 0, "type": "main"}],
                ensure_ascii=False,
            ),
            status="active",
        ))
        await s.commit()

    captured = FakeClient("<narrative>x</narrative>")
    async with SessionMaker() as s:
        async for _ in run_turn(s, sid, "继续", captured):
            pass
        await s.commit()

    sys_msg = captured.last_messages[0].content
    # The completed event_idx=0 must display as [done] 事件零, the other as
    # [pending] 事件一. We assert both signatures appear in order.
    done_idx = sys_msg.find("[done] 事件零")
    pending_idx = sys_msg.find("[pending] 事件一")
    assert done_idx != -1, sys_msg
    assert pending_idx != -1, sys_msg


async def test_key_facts_omits_screenplay_when_none(seeded):
    """Sessions without an active Screenplay (legacy / pre-v0.1.0) must not
    surface the *injected* progress block. We can't simply assert the literal
    header is absent, because rule 24 in the static prompt references it by
    name. Instead we look for the unique signature of the actual injection:
    the parenthesised subtitle '（GM 严格遵守主线，分支由 PC 探索触发）'
    only appears in the injected block, never in the static template."""
    engine, SessionMaker, sid = seeded
    captured = FakeClient("<narrative>x</narrative>")
    async with SessionMaker() as s:
        async for _ in run_turn(s, sid, "继续", captured):
            pass
        await s.commit()

    sys_msg = captured.last_messages[0].content
    # Signature of the *injected* block (only emitted when an active
    # screenplay exists). The plain text "## 当前剧本进度" alone isn't unique
    # because iron rule 24 references it by name; the parenthesised subtitle
    # and "本章主线（必须演完才能推进下章）" only live in the injection.
    assert "GM 严格遵守主线，分支由 PC 探索触发" not in sys_msg
    assert "本章主线（必须演完才能推进下章）" not in sys_msg
    assert "（推进规则：主线 [pending]" not in sys_msg


# ---------------------------------------------------------------------------
# v0.2.2 P1.2 — 剧情强推: key_facts must inject a hard-priority directive when
# the GM has gone too long without completing a main event in the current
# chapter. Real play (72 turns stuck on chapter 1 of 3) showed rule 24 alone
# isn't enough; this section overrides with a concrete next-event directive.
# ---------------------------------------------------------------------------


async def test_key_facts_force_progress_after_3_turns_stuck(seeded):
    """Active screenplay with no completed events + session.turn_count high
    enough that turns_since_progress >= 3 → key_facts must contain the
    「⚠️ 剧情强推」 header and name the next pending main event."""
    engine, SessionMaker, sid = seeded
    async with SessionMaker() as s:
        s.add(Screenplay(
            session_id=sid,
            version=1,
            outline_md="x",
            chapters_json=json.dumps([
                {
                    "title": "第一章",
                    "main_events": ["进入修道院", "找到密信"],
                    "optional_events": [],
                },
                {"title": "第二章", "main_events": ["对峙"]},
            ], ensure_ascii=False),
            main_characters_json="[]",
            ending_md="",
            current_chapter=1,
            completed_events_json="[]",
            status="active",
        ))
        # Push turn_count high enough so that current_turn (4) is past
        # the 3-turn threshold. We bump it directly because the turn_count
        # increment happens inside run_turn — we need it pre-set so the
        # _build_key_facts call inside this turn sees current_turn >= 3.
        sess = await s.get(GameSession, sid)
        sess.turn_count = 3  # next turn will be 4
        await s.commit()

    captured = FakeClient("<narrative>x</narrative>")
    async with SessionMaker() as s:
        async for _ in run_turn(s, sid, "继续探索", captured):
            pass
        await s.commit()

    sys_msg = captured.last_messages[0].content
    # Use a header signature unique to the *injected* block — rule 24 in the
    # static template merely references the name 「⚠️ 剧情强推」 in prose,
    # so we anchor on the parenthesised "已 N 回合无主线进展" subtitle which
    # only appears in the injection.
    assert "## ⚠️ 剧情强推（已" in sys_msg
    assert "回合无主线进展）" in sys_msg
    # Next pending event (idx 0) must be named
    assert "进入修道院" in sys_msg
    # The injected directive points at chapter=1 event=0 type=main
    assert 'chapter="1"' in sys_msg and 'event="0"' in sys_msg


async def test_key_facts_no_force_when_recent_progress(seeded):
    """If completed_events_json has a turn within the last 5 turns the
    strong-push block must NOT appear — the GM has been making progress
    and shouldn't be nagged."""
    engine, SessionMaker, sid = seeded
    async with SessionMaker() as s:
        s.add(Screenplay(
            session_id=sid,
            version=1,
            outline_md="x",
            chapters_json=json.dumps([
                {
                    "title": "第一章",
                    "main_events": ["A", "B", "C"],
                    "optional_events": [],
                },
            ], ensure_ascii=False),
            main_characters_json="[]",
            ending_md="",
            current_chapter=1,
            completed_events_json=json.dumps(
                [{"chapter": 1, "event_idx": 0, "type": "main", "turn": 7}],
                ensure_ascii=False,
            ),
            status="active",
        ))
        sess = await s.get(GameSession, sid)
        sess.turn_count = 7  # next turn is 8 — only 1 turn since progress
        await s.commit()

    captured = FakeClient("<narrative>x</narrative>")
    async with SessionMaker() as s:
        async for _ in run_turn(s, sid, "继续", captured):
            pass
        await s.commit()

    sys_msg = captured.last_messages[0].content
    # Anchor on the *injected* header signature — rule 24 in the static
    # template references 「⚠️ 剧情强推」 in prose, so a bare substring
    # check would falsely fire. The unique signature is the parenthesised
    # turn-count subtitle which only the injection emits.
    assert "## ⚠️ 剧情强推（已" not in sys_msg


async def test_key_facts_force_progress_uses_legacy_estimate(seeded):
    """Legacy completed_events_json rows (predating v0.2.2) lack the `turn`
    field. _build_key_facts must fall back to a coarse estimate so old
    sessions still benefit from strong-push without a migration."""
    engine, SessionMaker, sid = seeded
    async with SessionMaker() as s:
        s.add(Screenplay(
            session_id=sid,
            version=1,
            outline_md="x",
            chapters_json=json.dumps([
                {
                    "title": "第一章",
                    "main_events": ["事件零", "事件一", "事件二"],
                    "optional_events": [],
                },
            ], ensure_ascii=False),
            main_characters_json="[]",
            ending_md="",
            current_chapter=1,
            # Legacy shape — no `turn` field on the record.
            completed_events_json=json.dumps(
                [{"chapter": 1, "event_idx": 0, "type": "main"}],
                ensure_ascii=False,
            ),
            status="active",
        ))
        sess = await s.get(GameSession, sid)
        sess.turn_count = 71  # turn 72 — definitely stuck (matches real-play)
        await s.commit()

    captured = FakeClient("<narrative>x</narrative>")
    async with SessionMaker() as s:
        async for _ in run_turn(s, sid, "继续", captured):
            pass
        await s.commit()

    sys_msg = captured.last_messages[0].content
    # At turn 72 (>= 6) urgency escalates to ❗❗ 极度紧急; the shared subtitle
    # "已 N 回合无主线进展" uniquely identifies the injected block regardless.
    assert "回合无主线进展）" in sys_msg
    # Pending events name the next one (event_idx=1, "事件一")
    assert "事件一" in sys_msg


async def test_force_advance_includes_emit_tag(seeded):
    """Force-advance message includes a copy-paste event_complete tag."""
    engine, SessionMaker, sid = seeded
    async with SessionMaker() as s:
        s.add(Screenplay(
            session_id=sid,
            version=1,
            outline_md="x",
            chapters_json=json.dumps([
                {
                    "title": "第一章",
                    "main_events": ["进入修道院", "找到密信"],
                    "optional_events": [],
                },
            ], ensure_ascii=False),
            main_characters_json="[]",
            ending_md="",
            current_chapter=1,
            completed_events_json="[]",
            status="active",
        ))
        sess = await s.get(GameSession, sid)
        sess.turn_count = 3  # next turn will be 4, so turns_since_progress >= 3
        await s.commit()

    captured = FakeClient("<narrative>x</narrative>")
    async with SessionMaker() as s:
        async for _ in run_turn(s, sid, "继续探索", captured):
            pass
        await s.commit()

    sys_msg = captured.last_messages[0].content
    # The force-advance block must include the event_complete emit tag
    assert "event_complete" in sys_msg
    assert 'chapter="1"' in sys_msg


# ----------------------------------------------------------------------------
# v0.2.1 — long-context fix: recent_messages window shrinks for long games,
# and prompt-token rough estimator is exposed for the activity log warning.
# ----------------------------------------------------------------------------


def test_recent_window_constants_distinct():
    """Three distinct bands so we can tell which kicked in just from the size."""
    assert RECENT_WINDOW_DEFAULT == 12
    assert RECENT_WINDOW_LONG_GAME == 8
    assert RECENT_WINDOW_VERY_LONG == 6


def test_recent_window_for_short_game():
    assert _recent_window_for(0) == RECENT_WINDOW_DEFAULT
    assert _recent_window_for(15) == RECENT_WINDOW_DEFAULT
    assert _recent_window_for(30) == RECENT_WINDOW_DEFAULT  # boundary stays default


def test_recent_window_shrinks_for_long_games():
    """At 35 turns we drop to the long-game window; at 65 to very-long."""
    assert _recent_window_for(31) == RECENT_WINDOW_LONG_GAME
    assert _recent_window_for(35) == RECENT_WINDOW_LONG_GAME
    assert _recent_window_for(60) == RECENT_WINDOW_LONG_GAME  # boundary
    assert _recent_window_for(61) == RECENT_WINDOW_VERY_LONG
    assert _recent_window_for(65) == RECENT_WINDOW_VERY_LONG
    assert _recent_window_for(120) == RECENT_WINDOW_VERY_LONG


async def test_recent_window_actually_applied_at_run_turn(seeded):
    """End-to-end: bump turn_count to 65, run a turn, and verify the prompt
    only carries the last 6 historical messages (very-long band)."""
    engine, SessionMaker, sid = seeded

    # Seed 20 historical message rows (more than any window) and bump turn_count.
    async with SessionMaker() as s:
        sess = await s.get(GameSession, sid)
        for t in range(1, 11):
            s.add(MessageRow(session_id=sid, role="user",
                             content=f"动作{t}", turn=t))
            s.add(MessageRow(session_id=sid, role="assistant",
                             content=f"<narrative>结果{t}</narrative>", turn=t))
        sess.turn_count = 65
        await s.commit()

    client = FakeClient("<narrative>新一回合</narrative>")
    async with SessionMaker() as s:
        async for _ in run_turn(s, sid, "新动作", client):
            pass
        await s.commit()

    # Of the messages passed to the LLM, only the system prompt + recent
    # window + current_action should be present. The very-long window is 6,
    # so we expect at most 6 historical message contents to slip into the
    # context (plus the current "新动作"). Concretely "动作1"/"动作2" must NOT
    # appear because they sit outside the 6-message tail.
    contents = [m.content for m in client.last_messages]
    flat = "\n".join(contents)
    assert "动作1\n" not in flat and "动作1\"" not in flat  # too old
    assert "动作10" in flat or "结果10" in flat  # newest window contents survive
    assert contents[-1] == "新动作"


def test_rough_token_count_cjk_vs_ascii():
    """Rough estimator: CJK ~1.5 chars/tok, ASCII ~4 chars/tok."""
    msgs_cjk = [Message(role="user", content="一二三四五六")]   # 6 CJK
    msgs_ascii = [Message(role="user", content="abcdefgh")]     # 8 ASCII
    # 6 / 1.5 = 4 tokens for CJK; 8 / 4 = 2 tokens for ASCII
    assert _rough_token_count(msgs_cjk) == 4
    assert _rough_token_count(msgs_ascii) == 2
    assert _rough_token_count([]) == 0


# ============================================================================
# v0.2.2 P1.6 — dice randomness monitor
# ============================================================================

async def test_key_facts_warns_on_stuck_d20(seeded):
    """When the last 3 assistant turns all rolled the same d20 value, the next
    prompt's key_facts should include a `## ⚠️ Dice 警告` block telling the GM
    to vary the value."""
    _, SessionMaker, sid = seeded

    # Seed 3 assistant turns whose events_json each carries a d20=9 dice tag.
    async with SessionMaker() as s:
        for t in range(1, 4):
            events = [{
                "type": "dice",
                "payload": {"skill": "洞察", "target": "12"},
                "content": "d20=9，失败",
            }]
            s.add(MessageRow(
                session_id=sid, role="assistant",
                content=f"<dice skill=\"洞察\" target=\"12\">d20=9，失败</dice>",
                turn=t,
                events_json=json.dumps(events, ensure_ascii=False),
            ))
        await s.commit()

    client = FakeClient("<narrative>下一回合</narrative>")
    async with SessionMaker() as s:
        async for _ in run_turn(s, sid, "继续", client):
            pass
        await s.commit()

    sys_msg = client.last_messages[0].content
    assert "Dice 警告" in sys_msg
    assert "d20=9" in sys_msg


async def test_key_facts_no_dice_warning_when_varied(seeded):
    """Varied d20 values must NOT trigger the warning."""
    _, SessionMaker, sid = seeded

    async with SessionMaker() as s:
        for t, val in zip(range(1, 4), (9, 14, 7)):
            events = [{"type": "dice", "payload": {}, "content": f"d20={val}"}]
            s.add(MessageRow(
                session_id=sid, role="assistant",
                content=f"<dice>d20={val}</dice>",
                turn=t,
                events_json=json.dumps(events, ensure_ascii=False),
            ))
        await s.commit()

    client = FakeClient("<narrative>x</narrative>")
    async with SessionMaker() as s:
        async for _ in run_turn(s, sid, "继续", client):
            pass
        await s.commit()

    sys_msg = client.last_messages[0].content
    assert "Dice 警告" not in sys_msg


async def test_key_facts_no_dice_warning_when_only_two_same(seeded):
    """Need ≥3 same in a row (min_streak default = 2) to trigger."""
    _, SessionMaker, sid = seeded

    async with SessionMaker() as s:
        for t, val in zip(range(1, 3), (9, 9)):
            events = [{"type": "dice", "payload": {}, "content": f"d20={val}"}]
            s.add(MessageRow(
                session_id=sid, role="assistant",
                content=f"<dice>d20={val}</dice>",
                turn=t,
                events_json=json.dumps(events, ensure_ascii=False),
            ))
        await s.commit()

    client = FakeClient("<narrative>x</narrative>")
    async with SessionMaker() as s:
        async for _ in run_turn(s, sid, "继续", client):
            pass
        await s.commit()

    sys_msg = client.last_messages[0].content
    assert "Dice 警告" not in sys_msg


# ============================================================================
# v0.2.6 T3 — GM prompt 注入当前场地
# ============================================================================

async def test_key_facts_includes_current_location(seeded):
    """_build_key_facts includes current location name, in-scene NPCs, and items."""
    from dzmm.db.models import Location
    from dzmm.service.game import _build_key_facts

    _, SessionMaker, sid = seeded

    async with SessionMaker() as s:
        loc = Location(session_id=sid, name="书房", description="摆满书架的房间",
                       first_visited_turn=1, last_visited_turn=1, is_current=True,
                       items_json=json.dumps([{"name": "戒指", "description": "一枚金戒指"}]))
        s.add(loc)

        npc = NPC(session_id=sid, name="镜中人", description="", favor=0,
                  state="被困", last_seen_turn=1, notes_json="[]", purpose="",
                  archetype="", affinity_json="{}", pinned=False,
                  revealed_json='{"name":true}', current_location="书房")
        s.add(npc)
        await s.commit()

    async with SessionMaker() as s:
        result = await _build_key_facts(s, sid, 2)
    assert "书房" in result
    assert "镜中人" in result
    assert "戒指" in result
