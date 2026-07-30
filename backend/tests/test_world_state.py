"""Tests for GET /sessions/{id}/world_state endpoint."""
import json
import pytest
from httpx import ASGITransport, AsyncClient

from dzmm.db.base import init_db, get_engine, async_session
from dzmm.main import create_app


# ── fixtures ───────────────────────────────────────────────────────────────

@pytest.fixture
async def client(tmp_path):
    db_url = f"sqlite+aiosqlite:///{tmp_path}/t.db"
    engine = get_engine(db_url)
    await init_db(engine)
    sm = async_session(engine)
    app = create_app(sm)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    await engine.dispose()


async def _seed_minimal(sm) -> dict:
    """Seed one World, Character, ModelConfig, and two GameSessions:
    - sess_legacy: framework_id=None
    - sess_fw: framework_id pointing to a full WorldFramework
    Returns ids dict.
    """
    from dzmm.db.models import (
        World, Character, ModelConfig, Session as GameSession,
        WorldFramework, WorldLocation, WorldFaction, WorldNPCTemplate,
        WorldEvent, Campaign, SessionNpcState, SessionEventState,
        SessionCampaignState, SessionFactionState,
    )
    async with sm() as s:
        # prereqs
        world = World(name="test-world", style="dark", content_md="")
        s.add(world)
        await s.flush()

        char = Character(
            name="主角", world_id=world.id,
            profile_md="", base_stats_json="{}",
        )
        s.add(char)
        await s.flush()

        mcfg = ModelConfig(
            name="cfg", type="openai", model_name="gpt-4o",
            base_url="http://localhost",
        )
        s.add(mcfg)
        await s.flush()

        # legacy session (no framework)
        sess_legacy = GameSession(
            name="legacy", world_id=world.id, character_id=char.id,
            gm_model_config_id=mcfg.id, summarizer_model_config_id=mcfg.id,
        )
        s.add(sess_legacy)
        await s.flush()

        # framework
        fw = WorldFramework(name="开放世界", genre="fantasy", style="dark")
        s.add(fw)
        await s.flush()

        loc1 = WorldLocation(
            framework_id=fw.id, name="暗影港", description_md="港口城市",
            location_type="city",
            connections_json=json.dumps([{"target_id": 0, "direction": "north", "distance": 1, "travel_turns": 2}]),
            initial_state="normal",
        )
        loc2 = WorldLocation(
            framework_id=fw.id, name="迷雾森林", description_md="神秘森林",
            location_type="wilderness", connections_json="[]", initial_state="normal",
        )
        s.add_all([loc1, loc2])
        await s.flush()

        faction = WorldFaction(
            framework_id=fw.id, name="暗夜公会", description_md="地下势力",
            rival_factions_json="[]", ally_factions_json="[]",
            tension_rules_json=json.dumps({"passive_gain_per_turn": 1, "threshold_conflict": 80}),
        )
        s.add(faction)
        await s.flush()

        npc_revealed = WorldNPCTemplate(
            framework_id=fw.id, name="李影", gender="female", role="密探",
            description_md="", motivation="", home_location_id=loc1.id, faction_id=faction.id,
        )
        npc_hidden = WorldNPCTemplate(
            framework_id=fw.id, name="神秘人", gender="", role="未知",
            description_md="", motivation="", home_location_id=None,
        )
        s.add_all([npc_revealed, npc_hidden])
        await s.flush()

        ev1 = WorldEvent(
            framework_id=fw.id, name="港口起义", summary_md="暴乱",
            scope_type="location", scope_ref=str(loc1.id), importance=3,
            trigger_conditions_json="[]",
        )
        ev2 = WorldEvent(
            framework_id=fw.id, name="秘密任务", summary_md="隐藏任务",
            scope_type="global", scope_ref="", importance=2,
            trigger_conditions_json="[]",
        )
        s.add_all([ev1, ev2])
        await s.flush()

        campaign = Campaign(
            framework_id=fw.id, name="暗影战役",
            phases_json=json.dumps([
                {
                    "phase_id": 1,
                    "name": "第一章",
                    "description": "起源",
                    "prerequisite_phase_ids": [],
                    "key_event_ids": [ev1.id],
                    "required_count": 1,
                },
                {
                    "phase_id": 2,
                    "name": "第二章",
                    "description": "发展",
                    "prerequisite_phase_ids": [1],
                    "key_event_ids": [ev2.id],
                    "required_count": 1,
                },
            ]),
        )
        s.add(campaign)
        await s.flush()

        sess_fw = GameSession(
            name="fw-session", world_id=world.id, character_id=char.id,
            gm_model_config_id=mcfg.id, summarizer_model_config_id=mcfg.id,
            framework_id=fw.id,
        )
        s.add(sess_fw)
        await s.flush()

        # Reveal npc_revealed; npc_hidden has no state row
        npc_state = SessionNpcState(
            session_id=sess_fw.id, npc_template_id=npc_revealed.id,
            is_revealed=True, favor=10, current_location_id=loc1.id,
        )
        s.add(npc_state)

        # Trigger ev1 (visible), ev2 stays pending (hidden)
        ev_state = SessionEventState(
            session_id=sess_fw.id, event_id=ev1.id,
            status="triggered", triggered_turn=3,
        )
        s.add(ev_state)

        # Campaign state: current_phase=1, ev1 triggered
        camp_state = SessionCampaignState(
            session_id=sess_fw.id, current_phase_id=1,
            triggered_key_events_json=json.dumps([ev1.id]),
        )
        s.add(camp_state)

        # Faction state
        fs = SessionFactionState(
            session_id=sess_fw.id, faction_id=faction.id,
            tension=25, pc_reputation=-5,
        )
        s.add(fs)

        await s.commit()

        return {
            "legacy_id": sess_legacy.id,
            "fw_id": sess_fw.id,
            "fw_framework_id": fw.id,
            "loc1_id": loc1.id,
            "loc2_id": loc2.id,
            "faction_id": faction.id,
            "npc_revealed_id": npc_revealed.id,
            "npc_hidden_id": npc_hidden.id,
            "ev1_id": ev1.id,
            "ev2_id": ev2.id,
        }


