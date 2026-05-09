# Open World Framework — Plan A: DB Models

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add all new SQLAlchemy ORM models for the open-world framework (WorldFramework, WorldLocation, WorldFaction, WorldNPCTemplate, WorldEvent, Campaign, and five session-level state tables) plus inline migrations to wire them into the existing DB init system.

**Architecture:** New tables are added to `backend/src/dzmm/db/models.py` and auto-created via `Base.metadata.create_all`. The single new column on `sessions` (`framework_id`) uses the existing `_VNN_MIGRATIONS` / `_add_missing_columns_sync` pattern in `base.py`. No Alembic — all migrations are inline. Session-level state tables link by `(session_id, entity_id)` composite keys.

**Tech Stack:** Python 3.11, SQLAlchemy 2.x async ORM, SQLite (dev), pytest-asyncio

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `backend/src/dzmm/db/models.py` | Modify | Add 9 new ORM classes |
| `backend/src/dzmm/db/base.py` | Modify | Add `_V044_MIGRATIONS` for `sessions.framework_id` |
| `backend/tests/test_open_world_models.py` | Create | Model instantiation + migration idempotency tests |

---

### Task 1: WorldFramework + WorldLocation models

**Files:**
- Modify: `backend/src/dzmm/db/models.py` (append after `AgentMessage`)
- Create: `backend/tests/test_open_world_models.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_open_world_models.py
import json
import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from dzmm.db.base import Base
from dzmm.db import models  # noqa: F401 — registers all ORM classes


@pytest.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = async_sessionmaker(engine, expire_on_commit=False)
    async with sm() as s:
        yield s
    await engine.dispose()


async def test_world_framework_and_location(db_session: AsyncSession):
    from dzmm.db.models import WorldFramework, WorldLocation
    fw = WorldFramework(name="测试世界", genre="奇幻", style="dark_fantasy")
    db_session.add(fw)
    await db_session.flush()

    loc = WorldLocation(
        framework_id=fw.id,
        name="暗影港",
        description_md="一座阴暗的港口城市。",
        location_type="city",
        connections_json=json.dumps([{"target_id": 2, "direction": "north", "distance": 1, "travel_turns": 1}]),
    )
    db_session.add(loc)
    await db_session.commit()

    fetched = await db_session.get(WorldLocation, loc.id)
    assert fetched is not None
    assert fetched.framework_id == fw.id
    conns = json.loads(fetched.connections_json)
    assert conns[0]["direction"] == "north"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && uv run pytest tests/test_open_world_models.py::test_world_framework_and_location -v
```

Expected: `FAILED` — `ImportError: cannot import name 'WorldFramework'`

- [ ] **Step 3: Add WorldFramework and WorldLocation to models.py**

Append after the `AgentMessage` class (end of file):

```python
# ── 开放世界框架（WorldFramework 层） ────────────────────
# WorldFramework 是只读模板；Session 在其上叠加运行时状态覆盖层。
# 同一 WorldFramework 可被多个 Session 引用（多存档共享世界）。

class WorldFramework(Base):
    __tablename__ = "world_frameworks"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    genre: Mapped[str] = mapped_column(String(60), default="")
    style: Mapped[str] = mapped_column(String(60), default="")
    description_md: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None)
    )


class WorldLocation(Base):
    __tablename__ = "world_locations"
    id: Mapped[int] = mapped_column(primary_key=True)
    framework_id: Mapped[int] = mapped_column(ForeignKey("world_frameworks.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    description_md: Mapped[str] = mapped_column(Text, default="")
    # city / dungeon / wilderness / landmark
    location_type: Mapped[str] = mapped_column(String(40), default="city")
    # JSON list: [{target_id, direction, distance, travel_turns}]
    # distance: 0=same, 1=adjacent, 2=nearby, 3+=far
    connections_json: Mapped[str] = mapped_column(Text, default="[]")
    controlling_faction_id: Mapped[int | None] = mapped_column(
        ForeignKey("world_factions.id"), nullable=True
    )
    # normal / damaged / destroyed
    initial_state: Mapped[str] = mapped_column(String(20), default="normal")
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd backend && uv run pytest tests/test_open_world_models.py::test_world_framework_and_location -v
```

Expected: `PASSED`

