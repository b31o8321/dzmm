"""Tests for v0.11 open-world event state machine.

Covers:
  - event_trigger tag: inserts SessionEventState row (pending→triggered)
  - event_trigger idempotency: re-emit same id → no duplicate, no status regression
  - event_complete (open-world): advances SessionEventState to completed
  - _apply_phase_advance: triggers_key_events + Campaign phase logic
  - Phase advance respects prerequisites
  - event_complete with chapter attr still uses screenplay mode (backward compat)
  - Unknown event_id is silently skipped
"""
import json
import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import select

from dzmm.db.base import Base
from dzmm.db import models  # noqa: F401  — registers all ORM classes
from dzmm.db.models import (
    Campaign,
    Character,
    ModelConfig,
    Screenplay,
    SessionCampaignState,
    SessionEventState,
    Session as GameSession,
    World,
    WorldEvent,
    WorldFramework,
)
from dzmm.parsing.events import TagComplete
from dzmm.service.state_apply import apply_tags


# ── shared fixture ────────────────────────────────────────────────────────────

@pytest.fixture
async def db():
    """In-memory SQLite with all tables created, yields AsyncSession."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = async_sessionmaker(engine, expire_on_commit=False)
    async with sm() as s:
        yield s
    await engine.dispose()


async def _make_world_session(s: AsyncSession, framework_id: int | None = None):
    """Create a minimal World + Character + ModelConfig + GameSession row."""
    world = World(name="Test World", content_md="x", style="dark")
    char = Character(world=world, name="Hero", profile_md="y",
                     base_stats_json='{"hp":20}')
    cfg = ModelConfig(name="m", type="ollama",
                      base_url="http://localhost:11434", model_name="qwen")
    s.add_all([world, char, cfg])
    await s.flush()
    sess = GameSession(
        name="run",
        world_id=world.id,
        character_id=char.id,
        gm_model_config_id=cfg.id,
        summarizer_model_config_id=cfg.id,
        framework_id=framework_id,
    )
    s.add(sess)
    await s.flush()
    return sess.id


async def _make_framework_and_event(s: AsyncSession, importance: int = 3):
    """Create a WorldFramework + one WorldEvent, return (framework_id, event_id)."""
    fw = WorldFramework(name="Fantasy World", genre="奇幻")
    s.add(fw)
    await s.flush()
    ev = WorldEvent(
        framework_id=fw.id,
        name="政变事件",
        summary_md="城堡政变",
        importance=importance,
    )
    s.add(ev)
    await s.flush()
    return fw.id, ev.id


# ── Task 1 + 2: event_trigger ─────────────────────────────────────────────────

async def test_event_trigger_inserts_state_row(db: AsyncSession):
    """<event_trigger event_id=N/> creates a SessionEventState row with status=triggered."""
    fw_id, ev_id = await _make_framework_and_event(db)
    sid = await _make_world_session(db, framework_id=fw_id)
    await db.commit()

    tag = TagComplete(name="event_trigger", attrs={"event_id": str(ev_id)})
    await apply_tags(db, sid, current_turn=3, tags=[tag])
    await db.commit()

    row = await db.get(SessionEventState, (sid, ev_id))
    assert row is not None
    assert row.status == "triggered"
    assert row.triggered_turn == 3


async def test_event_trigger_idempotent(db: AsyncSession):
    """Re-emitting the same event_trigger does not create a duplicate row or regress status."""
    fw_id, ev_id = await _make_framework_and_event(db)
    sid = await _make_world_session(db, framework_id=fw_id)
    await db.commit()

    tag = TagComplete(name="event_trigger", attrs={"event_id": str(ev_id)})
    # First emit
    await apply_tags(db, sid, current_turn=2, tags=[tag])
    await db.commit()

    # Second emit (same turn for simplicity)
    await apply_tags(db, sid, current_turn=5, tags=[tag])
    await db.commit()

    # Only one row
    result = await db.execute(
        select(SessionEventState).where(
            SessionEventState.session_id == sid,
            SessionEventState.event_id == ev_id,
        )
    )
    rows = result.scalars().all()
    assert len(rows) == 1
    # Status should not regress
    assert rows[0].status == "triggered"
    # triggered_turn stays from first emit
    assert rows[0].triggered_turn == 2


async def test_event_trigger_no_regression_from_completed(db: AsyncSession):
    """Re-emitting event_trigger after event is already completed does NOT regress to triggered."""
    fw_id, ev_id = await _make_framework_and_event(db)
    sid = await _make_world_session(db, framework_id=fw_id)
    # Pre-insert completed row
    completed_row = SessionEventState(
        session_id=sid,
        event_id=ev_id,
        status="completed",
        triggered_turn=1,
    )
    db.add(completed_row)
    await db.commit()

    tag = TagComplete(name="event_trigger", attrs={"event_id": str(ev_id)})
    await apply_tags(db, sid, current_turn=10, tags=[tag])
    await db.commit()

    row = await db.get(SessionEventState, (sid, ev_id))
    assert row.status == "completed"  # Must not regress


# ── Task 3: event_complete open-world ─────────────────────────────────────────

async def test_event_complete_open_world_rejects_pending_event(db: AsyncSession):
    """An event must be triggered in the story before it can be completed."""
    fw_id, ev_id = await _make_framework_and_event(db)
    sid = await _make_world_session(db, framework_id=fw_id)
    await db.commit()

    tag = TagComplete(name="event_complete", attrs={"event_id": str(ev_id)})
    await apply_tags(db, sid, current_turn=7, tags=[tag])
    await db.commit()

    row = await db.get(SessionEventState, (sid, ev_id))
    assert row is None


async def test_event_complete_open_world_idempotent(db: AsyncSession):
    """Re-emitting event_complete for the same event_id is a no-op (idempotent)."""
    fw_id, ev_id = await _make_framework_and_event(db)
    sid = await _make_world_session(db, framework_id=fw_id)
    await db.commit()

    tag = TagComplete(name="event_complete", attrs={"event_id": str(ev_id)})
    trigger = TagComplete(name="event_trigger", attrs={"event_id": str(ev_id)})
    await apply_tags(db, sid, current_turn=3, tags=[trigger])
    await db.commit()
    await apply_tags(db, sid, current_turn=4, tags=[tag])
    await db.commit()
    await apply_tags(db, sid, current_turn=9, tags=[tag])
    await db.commit()

    result = await db.execute(
        select(SessionEventState).where(
            SessionEventState.session_id == sid,
            SessionEventState.event_id == ev_id,
        )
    )
    rows = result.scalars().all()
    assert len(rows) == 1
    assert rows[0].status == "completed"


# ── Task 4: _apply_phase_advance ─────────────────────────────────────────────

async def _make_campaign(s: AsyncSession, fw_id: int, phases: list[dict]) -> int:
    """Create a Campaign for the framework and return campaign.id."""
    c = Campaign(
        framework_id=fw_id,
        name="主线战役",
        phases_json=json.dumps(phases, ensure_ascii=False),
    )
    s.add(c)
    await s.flush()
    return c.id


async def test_phase_advance_when_required_count_met(db: AsyncSession):
    """Completing a key event that meets required_count advances current_phase_id."""
    fw = WorldFramework(name="W", genre="奇幻")
    db.add(fw)
    await db.flush()

    ev1 = WorldEvent(framework_id=fw.id, name="事件A", summary_md="", importance=3)
    ev2 = WorldEvent(framework_id=fw.id, name="事件B", summary_md="", importance=3)
    db.add_all([ev1, ev2])
    await db.flush()

    phases = [
        {
            "phase_id": 1,
            "name": "序章",
            "description": "",
            "prerequisite_phase_ids": [],
            "key_event_ids": [ev1.id, ev2.id],
            "required_count": 1,  # 只需完成 1 个就算完成阶段
        },
        {
            "phase_id": 2,
            "name": "第二章",
            "description": "",
            "prerequisite_phase_ids": [1],
            "key_event_ids": [ev2.id],  # 需要完成 ev2 才能完成第二章
            "required_count": 1,
        },
    ]
    await _make_campaign(db, fw.id, phases)
    sid = await _make_world_session(db, framework_id=fw.id)
    await db.commit()

    # Complete ev1 → phase 1 required_count=1 met → phase 1 completed
    # Phase 2 prerequisite (phase 1) is now met and it has its own key event (ev2) not yet done
    # → next active phase = 2
    trigger = TagComplete(name="event_trigger", attrs={"event_id": str(ev1.id)})
    tag = TagComplete(name="event_complete", attrs={"event_id": str(ev1.id)})
    await apply_tags(db, sid, current_turn=4, tags=[trigger])
    await apply_tags(db, sid, current_turn=5, tags=[tag])
    await db.commit()

    state = await db.get(SessionCampaignState, sid)
    assert state is not None
    triggered = json.loads(state.triggered_key_events_json)
    assert ev1.id in triggered
    # Phase 1 is completed (1/2 key events done, required=1).
    # Phase 2 prerequisite met, not yet completed → current_phase_id = 2
    assert state.current_phase_id == 2


async def test_phase_advance_respects_prerequisites(db: AsyncSession):
    """A phase whose prerequisite_phase_ids are not yet completed is not selected."""
    fw = WorldFramework(name="W2", genre="现代")
    db.add(fw)
    await db.flush()

    ev1 = WorldEvent(framework_id=fw.id, name="A", summary_md="", importance=2)
    ev2 = WorldEvent(framework_id=fw.id, name="B", summary_md="", importance=2)
    ev3 = WorldEvent(framework_id=fw.id, name="C", summary_md="", importance=2)
    db.add_all([ev1, ev2, ev3])
    await db.flush()

    phases = [
        {
            "phase_id": 1,
            "name": "第一章",
            "description": "",
            "prerequisite_phase_ids": [],
            "key_event_ids": [ev1.id],
            "required_count": 1,
        },
        {
            "phase_id": 2,
            "name": "第二章（需要第一章完成）",
            "description": "",
            "prerequisite_phase_ids": [1],  # 依赖 phase 1
            "key_event_ids": [ev2.id],
            "required_count": 1,
        },
        {
            "phase_id": 3,
            "name": "第三章（需要第二章完成）",
            "description": "",
            "prerequisite_phase_ids": [2],  # 依赖 phase 2
            "key_event_ids": [ev3.id],
            "required_count": 1,
        },
    ]
    await _make_campaign(db, fw.id, phases)
    sid = await _make_world_session(db, framework_id=fw.id)
    await db.commit()

    # Complete ev2 (phase 2 key event) but phase 1 prerequisite is NOT completed
    trigger = TagComplete(name="event_trigger", attrs={"event_id": str(ev2.id)})
    tag = TagComplete(name="event_complete", attrs={"event_id": str(ev2.id)})
    await apply_tags(db, sid, current_turn=2, tags=[trigger])
    await apply_tags(db, sid, current_turn=3, tags=[tag])
    await db.commit()

    state = await db.get(SessionCampaignState, sid)
    # Phase 1 has no prerequisites and no key events completed → NOT completed
    # Phase 2 key event cannot complete before phase 1, so it remains triggered.
    # Phase 3 prerequisites not met either
    # The only phase with no unmet prerequisites is phase 1 (which isn't completed)
    # → current_phase_id should be 1 (the only unlocked phase)
    assert state is not None
    assert state.current_phase_id == 1
    ev_state = await db.get(SessionEventState, (sid, ev2.id))
    assert ev_state.status == "triggered"


async def test_phase_advance_no_campaign_is_noop(db: AsyncSession):
    """If no Campaign exists for the framework, _apply_phase_advance is a silent no-op."""
    fw = WorldFramework(name="NoCampaign", genre="奇幻")
    db.add(fw)
    await db.flush()
    ev = WorldEvent(framework_id=fw.id, name="事件X", summary_md="", importance=1)
    db.add(ev)
    await db.flush()
    # No Campaign added
    sid = await _make_world_session(db, framework_id=fw.id)
    await db.commit()

    trigger = TagComplete(name="event_trigger", attrs={"event_id": str(ev.id)})
    tag = TagComplete(name="event_complete", attrs={"event_id": str(ev.id)})
    await apply_tags(db, sid, current_turn=1, tags=[trigger, tag])
    await db.commit()

    # Row in SessionEventState should still be created
    row = await db.get(SessionEventState, (sid, ev.id))
    assert row is not None
    assert row.status == "completed"
    # But no SessionCampaignState row
    state = await db.get(SessionCampaignState, sid)
    assert state is None


# ── Task 6: backward compat — screenplay mode ─────────────────────────────────

async def test_framework_session_rejects_screenplay_event_complete(db: AsyncSession):
    """Framework and chapter-screenplay control modes are mutually exclusive."""
    fw_id, ev_id = await _make_framework_and_event(db)
    sid = await _make_world_session(db, framework_id=fw_id)

    # Add a screenplay so the screenplay path doesn't early-exit
    sp = Screenplay(
        session_id=sid,
        version=1,
        status="active",
        chapters_json=json.dumps([{"title": "Ch1"}, {"title": "Ch2"}]),
        completed_events_json="[]",
        current_chapter=1,
    )
    db.add(sp)
    await db.commit()

    tag = TagComplete(
        name="event_complete",
        attrs={"chapter": "1", "event": "2", "type": "main"},
    )
    await apply_tags(db, sid, current_turn=5, tags=[tag])
    await db.commit()

    # Framework mode ignores chapter-screenplay progress even if a stale row exists.
    await db.refresh(sp)
    completed = json.loads(sp.completed_events_json)
    assert completed == []

    # Open-world table must remain empty
    result = await db.execute(
        select(SessionEventState).where(SessionEventState.session_id == sid)
    )
    assert result.scalars().all() == []


# ── Task 7: unknown event_id ──────────────────────────────────────────────────

async def test_unknown_event_id_silent_skip(db: AsyncSession):
    """event_trigger or event_complete with a non-existent event_id is a silent no-op."""
    fw_id, _ = await _make_framework_and_event(db)
    sid = await _make_world_session(db, framework_id=fw_id)
    await db.commit()

    unknown_id = 99999
    for tag_name in ("event_trigger", "event_complete"):
        tag = TagComplete(name=tag_name, attrs={"event_id": str(unknown_id)})
        # Must not raise
        await apply_tags(db, sid, current_turn=1, tags=[tag])
        await db.commit()

    result = await db.execute(
        select(SessionEventState).where(SessionEventState.session_id == sid)
    )
    assert result.scalars().all() == []


async def test_event_trigger_no_framework_is_noop(db: AsyncSession):
    """event_trigger on a session with no framework_id is a silent no-op."""
    fw_id, ev_id = await _make_framework_and_event(db)
    # Session has NO framework_id
    sid = await _make_world_session(db, framework_id=None)
    await db.commit()

    tag = TagComplete(name="event_trigger", attrs={"event_id": str(ev_id)})
    await apply_tags(db, sid, current_turn=1, tags=[tag])
    await db.commit()

    result = await db.execute(
        select(SessionEventState).where(SessionEventState.session_id == sid)
    )
    assert result.scalars().all() == []


async def test_event_trigger_wrong_framework_silent_skip(db: AsyncSession):
    """event_trigger with an event from a different framework is silently skipped."""
    fw1 = WorldFramework(name="World1", genre="奇幻")
    fw2 = WorldFramework(name="World2", genre="科幻")
    db.add_all([fw1, fw2])
    await db.flush()

    # Event belongs to fw2, session uses fw1
    ev = WorldEvent(framework_id=fw2.id, name="外来事件", summary_md="", importance=2)
    db.add(ev)
    await db.flush()
    sid = await _make_world_session(db, framework_id=fw1.id)
    await db.commit()

    tag = TagComplete(name="event_trigger", attrs={"event_id": str(ev.id)})
    await apply_tags(db, sid, current_turn=1, tags=[tag])
    await db.commit()

    result = await db.execute(
        select(SessionEventState).where(SessionEventState.session_id == sid)
    )
    assert result.scalars().all() == []