# ── tests ──────────────────────────────────────────────────────────────────

async def test_legacy_session_returns_empty(client):
    """A session with framework_id=None should return all-empty arrays."""
    # We need to seed using the same engine used by the client fixture.
    # Use a fresh in-process seed via the API-seeded client is not possible;
    # instead we hit a non-existent endpoint with a real seed via direct DB.
    # Simplest: just hit a session that was created with no framework (via API).
    # Since we can't control session creation here easily, test via seeded db.
    # Skip and use a separate db-level test instead.
    pytest.skip("Covered by test_legacy_session_db below.")


async def test_legacy_session_db():
    """Session with framework_id=None → all empty."""
    from dzmm.db.base import init_db, get_engine, async_session
    from dzmm.main import create_app
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        db_url = f"sqlite+aiosqlite:///{tmp}/t.db"
        engine = get_engine(db_url)
        await init_db(engine)
        sm = async_session(engine)
        ids = await _seed_minimal(sm)
        app = create_app(sm)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get(f"/sessions/{ids['legacy_id']}/world_state")
        await engine.dispose()

    assert r.status_code == 200
    data = r.json()
    assert data["locations"] == []
    assert data["factions"] == []
    assert data["npcs"] == []
    assert data["events"] == []
    assert data["pc_location_id"] is None
    assert data["campaign"] is None


async def test_framework_session_locations_and_factions():
    """Populated framework session: locations include connections; factions include tension."""
    import tempfile
    from dzmm.db.base import get_engine, init_db, async_session
    from dzmm.main import create_app

    with tempfile.TemporaryDirectory() as tmp:
        engine = get_engine(f"sqlite+aiosqlite:///{tmp}/t.db")
        await init_db(engine)
        sm = async_session(engine)
        ids = await _seed_minimal(sm)
        app = create_app(sm)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get(f"/sessions/{ids['fw_id']}/world_state")
        await engine.dispose()

    assert r.status_code == 200
    data = r.json()

    # Locations
    assert len(data["locations"]) == 2
    loc1 = next(location for location in data["locations"] if location["id"] == ids["loc1_id"])
    assert loc1["name"] == "暗影港"
    assert isinstance(loc1["connections"], list)
    assert len(loc1["connections"]) == 1
    assert loc1["connections"][0]["direction"] == "north"

    # Factions
    assert len(data["factions"]) == 1
    fac = data["factions"][0]
    assert fac["tension"] == 25
    assert fac["pc_reputation"] == -5