- [ ] **Step 5: Commit**

```bash
git add backend/src/dzmm/db/models.py backend/tests/test_open_world_models.py
git commit -m "feat(db): add WorldFramework + WorldLocation ORM models"
```

---

### Task 2: WorldFaction + WorldNPCTemplate models

**Files:**
- Modify: `backend/src/dzmm/db/models.py`
- Modify: `backend/tests/test_open_world_models.py`

Note: `WorldLocation.controlling_faction_id` already references `world_factions.id` — SQLite defers FK checks so the table definition order in models.py doesn't matter at runtime, but `WorldFaction` must be added so the table exists before tests run.

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_open_world_models.py`:

```python
async def test_world_faction_and_npc_template(db_session: AsyncSession):
    from dzmm.db.models import WorldFramework, WorldFaction, WorldNPCTemplate
    fw = WorldFramework(name="世界B", genre="现代悬疑")
    db_session.add(fw)
    await db_session.flush()

    faction = WorldFaction(
        framework_id=fw.id,
        name="暗夜公会",
        description_md="控制城市地下经济的秘密组织。",
        rival_factions_json=json.dumps([]),
        ally_factions_json=json.dumps([]),
        tension_rules_json=json.dumps({"passive_gain_per_turn": 1, "threshold_conflict": 80}),
    )
    db_session.add(faction)
    await db_session.flush()

    npc = WorldNPCTemplate(
        framework_id=fw.id,
        name="李影",
        gender="female",
        role="公会密探",
        description_md="冷静、多疑，善于伪装。",
        motivation="保护组织机密",
        home_location_id=None,
        faction_id=faction.id,
    )
    db_session.add(npc)
    await db_session.commit()

    fetched = await db_session.get(WorldNPCTemplate, npc.id)
    assert fetched.faction_id == faction.id
    assert fetched.gender == "female"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && uv run pytest tests/test_open_world_models.py::test_world_faction_and_npc_template -v
