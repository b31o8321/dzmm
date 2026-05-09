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
