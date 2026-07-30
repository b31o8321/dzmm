"""Tests for engine/predicates.py and service/event_evaluator.py.

TDD: all tests are written BEFORE the implementation modules exist.
Run to confirm RED, then implement to make GREEN.
"""
import json
import logging
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.db.base import async_session, get_engine, init_db
from dzmm.db.models import (
    Character,
    CharState,
    ModelConfig,
    Session as GameSession,
    SessionEventState,
    SessionFactionState,
    SessionNpcState,
    World,
    WorldEvent,
    WorldFaction,
    WorldFramework,
    WorldNPCTemplate,
)
from dzmm.engine.predicates import evaluate, parse_predicate
from dzmm.service.event_evaluator import check_and_trigger_events


# ── DB fixture ────────────────────────────────────────────────────────────────

@pytest.fixture
async def db(tmp_path):
    engine = get_engine(f"sqlite+aiosqlite:///{tmp_path}/pred_test.db")
    await init_db(engine)
    async with async_session(engine)() as s:
        yield s
    await engine.dispose()


# ── Helper: build minimal session + related objects ───────────────────────────

async def _make_session(
    s: AsyncSession,
    *,
    hp: int = 20,
    sanity: int = 40,
    stamina: int = 30,
    doom_score: int = 0,
    inventory: list | None = None,
    skills: dict | None = None,
    pc_location_id: int | None = None,
) -> tuple[GameSession, Character, CharState]:
    """Create a minimal World / Character / CharState / Session row."""
    mc = ModelConfig(name="m", type="ollama", base_url="http://x", model_name="x")
    s.add(mc)
    await s.flush()

    world = World(name="W", content_md="x", style="realistic")
    s.add(world)
    await s.flush()

    char = Character(
        world_id=world.id, name="Hero", gender="male",
        profile_md="", base_stats_json="{}",
        inventory_json=json.dumps(inventory or []),
        skills_json=json.dumps(skills or {}),
    )
    s.add(char)
    await s.flush()

    settings: dict = {}
    if pc_location_id is not None:
        settings["pc_location_id"] = pc_location_id

    sess = GameSession(
        name="S", world_id=world.id, character_id=char.id,
        gm_model_config_id=mc.id, summarizer_model_config_id=mc.id,
        doom_score=doom_score,
        settings_json=json.dumps(settings),
    )
    s.add(sess)
    await s.flush()

    cs = CharState(
        session_id=sess.id,
        stats_json=json.dumps({"hp": hp, "sanity": sanity}),
        stamina=stamina,
    )
    s.add(cs)
    await s.flush()

    return sess, char, cs


async def _make_framework_and_event(
    s: AsyncSession, session_id: int,
    predicate_data: dict,
    status: str = "pending",
) -> tuple[WorldFramework, WorldEvent, SessionEventState]:
    fw = WorldFramework(name="FW", genre="fantasy")
    s.add(fw)
    await s.flush()

    event = WorldEvent(
        framework_id=fw.id,
        name="Test Event",
        trigger_conditions_json=json.dumps(predicate_data),
    )
    s.add(event)
    await s.flush()

    ev_state = SessionEventState(
        session_id=session_id,
        event_id=event.id,
        status=status,
    )
    s.add(ev_state)
    await s.flush()

    return fw, event, ev_state


# ─────────────────────────────────────────────────────────────────────────────
# Part A: predicate unit tests
# ─────────────────────────────────────────────────────────────────────────────

# A1. LocationReached: PC at location → True
async def test_location_reached_true(db):
    loc_id = 99
    sess, char, cs = await _make_session(db, pc_location_id=loc_id)
    pred = parse_predicate({"type": "location_reached", "location_id": loc_id})
    result = await evaluate(db, sess.id, pred)
    assert result is True


# A2. LocationReached: PC not at location → False
async def test_location_reached_false(db):
    sess, char, cs = await _make_session(db, pc_location_id=5)
    pred = parse_predicate({"type": "location_reached", "location_id": 42})
    result = await evaluate(db, sess.id, pred)
    assert result is False


# A3. StatThreshold: hp lte 5 with current hp 3 → True
async def test_stat_threshold_hp_lte_true(db):
    sess, char, cs = await _make_session(db, hp=3)
    pred = parse_predicate({"type": "stat_threshold", "stat": "hp", "op": "lte", "value": 5})
    result = await evaluate(db, sess.id, pred)
    assert result is True


# A4. StatThreshold: hp lte 5 with current hp 10 → False
async def test_stat_threshold_hp_lte_false(db):
    sess, char, cs = await _make_session(db, hp=10)
    pred = parse_predicate({"type": "stat_threshold", "stat": "hp", "op": "lte", "value": 5})
    result = await evaluate(db, sess.id, pred)
    assert result is False


# A5. StatThreshold: sanity gte 30 with current sanity 40 → True
async def test_stat_threshold_sanity_gte_true(db):
    sess, char, cs = await _make_session(db, sanity=40)
    pred = parse_predicate({"type": "stat_threshold", "stat": "sanity", "op": "gte", "value": 30})
    result = await evaluate(db, sess.id, pred)
    assert result is True


