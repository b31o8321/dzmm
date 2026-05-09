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
