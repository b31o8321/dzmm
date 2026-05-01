import json
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.db.base import init_db, get_engine, async_session
from dzmm.db.models import (
    Character, CharState, Era, HiddenEvent, ModelConfig, NPC, NpcRelation, PCGoal, PlotThread, Screenplay, ScreenplayRevision, Session as GameSession, World,
)
from dzmm.parsing.events import TagComplete
from dzmm.service.state_apply import apply_tags


@pytest.fixture
async def session_with_state(tmp_path):
    engine = get_engine(f"sqlite+aiosqlite:///{tmp_path}/t.db")
    await init_db(engine)
    SessionMaker = async_session(engine)
    async with SessionMaker() as s:
        world = World(name="W", content_md="x", style="dark")
        char = Character(world=world, name="C", profile_md="y",
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
        yield s, sess.id
    await engine.dispose()


async def test_apply_state_change_updates_stats(session_with_state):
    s, sid = session_with_state
    tag = TagComplete(name="state_change", content='{"hp": -5, "sanity": -2}')
    await apply_tags(s, sid, current_turn=1, tags=[tag])
    await s.commit()

    cs = (await s.execute(
        select(CharState).where(CharState.session_id == sid)
    )).scalar_one()
    stats = json.loads(cs.stats_json)
    assert stats["hp"] == 15
    assert stats["sanity"] == 13


async def test_inventory_add_and_remove(session_with_state):
    s, sid = session_with_state
    tag = TagComplete(name="state_change",
                      content='{"inventory_add": ["钥匙","小刀"]}')
    await apply_tags(s, sid, current_turn=1, tags=[tag])
    await s.commit()

    cs = (await s.execute(
        select(CharState).where(CharState.session_id == sid)
    )).scalar_one()
    assert json.loads(cs.inventory_json) == ["钥匙", "小刀"]

    tag2 = TagComplete(name="state_change",
                       content='{"inventory_remove": ["钥匙"]}')
    await apply_tags(s, sid, current_turn=2, tags=[tag2])
    await s.commit()

    cs = (await s.execute(
        select(CharState).where(CharState.session_id == sid)
    )).scalar_one()
    assert json.loads(cs.inventory_json) == ["小刀"]


async def test_npc_update_creates_and_updates(session_with_state):
    s, sid = session_with_state
    tag = TagComplete(
        name="npc_update",
        content='{"name":"卫兵长","favor_delta":-10,"state":"警戒"}',
    )
    await apply_tags(s, sid, current_turn=1, tags=[tag])
    await s.commit()

    npcs = (await s.execute(
        select(NPC).where(NPC.session_id == sid)
    )).scalars().all()
    assert len(npcs) == 1
    npc = npcs[0]
    assert npc.name == "卫兵长"
    assert npc.favor == -10
    assert npc.state == "警戒"
    assert npc.last_seen_turn == 1

    tag2 = TagComplete(
        name="npc_update",
        content='{"name":"卫兵长","favor_delta":-5,"state":"敌对"}',
    )
    await apply_tags(s, sid, current_turn=2, tags=[tag2])
    await s.commit()

    npcs = (await s.execute(
        select(NPC).where(NPC.session_id == sid)
    )).scalars().all()
    assert len(npcs) == 1
    assert npcs[0].favor == -15
    assert npcs[0].state == "敌对"
    assert npcs[0].last_seen_turn == 2


async def test_apply_tags_skips_malformed_json(session_with_state):
    s, sid = session_with_state
    tag = TagComplete(name="state_change", content="not-json-at-all")
    await apply_tags(s, sid, current_turn=1, tags=[tag])
    await s.commit()
    cs = (await s.execute(
        select(CharState).where(CharState.session_id == sid)
    )).scalar_one()
    assert json.loads(cs.stats_json) == {"hp": 20, "sanity": 15}


async def test_ignores_non_state_tags(session_with_state):
    s, sid = session_with_state
    tag = TagComplete(name="dice", content="d20=15")
    await apply_tags(s, sid, current_turn=1, tags=[tag])
    await s.commit()


async def test_apply_plot_event_creates_thread(session_with_state):
    s, sid = session_with_state
    tag = TagComplete(
        name="plot_event",
        attrs={"type": "new_quest", "importance": "3"},
        content="从义体黑市的山猫处取回加密芯片",
    )
    await apply_tags(s, sid, current_turn=1, tags=[tag])
    await s.commit()

    threads = (await s.execute(
        select(PlotThread).where(PlotThread.session_id == sid)
    )).scalars().all()
    assert len(threads) == 1
    assert threads[0].type == "new_quest"
    assert threads[0].importance == 3
    assert threads[0].status == "active"
    assert "山猫" in threads[0].description


async def test_npc_purpose_archetype_setter(session_with_state):
    """purpose / archetype are setters: subsequent updates overwrite prior values."""
    s, sid = session_with_state
    tag = TagComplete(
        name="npc_update",
        content=(
            '{"name":"御坂雪","purpose":"查清祖母遗物里咒符的来源",'
            '"archetype":"外柔内刚的文学少女"}'
        ),
    )
    await apply_tags(s, sid, current_turn=1, tags=[tag])
    await s.commit()

    npc = (await s.execute(
        select(NPC).where(NPC.session_id == sid)
    )).scalar_one()
    assert npc.purpose == "查清祖母遗物里咒符的来源"
    assert npc.archetype == "外柔内刚的文学少女"

    tag2 = TagComplete(
        name="npc_update",
        content='{"name":"御坂雪","purpose":"保护妹妹"}',
    )
    await apply_tags(s, sid, current_turn=2, tags=[tag2])
    await s.commit()

    npc = (await s.execute(
        select(NPC).where(NPC.session_id == sid)
    )).scalar_one()
    assert npc.purpose == "保护妹妹"
    # archetype unchanged because not provided
    assert npc.archetype == "外柔内刚的文学少女"


async def test_npc_affinity_additive_multiaxis(session_with_state):
    """affinity is a partial axis→delta map; multiple updates accumulate per axis."""
    s, sid = session_with_state
    tag1 = TagComplete(
        name="npc_update",
        content='{"name":"御坂雪","affinity":{"信任":5,"羁绊":2}}',
    )
    await apply_tags(s, sid, current_turn=1, tags=[tag1])
    await s.commit()

    tag2 = TagComplete(
        name="npc_update",
        content='{"name":"御坂雪","affinity":{"信任":3}}',
    )
    await apply_tags(s, sid, current_turn=2, tags=[tag2])
    await s.commit()

    npc = (await s.execute(
        select(NPC).where(NPC.session_id == sid)
    )).scalar_one()
    affinity = json.loads(npc.affinity_json)
    assert affinity == {"信任": 8, "羁绊": 2}


async def test_recall_appends_name_to_session_pending(session_with_state):
    """<recall name="X"/> appends X to Session.recall_pending_json (idempotent)."""
    s, sid = session_with_state
    tag = TagComplete(name="recall", attrs={"name": "御坂雪"}, content="")
    await apply_tags(s, sid, current_turn=1, tags=[tag])
    await s.commit()

    sess = await s.get(GameSession, sid)
    pending = json.loads(sess.recall_pending_json)
    assert "御坂雪" in pending

    # Repeating the same name shouldn't duplicate.
    await apply_tags(s, sid, current_turn=2, tags=[tag])
    await s.commit()
    sess = await s.get(GameSession, sid)
    pending = json.loads(sess.recall_pending_json)
    assert pending.count("御坂雪") == 1

    # A second recall name is appended.
    tag2 = TagComplete(name="recall", attrs={"name": "卫兵长"}, content="")
    await apply_tags(s, sid, current_turn=3, tags=[tag2])
    await s.commit()
    sess = await s.get(GameSession, sid)
    pending = json.loads(sess.recall_pending_json)
    assert "卫兵长" in pending and "御坂雪" in pending


async def test_character_xp_tag_grants_xp(session_with_state):
    s, sid = session_with_state
    tag = TagComplete(name="character_xp", attrs={"delta": "50"},
                      content="完成任务")
    await apply_tags(s, sid, current_turn=1, tags=[tag])
    await s.commit()

    sess = await s.get(GameSession, sid)
    char = await s.get(Character, sess.character_id)
    assert char.xp == 50
    # Level is NOT auto-bumped — that happens via the explicit /levelup endpoint.
    assert char.level == 1


async def test_character_xp_tag_accumulates(session_with_state):
    s, sid = session_with_state
    tag1 = TagComplete(name="character_xp", attrs={"delta": "30"}, content="支线")
    tag2 = TagComplete(name="character_xp", attrs={"delta": "20"}, content="另一段")
    await apply_tags(s, sid, current_turn=1, tags=[tag1, tag2])
    await s.commit()

    sess = await s.get(GameSession, sid)
    char = await s.get(Character, sess.character_id)
    assert char.xp == 50


async def test_character_xp_tag_ignores_zero_and_invalid(session_with_state):
    s, sid = session_with_state
    bad = [
        TagComplete(name="character_xp", attrs={"delta": "0"}, content=""),
        TagComplete(name="character_xp", attrs={"delta": "abc"}, content=""),
        TagComplete(name="character_xp", attrs={}, content=""),
    ]
    await apply_tags(s, sid, current_turn=1, tags=bad)
    await s.commit()

    sess = await s.get(GameSession, sid)
    char = await s.get(Character, sess.character_id)
    assert char.xp == 0


async def test_character_xp_tag_floors_at_zero(session_with_state):
    s, sid = session_with_state
    tag = TagComplete(name="character_xp", attrs={"delta": "-100"}, content="罚")
    await apply_tags(s, sid, current_turn=1, tags=[tag])
    await s.commit()

    sess = await s.get(GameSession, sid)
    char = await s.get(Character, sess.character_id)
    assert char.xp == 0


async def test_era_begin_creates_row(session_with_state):
    s, sid = session_with_state
    tag = TagComplete(
        name="era_begin",
        attrs={"name": "第二章：九龙黑街"},
        content="经过霓虹猫酒馆的事件，故事进入新阶段。",
    )
    await apply_tags(s, sid, current_turn=5, tags=[tag])
    await s.commit()

    eras = (await s.execute(select(Era).where(Era.session_id == sid))).scalars().all()
    assert len(eras) == 1
    assert eras[0].name == "第二章：九龙黑街"
    assert eras[0].started_turn == 5
    assert "霓虹猫" in eras[0].description


async def test_era_begin_without_name_skipped(session_with_state):
    s, sid = session_with_state
    tag = TagComplete(name="era_begin", attrs={}, content="无名章节")
    await apply_tags(s, sid, current_turn=1, tags=[tag])
    await s.commit()

    eras = (await s.execute(select(Era).where(Era.session_id == sid))).scalars().all()
    assert len(eras) == 0


async def test_pc_goal_add_creates_row(session_with_state):
    s, sid = session_with_state
    tag = TagComplete(
        name="pc_goal", attrs={"type": "add", "priority": "high"},
        content="找到义体黑医",
    )
    await apply_tags(s, sid, current_turn=2, tags=[tag])
    await s.commit()

    goals = (await s.execute(select(PCGoal).where(PCGoal.session_id == sid))).scalars().all()
    assert len(goals) == 1
    assert goals[0].description == "找到义体黑医"
    assert goals[0].priority == "high"
    assert goals[0].status == "active"
    assert goals[0].introduced_turn == 2


async def test_pc_goal_complete_closes_existing(session_with_state):
    s, sid = session_with_state

    # 先 add
    add_tag = TagComplete(name="pc_goal", attrs={"type": "add"}, content="目标 A")
    await apply_tags(s, sid, current_turn=1, tags=[add_tag])
    await s.commit()
    goal_id = (await s.execute(select(PCGoal.id).where(PCGoal.session_id == sid))).scalar_one()

    # 再 complete
    complete_tag = TagComplete(
        name="pc_goal", attrs={"type": "complete", "id": str(goal_id)},
        content="任务完成原因",
    )
    await apply_tags(s, sid, current_turn=5, tags=[complete_tag])
    await s.commit()

    goal = (await s.execute(
        select(PCGoal).where(PCGoal.id == goal_id)
    )).scalar_one()
    assert goal.status == "completed"
    assert goal.completed_turn == 5
    assert "完成原因" in goal.completion_note


async def test_npc_emotion_accumulates_and_clamps(session_with_state):
    """5-axis emotion deltas accumulate and clamp to [0, 100]."""
    s, sid = session_with_state
    tag1 = TagComplete(
        name="npc_update",
        content='{"name":"御坂雪","emotion":{"love":40,"fear":10}}',
    )
    await apply_tags(s, sid, current_turn=1, tags=[tag1])
    await s.commit()

    npc = (await s.execute(select(NPC).where(NPC.session_id == sid))).scalar_one()
    emo = json.loads(npc.emotion_json)
    assert emo == {"love": 40, "fear": 10}

    # Second update accumulates and clamps.
    tag2 = TagComplete(
        name="npc_update",
        content='{"name":"御坂雪","emotion":{"love":80,"fear":-30}}',
    )
    await apply_tags(s, sid, current_turn=2, tags=[tag2])
    await s.commit()

    npc = (await s.execute(select(NPC).where(NPC.session_id == sid))).scalar_one()
    emo = json.loads(npc.emotion_json)
    assert emo["love"] == 100  # 40 + 80 clamped to 100
    assert emo["fear"] == 0    # 10 - 30 clamped to 0


async def test_npc_emotion_unknown_axis_ignored(session_with_state):
    s, sid = session_with_state
    tag = TagComplete(
        name="npc_update",
        content='{"name":"X","emotion":{"love":10,"happiness":50}}',
    )
    await apply_tags(s, sid, current_turn=1, tags=[tag])
    await s.commit()

    npc = (await s.execute(select(NPC).where(NPC.session_id == sid))).scalar_one()
    emo = json.loads(npc.emotion_json)
    assert emo == {"love": 10}  # unknown axis dropped


async def test_pc_mood_accumulates_and_clamps(session_with_state):
    """<pc_mood> deltas accumulate into Session.pc_mood_json, clamp 0-100."""
    s, sid = session_with_state
    tag1 = TagComplete(name="pc_mood", content='{"tense": 30, "exhausted": 10}')
    await apply_tags(s, sid, current_turn=1, tags=[tag1])
    await s.commit()

    sess = await s.get(GameSession, sid)
    moods = json.loads(sess.pc_mood_json)
    assert moods == {"tense": 30, "exhausted": 10}

    tag2 = TagComplete(name="pc_mood", content='{"tense": 80, "exhausted": -20}')
    await apply_tags(s, sid, current_turn=2, tags=[tag2])
    await s.commit()

    sess = await s.get(GameSession, sid)
    moods = json.loads(sess.pc_mood_json)
    assert moods["tense"] == 100  # 30 + 80 clamped
    assert moods["exhausted"] == 0  # 10 - 20 clamped


async def test_pc_mood_skips_non_numeric(session_with_state):
    s, sid = session_with_state
    tag = TagComplete(
        name="pc_mood", content='{"calm": 5, "weird": "not-a-number"}'
    )
    await apply_tags(s, sid, current_turn=1, tags=[tag])
    await s.commit()

    sess = await s.get(GameSession, sid)
    moods = json.loads(sess.pc_mood_json)
    assert moods == {"calm": 5}


async def test_npc_relation_creates_row(session_with_state):
    s, sid = session_with_state
    tag = TagComplete(
        name="npc_relation",
        attrs={"between": "御坂雪,卫兵长", "kind": "父女"},
        content="御坂雪是卫兵长失散多年的女儿。",
    )
    await apply_tags(s, sid, current_turn=3, tags=[tag])
    await s.commit()

    rels = (await s.execute(
        select(NpcRelation).where(NpcRelation.session_id == sid)
    )).scalars().all()
    assert len(rels) == 1
    r = rels[0]
    assert r.npc_a == "御坂雪"
    assert r.npc_b == "卫兵长"
    assert r.kind == "父女"
    assert "失散多年" in r.description
    assert r.introduced_turn == 3


async def test_npc_relation_dedupes_unordered_pair(session_with_state):
    """A↔B with the same kind is treated as the same relation as B↔A."""
    s, sid = session_with_state
    tag1 = TagComplete(
        name="npc_relation",
        attrs={"between": "御坂雪,卫兵长", "kind": "父女"},
        content="",
    )
    await apply_tags(s, sid, current_turn=3, tags=[tag1])
    await s.commit()

    # Reverse order, same kind — must NOT create a duplicate.
    tag2 = TagComplete(
        name="npc_relation",
        attrs={"between": "卫兵长,御坂雪", "kind": "父女"},
        content="补充：母亲早逝。",
    )
    await apply_tags(s, sid, current_turn=4, tags=[tag2])
    await s.commit()

    rels = (await s.execute(
        select(NpcRelation).where(NpcRelation.session_id == sid)
    )).scalars().all()
    assert len(rels) == 1
    # Description should be backfilled from the second declaration.
    assert "母亲早逝" in rels[0].description


async def test_npc_relation_invalid_between_skipped(session_with_state):
    s, sid = session_with_state
    tag = TagComplete(
        name="npc_relation",
        attrs={"between": "只有一个名字", "kind": "盟友"},
        content="",
    )
    await apply_tags(s, sid, current_turn=1, tags=[tag])
    await s.commit()

    rels = (await s.execute(
        select(NpcRelation).where(NpcRelation.session_id == sid)
    )).scalars().all()
    assert len(rels) == 0


async def test_hidden_event_create(session_with_state):
    """<hidden_event> with required `kind` creates an active row keyed to subject."""
    s, sid = session_with_state
    tag = TagComplete(
        name="hidden_event",
        attrs={
            "subject": "小菱",
            "kind": "injury",
            "severity": "2",
            "description": "云梦泽蒙面人砍伤渗血",
            "consequence": "再过 5 回合不治会昏迷",
        },
        content="",
    )
    await apply_tags(s, sid, current_turn=3, tags=[tag])
    await s.commit()

    rows = (await s.execute(
        select(HiddenEvent).where(HiddenEvent.session_id == sid)
    )).scalars().all()
    assert len(rows) == 1
    ev = rows[0]
    assert ev.subject == "小菱"
    assert ev.kind == "injury"
    assert ev.severity == 2
    assert ev.status == "active"
    assert ev.introduced_turn == 3
    assert "渗血" in ev.description
    assert "昏迷" in ev.consequence


async def test_hidden_event_resolve(session_with_state):
    """A second <hidden_event resolve subject="..."/> marks the active row resolved."""
    s, sid = session_with_state
    create_tag = TagComplete(
        name="hidden_event",
        attrs={
            "subject": "小菱",
            "kind": "injury",
            "severity": "2",
            "description": "渗血",
        },
        content="",
    )
    await apply_tags(s, sid, current_turn=3, tags=[create_tag])
    await s.commit()

    resolve_tag = TagComplete(
        name="hidden_event",
        attrs={"resolve": "1", "subject": "小菱", "resolution": "包扎止血"},
        content="",
    )
    await apply_tags(s, sid, current_turn=8, tags=[resolve_tag])
    await s.commit()

    ev = (await s.execute(
        select(HiddenEvent).where(HiddenEvent.session_id == sid)
    )).scalar_one()
    assert ev.status == "resolved"
    assert ev.resolved_turn == 8
    assert "包扎" in ev.resolution


async def test_hidden_event_ignores_invalid(session_with_state):
    """Missing kind → no insert. Resolve on a non-existent subject → silent skip."""
    s, sid = session_with_state

    # Missing kind
    invalid = TagComplete(
        name="hidden_event",
        attrs={"subject": "无名"},
        content="",
    )
    await apply_tags(s, sid, current_turn=1, tags=[invalid])
    await s.commit()
    rows = (await s.execute(
        select(HiddenEvent).where(HiddenEvent.session_id == sid)
    )).scalars().all()
    assert rows == []

    # Resolve a subject that doesn't exist — must not raise.
    resolve = TagComplete(
        name="hidden_event",
        attrs={"resolve": "1", "subject": "幽灵"},
        content="",
    )
    await apply_tags(s, sid, current_turn=2, tags=[resolve])
    await s.commit()
    rows = (await s.execute(
        select(HiddenEvent).where(HiddenEvent.session_id == sid)
    )).scalars().all()
    assert rows == []


async def test_hidden_event_payload_in_body_json(session_with_state):
    """GM may put the payload as JSON inside the tag body — also accepted."""
    s, sid = session_with_state
    tag = TagComplete(
        name="hidden_event",
        attrs={},
        content='{"subject":"小菱","kind":"poison","severity":3,"description":"中毒"}',
    )
    await apply_tags(s, sid, current_turn=4, tags=[tag])
    await s.commit()

    ev = (await s.execute(
        select(HiddenEvent).where(HiddenEvent.session_id == sid)
    )).scalar_one()
    assert ev.kind == "poison"
    assert ev.severity == 3
    assert ev.subject == "小菱"


async def test_hidden_event_dedup_same_subject_and_kind(session_with_state):
    """v0.1.9: emitting the same (subject, kind) twice while the first row is
    still active must update the existing row, not insert a second copy.
    Fixes real-play GM looping the same hidden_event 6× in one playthrough."""
    s, sid = session_with_state

    first = TagComplete(
        name="hidden_event",
        attrs={
            "subject": "小菱",
            "kind": "injury",
            "severity": "2",
            "description": "first description",
            "consequence": "first consequence",
        },
        content="",
    )
    await apply_tags(s, sid, current_turn=3, tags=[first])
    await s.commit()

    second = TagComplete(
        name="hidden_event",
        attrs={
            "subject": "小菱",
            "kind": "injury",
            "severity": "2",
            "description": "updated description",
            "consequence": "updated consequence",
        },
        content="",
    )
    await apply_tags(s, sid, current_turn=4, tags=[second])
    await s.commit()

    rows = (await s.execute(
        select(HiddenEvent).where(
            HiddenEvent.session_id == sid,
            HiddenEvent.status == "active",
        )
    )).scalars().all()
    assert len(rows) == 1, "dedup must collapse same (subject,kind) into one row"
    assert rows[0].description == "updated description"
    assert rows[0].consequence == "updated consequence"
    # introduced_turn is the original create turn — not bumped on update.
    assert rows[0].introduced_turn == 3


async def test_npc_ner_fallback_creates_stub(session_with_state):
    """Narrative text mentioning a name without <npc_update> creates a stub NPC."""
    s, sid = session_with_state
    # v0.2.1: NER min length is now 3 chars; use a 3-char name (林婉儿) so the
    # heuristic can pick it up. 林婉儿 must appear ≥ 3x to satisfy freq.
    narrative = (
        "林婉儿颤抖着说话。她抬头时，林婉儿的眼角还挂着泪。"
        "片刻后，林婉儿深吸一口气。"
    )
    await apply_tags(
        s, sid, current_turn=1, tags=[], narrative_text=narrative
    )
    await s.commit()

    npcs = (await s.execute(
        select(NPC).where(NPC.session_id == sid, NPC.name == "林婉儿")
    )).scalars().all()
    assert len(npcs) == 1
    assert npcs[0].description == "（GM 未补全）"
    assert npcs[0].last_seen_turn == 1


async def test_npc_ner_skips_existing(session_with_state):
    """If an NPC with that name already exists, NER should not duplicate."""
    s, sid = session_with_state
    s.add(NPC(
        session_id=sid,
        name="林婉儿",
        description="原本就登记好的",
        favor=2,
        state="平静",
        last_seen_turn=0,
    ))
    await s.commit()

    # v0.2.1: 3-char name (林婉儿) needed since NER min length is now 3.
    narrative = (
        "林婉儿颤抖着说话。林婉儿低声重复了一遍。"
        "片刻后，林婉儿抬头望向月光。"
    )
    await apply_tags(
        s, sid, current_turn=5, tags=[], narrative_text=narrative
    )
    await s.commit()

    npcs = (await s.execute(
        select(NPC).where(NPC.session_id == sid, NPC.name == "林婉儿")
    )).scalars().all()
    # Still exactly one row — original kept.
    assert len(npcs) == 1
    assert npcs[0].description == "原本就登记好的"


async def test_npc_ner_skips_when_explicit_npc_update(session_with_state):
    """If GM declared the NPC via <npc_update> this turn, NER must not re-stub."""
    s, sid = session_with_state
    npc_tag = TagComplete(
        name="npc_update",
        content='{"name":"林婉儿","description":"少女剑客","state":"警觉"}',
    )
    # v0.2.1: 3-char name (林婉儿) — 2-char no longer registers via NER.
    narrative = (
        "林婉儿颤抖着说话。林婉儿握紧了剑柄。"
        "随即，林婉儿深吸一口气。"
    )
    await apply_tags(
        s, sid, current_turn=1, tags=[npc_tag], narrative_text=narrative
    )
    await s.commit()

    npcs = (await s.execute(
        select(NPC).where(NPC.session_id == sid, NPC.name == "林婉儿")
    )).scalars().all()
    assert len(npcs) == 1
    # The explicit npc_update wins — description is the GM-supplied one,
    # not the "(GM 未补全)" stub.
    assert npcs[0].description == "少女剑客"
    assert npcs[0].state == "警觉"


async def test_npc_ner_filters_stopwords(session_with_state):
    """Common pronouns / scene words must NOT be registered as NPCs."""
    s, sid = session_with_state
    narrative = "你看见远处。远处有一座庙。远处的雾很浓。她转过身。"
    await apply_tags(
        s, sid, current_turn=1, tags=[], narrative_text=narrative
    )
    await s.commit()

    npcs = (await s.execute(select(NPC).where(NPC.session_id == sid))).scalars().all()
    assert npcs == []


async def test_npc_ner_rejects_known_stopwords_v019(session_with_state):
    """v0.1.9 strictness: real-play junk like 修道院 / 大门 / 然后 /
    雨水 / 离开 must never be created as NPC stubs even at high frequency."""
    s, sid = session_with_state
    narrative = (
        "修道院的大门吱呀打开。修道院的钟声响起。修道院的廊柱阴森。"
        "然后管理人员走出来。然后他点了点头。然后他离开了。"
        "雨水拍打着大门。雨水滴落在屋檐。雨水浸透了石阶。"
        "离开是唯一的办法。离开吧。离开这里。"
    )
    await apply_tags(
        s, sid, current_turn=1, tags=[], narrative_text=narrative
    )
    await s.commit()

    npcs = (await s.execute(select(NPC).where(NPC.session_id == sid))).scalars().all()
    names = {n.name for n in npcs}
    for junk in ("修道院", "大门", "然后", "雨水", "离开"):
        assert junk not in names, (
            f"NER must reject stopword/junk '{junk}', got {names}"
        )


async def test_npc_ner_requires_min_freq_three(session_with_state):
    """v0.1.9: a hanzi token must appear ≥ 3× to be registered.
    Two appearances no longer suffice (was the previous threshold).

    v0.2.1: min length raised 2 → 3 chars; using 张三丰 (3 chars) here so the
    test exercises freq alone, not the length rule."""
    s, sid = session_with_state
    # 张三丰 appears exactly 2× — below threshold of 3.
    narrative = "张三丰看见远处。后来张三丰离开了。"
    await apply_tags(
        s, sid, current_turn=1, tags=[], narrative_text=narrative
    )
    await s.commit()

    npcs2 = (
        await s.execute(select(NPC).where(NPC.session_id == sid, NPC.name == "张三丰"))
    ).scalars().all()
    assert npcs2 == [], "freq=2 must NOT register"

    # Now 3× — should register.
    narrative3 = "张三丰看见远处。张三丰低声开口。张三丰缓缓离开。"
    await apply_tags(
        s, sid, current_turn=2, tags=[], narrative_text=narrative3
    )
    await s.commit()

    npcs3 = (
        await s.execute(select(NPC).where(NPC.session_id == sid, NPC.name == "张三丰"))
    ).scalars().all()
    assert len(npcs3) == 1, "freq=3 must register"


async def test_ner_rejects_all_v0_2_1_garbage_names(session_with_state):
    """v0.2.1 P0.1: real-play 72 turns produced 24 NPCs; 20 were NER junk.
    Each garbage name appears 5× in narrative — well above the freq=3 floor —
    yet none of them must end up in the NPC table after our 4 strictness
    measures (min 3 chars / PC substring / extended stopwords / first-char
    threshold)."""
    s, sid = session_with_state
    # Subset of the 20 garbage names that are 2-char or 3-char fragments.
    # 2-char ones (里面/写着/了你/我从/...) are killed by the min-length rule.
    # 3-char ones (any in this list) are killed by the stopword / first-char
    # threshold rules.
    garbage = [
        "里面", "写着", "印着", "面对", "标签",
        "了你", "我从", "她轻", "个叫", "远叫",
        "的一", "的那", "的黑", "一丝",
    ]
    # Each garbage word repeats 5 times — guaranteed past freq=3 floor.
    narrative = "。".join(g * 5 for g in garbage)
    await apply_tags(
        s, sid, current_turn=1, tags=[], narrative_text=narrative
    )
    await s.commit()

    rows = (
        await s.execute(select(NPC).where(NPC.session_id == sid))
    ).scalars().all()
    names = {n.name for n in rows}
    for junk in garbage:
        assert junk not in names, (
            f"v0.2.1: NER must reject playtest junk '{junk}', got NPC table {names}"
        )


async def test_ner_rejects_pc_name_substrings(session_with_state):
    """v0.2.1 P0.1 (2): substrings of the PC name must never be created as
    independent NPC stubs. PC '塞巴斯蒂安·冯·奥斯特' must not produce stubs for
    '塞巴' / '塞巴斯' / '奥斯特' / '巴斯蒂' even at high frequency."""
    s, sid = session_with_state
    pc_name = "塞巴斯蒂安·冯·奥斯特"
    # All four substrings appear 4-5 times each — past freq=3 — and have
    # no verb-led head char, so the only thing that should reject them is
    # the PC-substring filter.
    narrative = (
        "塞巴来到广场。塞巴看见月光。塞巴沉默了。塞巴又一次看到。"
        "塞巴斯走过长廊。塞巴斯抬起头。塞巴斯听见钟声。"
        "奥斯特的影子拉长。奥斯特低语。奥斯特沉吟。奥斯特走开。"
        "巴斯蒂转身。巴斯蒂低头。巴斯蒂沉默。巴斯蒂离开。"
    )
    await apply_tags(
        s,
        sid,
        current_turn=1,
        tags=[],
        narrative_text=narrative,
        character_name=pc_name,
    )
    await s.commit()

    rows = (
        await s.execute(select(NPC).where(NPC.session_id == sid))
    ).scalars().all()
    names = {n.name for n in rows}
    for sub in ("塞巴", "塞巴斯", "奥斯特", "巴斯蒂"):
        assert sub not in names, (
            f"v0.2.1: PC-name substring '{sub}' must not become an NPC; "
            f"got {names}"
        )


async def test_ner_first_char_threshold(session_with_state):
    """v0.2.1 P0.1 (4): candidates whose first char is one of
    了/的/着/我/她/他/一/这/那/有/被/把/给/为/之/从 require length >= 4. A 3-char
    hit like '了一段' must be rejected; a 4-char hit like '了空大师' is fine."""
    s, sid = session_with_state
    # '了一段' starts with '了' — must NOT register at len=3 even at freq=5.
    # Add an unrelated 4-char name that does NOT start with a threshold char
    # so the same run also produces a positive control. We use 赵铁柱叔 (4
    # chars, starts with 赵 which is not in _FIRST_CHAR_NEEDS_LONGER).
    narrative = (
        "了一段。了一段。了一段。了一段。了一段。"
        "赵铁柱叔走来。赵铁柱叔点头。赵铁柱叔离去。"
    )
    await apply_tags(
        s, sid, current_turn=1, tags=[], narrative_text=narrative
    )
    await s.commit()

    rows = (
        await s.execute(select(NPC).where(NPC.session_id == sid))
    ).scalars().all()
    names = {n.name for n in rows}
    assert "了一段" not in names, (
        f"3-char candidate starting with '了' must be rejected, got {names}"
    )


async def test_npc_create_auto_reveals_provided_fields(session_with_state):
    """v0.11: when an NPC is first created via <npc_update>, fields whose
    values are set in the same payload are auto-marked revealed (the GM has
    just written them so the player has seen them). Fields not provided
    remain hidden."""
    s, sid = session_with_state
    tag = TagComplete(
        name="npc_update",
        content='{"name":"小菱","description":"少女剑客","purpose":"找同伴"}',
    )
    await apply_tags(s, sid, current_turn=1, tags=[tag])
    await s.commit()

    npc = (await s.execute(
        select(NPC).where(NPC.session_id == sid, NPC.name == "小菱")
    )).scalar_one()
    revealed = json.loads(npc.revealed_json)
    assert revealed.get("name") is True
    assert revealed.get("description") is True
    assert revealed.get("purpose") is True
    # archetype not set in payload — must NOT be revealed
    assert "archetype" not in revealed or revealed.get("archetype") is False


async def test_npc_update_reveal_attribute_unlocks_fields(session_with_state):
    """v0.11: <npc_update name="..." reveal="purpose,archetype"/> on an
    existing NPC marks those fields revealed without changing their values."""
    s, sid = session_with_state
    # Step 1: minimal create — only name reveals.
    create = TagComplete(
        name="npc_update",
        content='{"name":"小菱"}',
    )
    await apply_tags(s, sid, current_turn=1, tags=[create])
    await s.commit()

    # Seed purpose/archetype directly so we can test reveal-only on existing values.
    npc = (await s.execute(
        select(NPC).where(NPC.session_id == sid, NPC.name == "小菱")
    )).scalar_one()
    npc.purpose = "寻找被抓走的同伴"
    npc.archetype = "外柔内刚的少女剑客"
    await s.commit()

    # Step 2: reveal-only update via attribute.
    reveal_tag = TagComplete(
        name="npc_update",
        attrs={"name": "小菱", "reveal": "purpose,archetype"},
        content="",
    )
    await apply_tags(s, sid, current_turn=2, tags=[reveal_tag])
    await s.commit()

    npc = (await s.execute(
        select(NPC).where(NPC.session_id == sid, NPC.name == "小菱")
    )).scalar_one()
    revealed = json.loads(npc.revealed_json)
    assert revealed.get("name") is True
    assert revealed.get("purpose") is True
    assert revealed.get("archetype") is True
    # Existing field values must be unchanged by the reveal-only update.
    assert npc.purpose == "寻找被抓走的同伴"
    assert npc.archetype == "外柔内刚的少女剑客"


async def test_npc_update_reveal_with_value_change_combined(session_with_state):
    """v0.11: a single update can both mutate a field AND reveal a different
    field via the reveal=... attribute. Auto-reveal also applies to any field
    whose value is being set in the same payload."""
    s, sid = session_with_state
    # Create with only name revealed.
    create = TagComplete(name="npc_update", content='{"name":"小菱"}')
    await apply_tags(s, sid, current_turn=1, tags=[create])
    await s.commit()

    # Update purpose AND ask reveal=affinity.
    update_tag = TagComplete(
        name="npc_update",
        attrs={"reveal": "affinity"},
        content='{"name":"小菱","purpose":"新动机"}',
    )
    await apply_tags(s, sid, current_turn=2, tags=[update_tag])
    await s.commit()

    npc = (await s.execute(
        select(NPC).where(NPC.session_id == sid, NPC.name == "小菱")
    )).scalar_one()
    revealed = json.loads(npc.revealed_json)
    assert npc.purpose == "新动机"
    assert revealed.get("purpose") is True  # auto-reveal: value just changed
    assert revealed.get("affinity") is True  # explicit reveal=affinity
    assert revealed.get("name") is True


async def test_npc_update_unknown_reveal_field_ignored(session_with_state):
    """v0.11: reveal names not in the whitelist (e.g. 'banana') are silently
    dropped. Recognised names in the same list still take effect."""
    s, sid = session_with_state
    create = TagComplete(name="npc_update", content='{"name":"小菱"}')
    await apply_tags(s, sid, current_turn=1, tags=[create])
    await s.commit()

    bad_tag = TagComplete(
        name="npc_update",
        attrs={"name": "小菱", "reveal": "banana,description"},
        content="",
    )
    await apply_tags(s, sid, current_turn=2, tags=[bad_tag])
    await s.commit()

    npc = (await s.execute(
        select(NPC).where(NPC.session_id == sid, NPC.name == "小菱")
    )).scalar_one()
    revealed = json.loads(npc.revealed_json)
    assert revealed.get("description") is True
    assert "banana" not in revealed


async def test_npc_update_reveal_only_no_npc_no_op(session_with_state):
    """v0.11: a reveal-only update against a non-existent NPC is a silent
    no-op — we don't fabricate a new NPC just to mark a field revealed."""
    s, sid = session_with_state
    tag = TagComplete(
        name="npc_update",
        attrs={"name": "幽灵", "reveal": "purpose"},
        content="",
    )
    await apply_tags(s, sid, current_turn=1, tags=[tag])
    await s.commit()

    rows = (await s.execute(
        select(NPC).where(NPC.session_id == sid, NPC.name == "幽灵")
    )).scalars().all()
    assert rows == []


async def test_apply_plot_event_resolution_closes_latest(session_with_state):
    s, sid = session_with_state
    open_tag = TagComplete(
        name="plot_event",
        attrs={"type": "hook_introduced", "importance": "2"},
        content="一个神秘人在酒吧角落注视 PC",
    )
    await apply_tags(s, sid, current_turn=1, tags=[open_tag])
    await s.commit()

    close_tag = TagComplete(
        name="plot_event",
        attrs={"type": "hook_resolved"},
        content="原来是地下情报贩子打听 PC 的义体来源",
    )
    await apply_tags(s, sid, current_turn=2, tags=[close_tag])
    await s.commit()

    threads = (await s.execute(
        select(PlotThread).where(PlotThread.session_id == sid)
    )).scalars().all()
    assert len(threads) == 1
    assert threads[0].status == "resolved"
    assert "情报贩子" in threads[0].resolution


# ---------------------------------------------------------------------------
# v0.12 plot_event dedup — when GM re-emits a near-identical new_quest /
# hook_introduced description, we collapse instead of fanning out rows.
# ---------------------------------------------------------------------------


async def test_plot_event_dedup_skips_similar(session_with_state):
    s, sid = session_with_state
    t1 = TagComplete(
        name="plot_event",
        attrs={"type": "new_quest", "importance": "2"},
        content="寻找老学者提到的接触者，获取秘密信息",
    )
    await apply_tags(s, sid, current_turn=1, tags=[t1])
    await s.commit()

    t2 = TagComplete(
        name="plot_event",
        attrs={"type": "new_quest", "importance": "2"},
        content="寻找老学者提到的接触者并获取关于公司的秘密",
    )
    await apply_tags(s, sid, current_turn=2, tags=[t2])
    await s.commit()

    threads = (await s.execute(
        select(PlotThread).where(PlotThread.session_id == sid)
    )).scalars().all()
    assert len(threads) == 1, f"expected 1 thread, got {len(threads)}"


async def test_plot_event_creates_distinct(session_with_state):
    s, sid = session_with_state
    t1 = TagComplete(
        name="plot_event",
        attrs={"type": "new_quest", "importance": "2"},
        content="调查重力场的异常波动",
    )
    t2 = TagComplete(
        name="plot_event",
        attrs={"type": "new_quest", "importance": "3"},
        content="为村中孩童寻找解药",
    )
    await apply_tags(s, sid, current_turn=1, tags=[t1])
    await apply_tags(s, sid, current_turn=2, tags=[t2])
    await s.commit()

    threads = (await s.execute(
        select(PlotThread).where(PlotThread.session_id == sid)
    )).scalars().all()
    assert len(threads) == 2


async def test_plot_event_doesnt_dedup_resolved(session_with_state):
    s, sid = session_with_state
    # Open + resolve a quest.
    t_open = TagComplete(
        name="plot_event",
        attrs={"type": "new_quest", "importance": "2"},
        content="调查 X 实验室的废弃记录",
    )
    await apply_tags(s, sid, current_turn=1, tags=[t_open])
    await s.commit()

    t_close = TagComplete(
        name="plot_event",
        attrs={"type": "hook_resolved"},
        content="发现实验室是公司的旧据点",
    )
    await apply_tags(s, sid, current_turn=2, tags=[t_close])
    await s.commit()

    # Re-emit a near-identical new_quest — the prior thread is resolved,
    # so this should create a fresh row, not collapse into the closed one.
    t_again = TagComplete(
        name="plot_event",
        attrs={"type": "new_quest", "importance": "2"},
        content="再次调查 X 实验室的废弃记录",
    )
    await apply_tags(s, sid, current_turn=5, tags=[t_again])
    await s.commit()

    threads = (await s.execute(
        select(PlotThread).where(PlotThread.session_id == sid)
    )).scalars().all()
    assert len(threads) == 2
    statuses = sorted(t.status for t in threads)
    assert statuses == ["active", "resolved"]


async def test_plot_event_dedup_applies_to_hook_introduced(session_with_state):
    s, sid = session_with_state
    t1 = TagComplete(
        name="plot_event",
        attrs={"type": "hook_introduced", "importance": "2"},
        content="一个戴风衣的男人在街角注视着 PC",
    )
    t2 = TagComplete(
        name="plot_event",
        attrs={"type": "hook_introduced", "importance": "2"},
        content="一个戴风衣的男人在街角偷偷注视着 PC",
    )
    await apply_tags(s, sid, current_turn=1, tags=[t1])
    await apply_tags(s, sid, current_turn=2, tags=[t2])
    await s.commit()

    threads = (await s.execute(
        select(PlotThread).where(PlotThread.session_id == sid)
    )).scalars().all()
    assert len(threads) == 1


# ---------------------------------------------------------------------------
# v0.13 plot_event dedup hardening — normalization + lower threshold + wider
# type coverage. v0.12 missed near-identical descriptions that differed only
# in whitespace / punctuation width / case.
# ---------------------------------------------------------------------------


async def test_plot_event_dedup_handles_whitespace_padding(session_with_state):
    """v0.13: Normalization must strip leading/trailing whitespace AND
    full-width spaces (U+3000) so visually-identical descriptions collapse."""
    s, sid = session_with_state
    t1 = TagComplete(
        name="plot_event",
        attrs={"type": "new_quest", "importance": "2"},
        content="你需要寻找接触者陈子轩",
    )
    # Same text but wrapped in full-width spaces + a stray ASCII space + tab
    t2 = TagComplete(
        name="plot_event",
        attrs={"type": "new_quest", "importance": "2"},
        content="　  你需要寻找接触者陈子轩  　\t",
    )
    await apply_tags(s, sid, current_turn=1, tags=[t1])
    await apply_tags(s, sid, current_turn=2, tags=[t2])
    await s.commit()

    threads = (await s.execute(
        select(PlotThread).where(PlotThread.session_id == sid)
    )).scalars().all()
    assert len(threads) == 1, f"expected 1 thread (whitespace-only diff), got {len(threads)}"


async def test_plot_event_dedup_covers_hook_introduced_vs_new_quest(session_with_state):
    """v0.13: A thread first opened as new_quest must still dedup when the
    GM later re-emits a near-identical description as hook_introduced
    (and vice versa). Cross-type wording-drift was a real production case."""
    s, sid = session_with_state
    t1 = TagComplete(
        name="plot_event",
        attrs={"type": "new_quest", "importance": "2"},
        content="找出谁在背后操纵公司董事会",
    )
    t2 = TagComplete(
        name="plot_event",
        attrs={"type": "hook_introduced", "importance": "2"},
        content="找出究竟是谁在背后操纵公司董事会",
    )
    await apply_tags(s, sid, current_turn=1, tags=[t1])
    await apply_tags(s, sid, current_turn=2, tags=[t2])
    await s.commit()

    threads = (await s.execute(
        select(PlotThread).where(PlotThread.session_id == sid)
    )).scalars().all()
    assert len(threads) == 1


async def test_plot_event_exact_duplicate_skipped(session_with_state):
    """v0.13: Two byte-identical descriptions short-circuit on the equality
    fast-path inside _is_duplicate_thread."""
    s, sid = session_with_state
    text = "去九龙黑街找黑医为小菱续命"
    for turn in (1, 2, 3):
        await apply_tags(
            s, sid, current_turn=turn,
            tags=[TagComplete(
                name="plot_event",
                attrs={"type": "new_quest", "importance": "2"},
                content=text,
            )],
        )
    await s.commit()

    threads = (await s.execute(
        select(PlotThread).where(PlotThread.session_id == sid)
    )).scalars().all()
    assert len(threads) == 1


async def test_plot_event_threshold_06_catches_paraphrase(session_with_state):
    """v0.13: The user's actual production case — two new_quest descriptions
    differing by ~6 chars of paraphrase. Raw SequenceMatcher ratio ~0.79.
    With v0.12's 0.7 threshold this was caught in synthetic cases; v0.13
    drops to 0.6 to add safety margin so similar near-misses also collapse."""
    s, sid = session_with_state
    t1 = TagComplete(
        name="plot_event",
        attrs={"type": "new_quest", "importance": "2"},
        content="你需要寻找老学者提到的接触者，并获取关于同源株式会社的秘密信息",
    )
    t2 = TagComplete(
        name="plot_event",
        attrs={"type": "new_quest", "importance": "2"},
        content="你需要寻找接触者陈子轩，并从他那里获取关于同源株式会社的秘密信息",
    )
    await apply_tags(s, sid, current_turn=1, tags=[t1])
    await apply_tags(s, sid, current_turn=2, tags=[t2])
    await s.commit()

    threads = (await s.execute(
        select(PlotThread).where(PlotThread.session_id == sid)
    )).scalars().all()
    assert len(threads) == 1, (
        f"expected paraphrased duplicate to collapse, got {len(threads)} threads: "
        + repr([t.description for t in threads])
    )


async def test_plot_event_dissimilar_creates_new(session_with_state):
    """v0.13: 0.6 threshold must NOT collapse genuinely distinct quests.
    'Investigate gravity anomaly' vs 'Find cure for child' have ratio 0.0
    after normalization — separate rows are correct."""
    s, sid = session_with_state
    t1 = TagComplete(
        name="plot_event",
        attrs={"type": "new_quest", "importance": "2"},
        content="调查重力场异常",
    )
    t2 = TagComplete(
        name="plot_event",
        attrs={"type": "new_quest", "importance": "3"},
        content="寻找解药救小菱",
    )
    await apply_tags(s, sid, current_turn=1, tags=[t1])
    await apply_tags(s, sid, current_turn=2, tags=[t2])
    await s.commit()

    threads = (await s.execute(
        select(PlotThread).where(PlotThread.session_id == sid)
    )).scalars().all()
    assert len(threads) == 2


async def test_plot_event_dedup_covers_major_event(session_with_state):
    """v0.13: dedup type coverage extended from new_quest/hook_introduced to
    also include major_event (and location_entered). GMs duplicate these too."""
    s, sid = session_with_state
    t1 = TagComplete(
        name="plot_event",
        attrs={"type": "major_event", "importance": "3"},
        content="霓虹猫酒馆爆炸，三人重伤",
    )
    t2 = TagComplete(
        name="plot_event",
        attrs={"type": "major_event", "importance": "3"},
        content="霓虹猫酒馆发生爆炸，三人重伤",
    )
    await apply_tags(s, sid, current_turn=1, tags=[t1])
    await apply_tags(s, sid, current_turn=2, tags=[t2])
    await s.commit()

    threads = (await s.execute(
        select(PlotThread).where(PlotThread.session_id == sid)
    )).scalars().all()
    assert len(threads) == 1


async def test_plot_event_dedup_covers_location_entered(session_with_state):
    """v0.13: same with location_entered."""
    s, sid = session_with_state
    t1 = TagComplete(
        name="plot_event",
        attrs={"type": "location_entered", "importance": "2"},
        content="进入九龙黑街地下集市",
    )
    t2 = TagComplete(
        name="plot_event",
        attrs={"type": "location_entered", "importance": "2"},
        content="进入了九龙黑街的地下集市",
    )
    await apply_tags(s, sid, current_turn=1, tags=[t1])
    await apply_tags(s, sid, current_turn=2, tags=[t2])
    await s.commit()

    threads = (await s.execute(
        select(PlotThread).where(PlotThread.session_id == sid)
    )).scalars().all()
    assert len(threads) == 1


async def test_plot_event_dedup_punctuation_width_normalized(session_with_state):
    """v0.13: CJK comma vs ASCII comma must not block dedup. Same text differing
    only by punctuation width should collapse on the exact-equality fast path."""
    s, sid = session_with_state
    t1 = TagComplete(
        name="plot_event",
        attrs={"type": "new_quest", "importance": "2"},
        content="找到老学者，问出真相",
    )
    t2 = TagComplete(
        name="plot_event",
        attrs={"type": "new_quest", "importance": "2"},
        content="找到老学者,问出真相",  # ASCII comma
    )
    await apply_tags(s, sid, current_turn=1, tags=[t1])
    await apply_tags(s, sid, current_turn=2, tags=[t2])
    await s.commit()

    threads = (await s.execute(
        select(PlotThread).where(PlotThread.session_id == sid)
    )).scalars().all()
    assert len(threads) == 1


# ---------------------------------------------------------------------------
# v0.1.0 task B — screenplay-driven tag handlers
# ---------------------------------------------------------------------------


async def _seed_screenplay(
    s: AsyncSession,
    sid: int,
    chapters: list[dict] | None = None,
    current_chapter: int = 1,
    completed: list[dict] | None = None,
) -> Screenplay:
    """Helper: seed an active Screenplay for the given session."""
    sp = Screenplay(
        session_id=sid,
        version=1,
        genre="悬疑",
        custom_prompt="",
        outline_md="测试大纲",
        chapters_json=json.dumps(chapters or [
            {"title": "第一章：序", "main_events": ["e0", "e1"], "optional_events": ["o0"]},
            {"title": "第二章：探", "main_events": ["e2"], "optional_events": []},
            {"title": "第三章：终", "main_events": ["e3"], "optional_events": []},
        ], ensure_ascii=False),
        main_characters_json="[]",
        ending_md="真相揭晓",
        opening_hook="",
        current_chapter=current_chapter,
        completed_events_json=json.dumps(completed or [], ensure_ascii=False),
        status="active",
    )
    s.add(sp)
    await s.flush()
    return sp


async def test_chapter_advance_increments_current_chapter(session_with_state):
    """<chapter_advance/> → current_chapter += 1 (3 chapters seeded → 1→2)."""
    s, sid = session_with_state
    sp = await _seed_screenplay(s, sid, current_chapter=1)
    await s.commit()

    tag = TagComplete(name="chapter_advance", attrs={}, content="")
    await apply_tags(s, sid, current_turn=5, tags=[tag])
    await s.commit()

    sp_reloaded = await s.get(Screenplay, sp.id)
    assert sp_reloaded.current_chapter == 2


async def test_chapter_advance_at_last_chapter_no_op(session_with_state):
    """At final chapter the advance must clamp — never go past total chapters.
    This protects against double-emit (GM emitting <chapter_advance/> twice
    in the final chapter would otherwise produce out-of-range indices in
    downstream readers like _build_key_facts)."""
    s, sid = session_with_state
    sp = await _seed_screenplay(s, sid, current_chapter=3)  # last of 3
    await s.commit()

    tag = TagComplete(name="chapter_advance", attrs={}, content="")
    await apply_tags(s, sid, current_turn=10, tags=[tag])
    await s.commit()

    sp_reloaded = await s.get(Screenplay, sp.id)
    assert sp_reloaded.current_chapter == 3  # still 3, not 4


async def test_event_complete_marks_event_done(session_with_state):
    """<event_complete chapter=1 event=0 type=main/> → completed_events_json
    grows by one record with int-typed chapter / event_idx."""
    s, sid = session_with_state
    sp = await _seed_screenplay(s, sid)
    await s.commit()

    tag = TagComplete(
        name="event_complete",
        attrs={"chapter": "1", "event": "0", "type": "main"},
        content="",
    )
    await apply_tags(s, sid, current_turn=2, tags=[tag])
    await s.commit()

    sp_reloaded = await s.get(Screenplay, sp.id)
    completed = json.loads(sp_reloaded.completed_events_json)
    assert completed == [{"chapter": 1, "event_idx": 0, "type": "main"}]


async def test_event_complete_idempotent(session_with_state):
    """Re-emitting the same chapter+event+type record must not create duplicates."""
    s, sid = session_with_state
    sp = await _seed_screenplay(s, sid)
    await s.commit()

    tag = TagComplete(
        name="event_complete",
        attrs={"chapter": "1", "event": "0", "type": "main"},
        content="",
    )
    await apply_tags(s, sid, current_turn=2, tags=[tag])
    await apply_tags(s, sid, current_turn=3, tags=[tag])
    await s.commit()

    sp_reloaded = await s.get(Screenplay, sp.id)
    completed = json.loads(sp_reloaded.completed_events_json)
    assert len(completed) == 1


async def test_plot_turn_major_creates_revision(session_with_state):
    """<plot_turn impact=major description=...> → ScreenplayRevision row added,
    capturing trigger_turn / description / before snapshot. The actual
    chapter rewrite is deferred to a later async outliner pass."""
    s, sid = session_with_state
    sp = await _seed_screenplay(s, sid)
    await s.commit()

    tag = TagComplete(
        name="plot_turn",
        attrs={"impact": "major", "description": "PC 杀了关键 NPC 陈子轩"},
        content="",
    )
    await apply_tags(s, sid, current_turn=7, tags=[tag])
    await s.commit()

    revs = (await s.execute(
        select(ScreenplayRevision).where(ScreenplayRevision.screenplay_id == sp.id)
    )).scalars().all()
    assert len(revs) == 1
    assert revs[0].trigger_turn == 7
    assert "陈子轩" in revs[0].trigger_description
    # before snapshot must equal current chapters_json (outliner fills after_*)
    assert revs[0].before_chapters_json == sp.chapters_json


async def test_plot_turn_minor_no_revision(session_with_state):
    """impact=minor is observational and must NOT create a revision row
    (only major triggers a rewrite chain)."""
    s, sid = session_with_state
    sp = await _seed_screenplay(s, sid)
    await s.commit()

    tag = TagComplete(
        name="plot_turn",
        attrs={"impact": "minor", "description": "PC 选了茶不是酒"},
        content="",
    )
    await apply_tags(s, sid, current_turn=4, tags=[tag])
    await s.commit()

    revs = (await s.execute(
        select(ScreenplayRevision).where(ScreenplayRevision.screenplay_id == sp.id)
    )).scalars().all()
    assert revs == []


async def test_ending_marks_screenplay_concluded(session_with_state):
    """<ending/> → status='concluded' + concluded_at populated."""
    s, sid = session_with_state
    sp = await _seed_screenplay(s, sid)
    await s.commit()

    tag = TagComplete(name="ending", attrs={}, content="")
    await apply_tags(s, sid, current_turn=12, tags=[tag])
    await s.commit()

    sp_reloaded = await s.get(Screenplay, sp.id)
    assert sp_reloaded.status == "concluded"
    assert sp_reloaded.concluded_at is not None