# A6. StatThreshold: doom_score gt 50 with doom_score=60 → True
async def test_stat_threshold_doom_true(db):
    sess, char, cs = await _make_session(db, doom_score=60)
    pred = parse_predicate({"type": "stat_threshold", "stat": "doom_score", "op": "gt", "value": 50})
    result = await evaluate(db, sess.id, pred)
    assert result is True


# A7. NpcState dead → True when NPC marked dead
async def test_npc_state_dead_true(db):
    fw = WorldFramework(name="FW2", genre="fantasy")
    db.add(fw)
    await db.flush()
    npc_tmpl = WorldNPCTemplate(framework_id=fw.id, name="Baron")
    db.add(npc_tmpl)
    await db.flush()

    sess, char, cs = await _make_session(db)
    npc_state = SessionNpcState(
        session_id=sess.id,
        npc_template_id=npc_tmpl.id,
        is_alive=False,
    )
    db.add(npc_state)
    await db.flush()

    pred = parse_predicate({"type": "npc_state", "npc_template_id": npc_tmpl.id, "state": "dead"})
    result = await evaluate(db, sess.id, pred)
    assert result is True


# A8. NpcState dead → False when NPC alive
async def test_npc_state_dead_false(db):
    fw = WorldFramework(name="FW3", genre="fantasy")
    db.add(fw)
    await db.flush()
    npc_tmpl = WorldNPCTemplate(framework_id=fw.id, name="Guard")
    db.add(npc_tmpl)
    await db.flush()

    sess, char, cs = await _make_session(db)
    npc_state = SessionNpcState(
        session_id=sess.id,
        npc_template_id=npc_tmpl.id,
        is_alive=True,
    )
    db.add(npc_state)
    await db.flush()

    pred = parse_predicate({"type": "npc_state", "npc_template_id": npc_tmpl.id, "state": "dead"})
    result = await evaluate(db, sess.id, pred)
    assert result is False


# A9. ItemOwned with qty 2, threshold min_qty=1 → True
async def test_item_owned_true(db):
    inventory = [{"name": "古老地图", "qty": 2, "item_type": "quest", "effects": []}]
    sess, char, cs = await _make_session(db, inventory=inventory)
    pred = parse_predicate({"type": "item_owned", "item_name": "古老地图", "min_qty": 1})
    result = await evaluate(db, sess.id, pred)
    assert result is True


# A10. ItemOwned: item not in inventory → False
async def test_item_owned_false(db):
    sess, char, cs = await _make_session(db, inventory=[])
    pred = parse_predicate({"type": "item_owned", "item_name": "神秘符文", "min_qty": 1})
    result = await evaluate(db, sess.id, pred)
    assert result is False


# A11. FactionTension gte 50 with tension 60 → True
async def test_faction_tension_gte_true(db):
    fw = WorldFramework(name="FW4", genre="fantasy")
    db.add(fw)
    await db.flush()
    faction = WorldFaction(framework_id=fw.id, name="Empire")
    db.add(faction)
    await db.flush()

    sess, char, cs = await _make_session(db)
    faction_state = SessionFactionState(
        session_id=sess.id,
        faction_id=faction.id,
        tension=60,
    )
    db.add(faction_state)
    await db.flush()

    pred = parse_predicate({"type": "faction_tension", "faction_id": faction.id, "op": "gte", "value": 50})
    result = await evaluate(db, sess.id, pred)
    assert result is True


# A12. FactionTension gte 70 with tension 60 → False
async def test_faction_tension_gte_false(db):
    fw = WorldFramework(name="FW5", genre="fantasy")
    db.add(fw)
    await db.flush()
    faction = WorldFaction(framework_id=fw.id, name="Rebel")
    db.add(faction)
    await db.flush()

    sess, char, cs = await _make_session(db)
    faction_state = SessionFactionState(
        session_id=sess.id,
        faction_id=faction.id,
        tension=60,
    )
    db.add(faction_state)
    await db.flush()

    pred = parse_predicate({"type": "faction_tension", "faction_id": faction.id, "op": "gte", "value": 70})
    result = await evaluate(db, sess.id, pred)
    assert result is False


# A13. CombinedAll: both True → True
async def test_combined_all_both_true(db):
    loc_id = 7
    sess, char, cs = await _make_session(db, hp=3, pc_location_id=loc_id)
    pred = parse_predicate({
        "type": "all",
        "children": [
            {"type": "location_reached", "location_id": loc_id},
            {"type": "stat_threshold", "stat": "hp", "op": "lte", "value": 5},
        ]
    })
    result = await evaluate(db, sess.id, pred)
    assert result is True


# A14. CombinedAll: one False → False
async def test_combined_all_one_false(db):
    loc_id = 8
    sess, char, cs = await _make_session(db, hp=20, pc_location_id=loc_id)
    pred = parse_predicate({
        "type": "all",
        "children": [
            {"type": "location_reached", "location_id": loc_id},
            {"type": "stat_threshold", "stat": "hp", "op": "lte", "value": 5},
        ]
    })
    result = await evaluate(db, sess.id, pred)
    assert result is False


