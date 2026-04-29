import json
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.db.base import init_db, get_engine, async_session
from dzmm.db.models import (
    Character, CharState, Era, ModelConfig, NPC, PCGoal, PlotThread, Session as GameSession, World,
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