async def test_revealed_vs_hidden_npc_filter():
    """Only NPCs with is_revealed=True appear; hidden NPC must be absent."""
    import tempfile
    from dzmm.db.base import get_engine, init_db, async_session
    from dzmm.main import create_app

    with tempfile.TemporaryDirectory() as tmp:
        engine = get_engine(f"sqlite+aiosqlite:///{tmp}/t.db")
        await init_db(engine)
        sm = async_session(engine)
        ids = await _seed_minimal(sm)
        app = create_app(sm)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get(f"/sessions/{ids['fw_id']}/world_state")
        await engine.dispose()

    data = r.json()
    npc_ids = [n["npc_template_id"] for n in data["npcs"]]
    assert ids["npc_revealed_id"] in npc_ids
    assert ids["npc_hidden_id"] not in npc_ids

    revealed_npc = next(n for n in data["npcs"] if n["npc_template_id"] == ids["npc_revealed_id"])
    assert revealed_npc["name"] == "李影"
    assert revealed_npc["favor"] == 10
    assert revealed_npc["is_revealed"] is True


async def test_events_pending_hidden_triggered_visible():
    """Pending events are hidden; triggered events appear."""
    import tempfile
    from dzmm.db.base import get_engine, init_db, async_session
    from dzmm.main import create_app

    with tempfile.TemporaryDirectory() as tmp:
        engine = get_engine(f"sqlite+aiosqlite:///{tmp}/t.db")
        await init_db(engine)
        sm = async_session(engine)
        ids = await _seed_minimal(sm)
        app = create_app(sm)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get(f"/sessions/{ids['fw_id']}/world_state")
        await engine.dispose()

    data = r.json()
    event_ids = [e["event_id"] for e in data["events"]]
    assert ids["ev1_id"] in event_ids     # triggered → visible
    assert ids["ev2_id"] not in event_ids  # pending → hidden

    ev1 = next(e for e in data["events"] if e["event_id"] == ids["ev1_id"])
    assert ev1["status"] == "triggered"
    assert ev1["triggered_turn"] == 3


async def test_campaign_phase_status_logic():
    """Phase 1 should be 'completed' (ev1 triggered), phase 2 'active' (prereq met)."""
    import tempfile
    from dzmm.db.base import get_engine, init_db, async_session
    from dzmm.main import create_app

    with tempfile.TemporaryDirectory() as tmp:
        engine = get_engine(f"sqlite+aiosqlite:///{tmp}/t.db")
        await init_db(engine)
        sm = async_session(engine)
        ids = await _seed_minimal(sm)
        app = create_app(sm)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get(f"/sessions/{ids['fw_id']}/world_state")
        await engine.dispose()

    data = r.json()
    camp = data["campaign"]
    assert camp is not None
    assert camp["campaign_name"] == "暗影战役"
    assert len(camp["phases"]) == 2

    phase1 = next(p for p in camp["phases"] if p["phase_id"] == 1)
    phase2 = next(p for p in camp["phases"] if p["phase_id"] == 2)

    assert phase1["status"] == "completed"
    assert phase1["triggered_count"] == 1
    assert phase1["required_count"] == 1
    assert len(phase1["triggered_key_events"]) == 1
    assert phase1["triggered_key_events"][0]["event_id"] == ids["ev1_id"]

    # Phase 2: prereq (phase 1) completed → active
    assert phase2["status"] == "active"
    assert phase2["triggered_count"] == 0


async def test_404_on_missing_session(client):
    """Non-existent session_id returns 404."""
    r = await client.get("/sessions/99999/world_state")
    assert r.status_code == 404