# A15. CombinedAny: one True → True
async def test_combined_any_one_true(db):
    sess, char, cs = await _make_session(db, hp=20, pc_location_id=5)
    pred = parse_predicate({
        "type": "any",
        "children": [
            {"type": "location_reached", "location_id": 99},  # False
            {"type": "stat_threshold", "stat": "hp", "op": "gte", "value": 10},  # True
        ]
    })
    result = await evaluate(db, sess.id, pred)
    assert result is True


# A16. Malformed/unknown predicate type → False + warning logged
async def test_malformed_predicate_returns_false(db, caplog):
    from dzmm.engine.predicates import evaluate, parse_predicate
    sess, char, cs = await _make_session(db)
    # parse_predicate should handle unknown type gracefully
    with caplog.at_level(logging.WARNING):
        pred = parse_predicate({"type": "unknown_type_xyz", "value": 999})
    result = await evaluate(db, sess.id, pred)
    assert result is False


# ─────────────────────────────────────────────────────────────────────────────
# Part B: EventEvaluator (check_and_trigger_events)
# ─────────────────────────────────────────────────────────────────────────────

# B1. pending event whose predicate is True → status becomes "triggered"
async def test_check_triggers_pending_event(db):
    loc_id = 11
    sess, char, cs = await _make_session(db, pc_location_id=loc_id)
    fw, event, ev_state = await _make_framework_and_event(
        db, sess.id,
        predicate_data={"type": "location_reached", "location_id": loc_id},
        status="pending",
    )
    triggered = await check_and_trigger_events(db, sess.id, current_turn=5)
    assert event.id in triggered
    await db.refresh(ev_state)
    assert ev_state.status == "triggered"
    assert ev_state.triggered_turn == 5


# B2. pending event whose predicate is False → status unchanged
async def test_check_does_not_trigger_false_predicate(db):
    sess, char, cs = await _make_session(db, pc_location_id=1)
    fw, event, ev_state = await _make_framework_and_event(
        db, sess.id,
        predicate_data={"type": "location_reached", "location_id": 999},
        status="pending",
    )
    triggered = await check_and_trigger_events(db, sess.id, current_turn=3)
    assert event.id not in triggered
    await db.refresh(ev_state)
    assert ev_state.status == "pending"


# B3. already-triggered event is ignored
async def test_check_ignores_already_triggered(db):
    loc_id = 22
    sess, char, cs = await _make_session(db, pc_location_id=loc_id)
    fw, event, ev_state = await _make_framework_and_event(
        db, sess.id,
        predicate_data={"type": "location_reached", "location_id": loc_id},
        status="triggered",  # already triggered
    )
    triggered = await check_and_trigger_events(db, sess.id, current_turn=10)
    assert event.id not in triggered
    await db.refresh(ev_state)
    assert ev_state.status == "triggered"  # unchanged


# B4. check_and_trigger_events returns list of newly-fired ids
async def test_check_returns_list_of_fired_ids(db):
    loc_id = 33
    sess, char, cs = await _make_session(db, pc_location_id=loc_id, hp=2)

    fw = WorldFramework(name="FW_multi", genre="fantasy")
    db.add(fw)
    await db.flush()

    event1 = WorldEvent(
        framework_id=fw.id, name="E1",
        trigger_conditions_json=json.dumps({"type": "location_reached", "location_id": loc_id}),
    )
    event2 = WorldEvent(
        framework_id=fw.id, name="E2",
        trigger_conditions_json=json.dumps({"type": "stat_threshold", "stat": "hp", "op": "lte", "value": 5}),
    )
    event3 = WorldEvent(
        framework_id=fw.id, name="E3",
        trigger_conditions_json=json.dumps({"type": "location_reached", "location_id": 9999}),
    )
    db.add_all([event1, event2, event3])
    await db.flush()

    for ev in [event1, event2, event3]:
        db.add(SessionEventState(session_id=sess.id, event_id=ev.id, status="pending"))
    await db.flush()

    triggered = await check_and_trigger_events(db, sess.id, current_turn=1)
    assert event1.id in triggered
    assert event2.id in triggered
    assert event3.id not in triggered
    assert len(triggered) == 2


# B5. malformed trigger_conditions_json is inert (old free-text wraps as manual_trigger)
async def test_check_malformed_predicate_is_inert(db):
    sess, char, cs = await _make_session(db)
    fw, event, ev_state = await _make_framework_and_event(
        db, sess.id,
        predicate_data="this is old free-text criteria, not valid JSON dict",
        status="pending",
    )
    # Overwrite trigger_conditions_json with raw free-text (not a dict)
    event.trigger_conditions_json = "PC reaches the old mill"
    await db.flush()

    triggered = await check_and_trigger_events(db, sess.id, current_turn=7)
    assert event.id not in triggered
    await db.refresh(ev_state)
    assert ev_state.status == "pending"