```

Expected: `FAILED` — `ImportError: cannot import name 'WorldFaction'`

- [ ] **Step 3: Add WorldFaction and WorldNPCTemplate to models.py**

Append after `WorldLocation`:

```python
class WorldFaction(Base):
    __tablename__ = "world_factions"
    id: Mapped[int] = mapped_column(primary_key=True)
    framework_id: Mapped[int] = mapped_column(ForeignKey("world_frameworks.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    description_md: Mapped[str] = mapped_column(Text, default="")
    # JSON list of faction IDs
    rival_factions_json: Mapped[str] = mapped_column(Text, default="[]")
    ally_factions_json: Mapped[str] = mapped_column(Text, default="[]")
    # {"passive_gain_per_turn": N, "threshold_conflict": N}
    tension_rules_json: Mapped[str] = mapped_column(Text, default="{}")


class WorldNPCTemplate(Base):
    __tablename__ = "world_npc_templates"
    id: Mapped[int] = mapped_column(primary_key=True)
    framework_id: Mapped[int] = mapped_column(ForeignKey("world_frameworks.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    # "male" | "female" | "" (unset)
    gender: Mapped[str] = mapped_column(String(10), default="")
    role: Mapped[str] = mapped_column(String(120), default="")
    description_md: Mapped[str] = mapped_column(Text, default="")
    motivation: Mapped[str] = mapped_column(Text, default="")
    home_location_id: Mapped[int | None] = mapped_column(
        ForeignKey("world_locations.id"), nullable=True
    )
    faction_id: Mapped[int | None] = mapped_column(
        ForeignKey("world_factions.id"), nullable=True
    )
    avatar_asset_id: Mapped[int | None] = mapped_column(
        ForeignKey("assets.id"), nullable=True
    )
    # contact thresholds for NPC proactive initiative
    contact_favor_threshold: Mapped[int] = mapped_column(default=70)
    contact_cooldown_turns: Mapped[int] = mapped_column(default=10)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd backend && uv run pytest tests/test_open_world_models.py::test_world_faction_and_npc_template -v
```

Expected: `PASSED`

- [ ] **Step 5: Commit**

```bash
git add backend/src/dzmm/db/models.py backend/tests/test_open_world_models.py
git commit -m "feat(db): add WorldFaction + WorldNPCTemplate ORM models"
```

---

### Task 3: WorldEvent + Campaign models

**Files:**
- Modify: `backend/src/dzmm/db/models.py`
- Modify: `backend/tests/test_open_world_models.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_open_world_models.py`:

```python
async def test_world_event_and_campaign(db_session: AsyncSession):
    from dzmm.db.models import WorldFramework, WorldEvent, Campaign
    fw = WorldFramework(name="世界C", genre="史诗奇幻")
    db_session.add(fw)
    await db_session.flush()

    event = WorldEvent(
        framework_id=fw.id,
        name="暗影港谋杀案",
        summary_md="港口发现神秘尸体，暗夜公会开始暗中调查。",
        scope_type="location",
        scope_ref="1",
        importance=3,
        trigger_conditions_json=json.dumps([
            {"type": "location", "value": 1},
            {"type": "stat_gte", "stat": "智识", "value": 3},
        ]),
        is_repeatable=False,
        cooldown_turns=0,
    )
    db_session.add(event)

    campaign = Campaign(
        framework_id=fw.id,
        name="暗影之战",
        phases_json=json.dumps([
            {
                "phase_id": 1,
                "name": "序章",
                "description": "调查谋杀案，建立人脉。",
                "prerequisite_phase_ids": [],
                "key_event_ids": [1, 2, 3],
                "required_count": 2,
            }
        ]),
    )
    db_session.add(campaign)
    await db_session.commit()

    fetched_event = await db_session.get(WorldEvent, event.id)
    assert fetched_event.importance == 3
    conds = json.loads(fetched_event.trigger_conditions_json)
    assert conds[0]["type"] == "location"

    fetched_campaign = await db_session.get(Campaign, campaign.id)
    phases = json.loads(fetched_campaign.phases_json)
    assert phases[0]["required_count"] == 2
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && uv run pytest tests/test_open_world_models.py::test_world_event_and_campaign -v
```

Expected: `FAILED` — `ImportError: cannot import name 'WorldEvent'`

- [ ] **Step 3: Add WorldEvent and Campaign to models.py**

Append after `WorldNPCTemplate`:

```python
class WorldEvent(Base):
    __tablename__ = "world_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    framework_id: Mapped[int] = mapped_column(ForeignKey("world_frameworks.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    summary_md: Mapped[str] = mapped_column(Text, default="")
    # "location" | "faction" | "global"
    scope_type: Mapped[str] = mapped_column(String(20), default="location")
    # stringified location_id or faction_id, or "" for global
    scope_ref: Mapped[str] = mapped_column(String(40), default="")
    # 1=minor … 5=critical; controls Director priority + rumor threshold (≥3)
    importance: Mapped[int] = mapped_column(default=2)
    # AND-logic condition list JSON (see spec Section 1 for schema)
    trigger_conditions_json: Mapped[str] = mapped_column(Text, default="[]")
    is_repeatable: Mapped[bool] = mapped_column(default=False)
    cooldown_turns: Mapped[int] = mapped_column(default=0)


class Campaign(Base):
    __tablename__ = "campaigns"
    id: Mapped[int] = mapped_column(primary_key=True)
    # one Campaign per WorldFramework (nullable: framework can have no campaign)
    framework_id: Mapped[int] = mapped_column(
        ForeignKey("world_frameworks.id"), unique=True
    )
    name: Mapped[str] = mapped_column(String(120))
    # JSON list of phase dicts:
    # [{phase_id, name, description, prerequisite_phase_ids, key_event_ids, required_count}]
    phases_json: Mapped[str] = mapped_column(Text, default="[]")
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd backend && uv run pytest tests/test_open_world_models.py::test_world_event_and_campaign -v
```

Expected: `PASSED`

- [ ] **Step 5: Commit**

```bash
git add backend/src/dzmm/db/models.py backend/tests/test_open_world_models.py
git commit -m "feat(db): add WorldEvent + Campaign ORM models"
```

---

### Task 4: Session-level state models (5 tables)

**Files:**
- Modify: `backend/src/dzmm/db/models.py`
- Modify: `backend/tests/test_open_world_models.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_open_world_models.py`:

```python
async def test_session_state_tables(db_session: AsyncSession):
    from dzmm.db.models import (
        WorldFramework, WorldLocation, WorldFaction, WorldNPCTemplate,
        WorldEvent, Campaign,
        SessionLocationState, SessionNpcState, SessionEventState,
        SessionFactionState, SessionCampaignState,
    )
    # Create minimal parent objects
    fw = WorldFramework(name="世界D")
    db_session.add(fw)
    await db_session.flush()

    loc = WorldLocation(framework_id=fw.id, name="城市A", location_type="city")
    faction = WorldFaction(framework_id=fw.id, name="教团")
    npc_t = WorldNPCTemplate(framework_id=fw.id, name="守门人")
    event = WorldEvent(framework_id=fw.id, name="事件X", importance=2)
    db_session.add_all([loc, faction, npc_t, event])
    await db_session.flush()

    SESSION_ID = 42  # pretend session exists

    loc_state = SessionLocationState(
        session_id=SESSION_ID, location_id=loc.id, status="damaged"
    )
    npc_state = SessionNpcState(
        session_id=SESSION_ID, npc_template_id=npc_t.id,
        current_location_id=loc.id, favor=55, is_companion=True,
        is_revealed=True, last_contact_turn=0,
    )
    event_state = SessionEventState(
        session_id=SESSION_ID, event_id=event.id,
        status="triggered", triggered_turn=5,
    )
    faction_state = SessionFactionState(
        session_id=SESSION_ID, faction_id=faction.id,
        tension=30, pc_reputation=10,
    )
    campaign_state = SessionCampaignState(
        session_id=SESSION_ID, current_phase_id=1,
        triggered_key_events_json=json.dumps([]),
    )
    db_session.add_all([loc_state, npc_state, event_state, faction_state, campaign_state])
    await db_session.commit()

    fetched_npc = await db_session.get(SessionNpcState, (SESSION_ID, npc_t.id))
    assert fetched_npc.is_companion is True
    assert fetched_npc.favor == 55

    fetched_event = await db_session.get(SessionEventState, (SESSION_ID, event.id))
    assert fetched_event.status == "triggered"

    fetched_loc = await db_session.get(SessionLocationState, (SESSION_ID, loc.id))
    assert fetched_loc.status == "damaged"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && uv run pytest tests/test_open_world_models.py::test_session_state_tables -v
```

Expected: `FAILED` — `ImportError: cannot import name 'SessionLocationState'`

- [ ] **Step 3: Add the 5 session-state tables to models.py**

Append after `Campaign`:

```python
# ── Session-level 世界状态覆盖层 ─────────────────────────
# WorldFramework 是不可变模板；Session 通过这些表存储运行时覆盖。

class SessionLocationState(Base):
    __tablename__ = "session_location_states"
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"), primary_key=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("world_locations.id"), primary_key=True)
    # "normal" | "damaged" | "destroyed"
    status: Mapped[str] = mapped_column(String(20), default="normal")
    notes: Mapped[str] = mapped_column(Text, default="")


class SessionNpcState(Base):
    __tablename__ = "session_npc_states"
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"), primary_key=True)
    npc_template_id: Mapped[int] = mapped_column(
        ForeignKey("world_npc_templates.id"), primary_key=True
    )
    current_location_id: Mapped[int | None] = mapped_column(
        ForeignKey("world_locations.id"), nullable=True
    )
    favor: Mapped[int] = mapped_column(default=0)
    is_companion: Mapped[bool] = mapped_column(default=False)
    is_revealed: Mapped[bool] = mapped_column(default=False)
    is_alive: Mapped[bool] = mapped_column(default=True)
    last_contact_turn: Mapped[int] = mapped_column(default=0)


class SessionEventState(Base):
    __tablename__ = "session_event_states"
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"), primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("world_events.id"), primary_key=True)
    # "pending" | "triggered" | "completed"
    status: Mapped[str] = mapped_column(String(20), default="pending")
    triggered_turn: Mapped[int] = mapped_column(default=0)
    # GM may override the standard summary for this specific session
    summary_override: Mapped[str | None] = mapped_column(Text, nullable=True)
    # track rumor delivery to avoid re-delivery
    rumor_delivered: Mapped[bool] = mapped_column(default=False)
    rumor_delivered_turn: Mapped[int] = mapped_column(default=0)


class SessionFactionState(Base):
    __tablename__ = "session_faction_states"
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"), primary_key=True)
    faction_id: Mapped[int] = mapped_column(ForeignKey("world_factions.id"), primary_key=True)
    # tension accumulates passively; triggers conflict event at threshold
    tension: Mapped[int] = mapped_column(default=0)
    pc_reputation: Mapped[int] = mapped_column(default=0)
    is_active: Mapped[bool] = mapped_column(default=True)


class SessionCampaignState(Base):
    __tablename__ = "session_campaign_states"
    # one row per session (session_id is PK)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"), primary_key=True)
    current_phase_id: Mapped[int | None] = mapped_column(nullable=True)
    # JSON list of triggered key event IDs in current phase
    triggered_key_events_json: Mapped[str] = mapped_column(Text, default="[]")
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd backend && uv run pytest tests/test_open_world_models.py::test_session_state_tables -v
```

Expected: `PASSED`

- [ ] **Step 5: Commit**

```bash
git add backend/src/dzmm/db/models.py backend/tests/test_open_world_models.py
git commit -m "feat(db): add 5 session-level world state ORM tables"
```

---

### Task 5: Add framework_id to Session + register migration

**Files:**
- Modify: `backend/src/dzmm/db/models.py` (Session class)
- Modify: `backend/src/dzmm/db/base.py` (add `_V044_MIGRATIONS`)
- Modify: `backend/tests/test_open_world_models.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_open_world_models.py`:

```python
async def test_session_has_framework_id(db_session: AsyncSession):
    from dzmm.db.models import WorldFramework
    fw = WorldFramework(name="世界E")
    db_session.add(fw)
    await db_session.flush()

    # Confirm the column exists on the Session table via a raw SQL check
    result = await db_session.execute(
        __import__("sqlalchemy").text("PRAGMA table_info(sessions)")
    )
    columns = {row[1] for row in result.fetchall()}
    assert "framework_id" in columns, "sessions table missing framework_id column"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && uv run pytest tests/test_open_world_models.py::test_session_has_framework_id -v
```

Expected: `FAILED` — `AssertionError: sessions table missing framework_id column`

- [ ] **Step 3: Add framework_id to Session model in models.py**

Find the `Session` class and add `framework_id` after `screenplay_id`:

```python
# In Session class, after:
#   screenplay_id: Mapped[int | None] = mapped_column(ForeignKey("screenplays.id"), nullable=True)
# Add:
    framework_id: Mapped[int | None] = mapped_column(
        ForeignKey("world_frameworks.id"), nullable=True, default=None
    )
```

- [ ] **Step 4: Add _V044_MIGRATIONS to base.py**

In `backend/src/dzmm/db/base.py`, after `_V043_MIGRATIONS`:

```python
_V044_MIGRATIONS: dict[str, list[tuple[str, str]]] = {
    "sessions": [
        ("framework_id", "framework_id INTEGER REFERENCES world_frameworks(id)"),
    ],
}
```

Then in the `init_db` function, after the `_V043_MIGRATIONS` loop:

```python
        for table, cols in _V044_MIGRATIONS.items():
            await conn.run_sync(_add_missing_columns_sync, table, cols)
```

- [ ] **Step 5: Run test to verify it passes**

```bash
cd backend && uv run pytest tests/test_open_world_models.py::test_session_has_framework_id -v
```

Expected: `PASSED`

- [ ] **Step 6: Run the full test suite to check for regressions**

```bash
cd backend && uv run pytest tests/ -v --tb=short 2>&1 | tail -30
```

Expected: All existing tests pass; new tests pass.

- [ ] **Step 7: Commit**

```bash
git add backend/src/dzmm/db/models.py backend/src/dzmm/db/base.py backend/tests/test_open_world_models.py
git commit -m "feat(db): add framework_id to Session + _V044 migration + full test coverage"
```

---

## What comes next

After Plan A is complete and merged:

- **Plan B** — Director Agent: spatial event scoring, rumor delivery, NPC proactive contact
- **Plan C** — Wizard API: 8-step LLM generation endpoints producing a `WorldFramework`
- **Plan D** — Frontend: WorldMapPanel, LocationDetailPopup, CampaignProgressPanel, Wizard UI updates
