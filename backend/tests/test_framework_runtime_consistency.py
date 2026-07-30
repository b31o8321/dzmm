import json

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from dzmm.api.routes_sessions._common import _to_out
from dzmm.api.routes_sessions.base import _initialize_framework_runtime
from dzmm.db import models  # noqa: F401
from dzmm.db.base import Base
from dzmm.db.models import (
    Campaign,
    Character,
    Location,
    LocationEdge,
    ModelConfig,
    Session as GameSession,
    SessionCampaignState,
    SessionEventState,
    SessionFactionState,
    SessionNpcState,
    World,
    WorldEvent,
    WorldFaction,
    WorldFramework,
    WorldLocation,
    WorldNPCTemplate,
)
from dzmm.parsing.events import TagComplete
from dzmm.service.game import _build_key_facts, _should_auto_generate_screenplay
from dzmm.service.state_apply import apply_tags


@pytest.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


async def _seed_framework_session(db: AsyncSession):
    world = World(name="W", content_md="world")
    char = Character(
        world=world, name="PC", profile_md="profile", base_stats_json='{"hp": 20}',
    )
    cfg = ModelConfig(
        name="local", type="ollama", base_url="http://localhost:11434", model_name="qwen",
    )
    fw = WorldFramework(name="FW", genre="悬疑")
    db.add_all([world, char, cfg, fw])
    await db.flush()
    start = WorldLocation(
        framework_id=fw.id, name="教堂", description_md="阴暗教堂", connections_json="[]",
    )
    other = WorldLocation(
        framework_id=fw.id, name="广场", description_md="中央广场",
        connections_json="[]", is_start=True,
    )
    faction = WorldFaction(framework_id=fw.id, name="教会")
    db.add_all([start, other, faction])
    await db.flush()
    start.connections_json = json.dumps([
        {"target_id": other.id, "direction": "east", "travel_turns": 1},
    ])
    other.connections_json = json.dumps([
        {"target_id": start.id, "direction": "west", "travel_turns": 1},
    ])
    npc = WorldNPCTemplate(
        framework_id=fw.id, name="艾琳娜", role="修女", home_location_id=start.id,
    )
    event = WorldEvent(framework_id=fw.id, name="教会异动", importance=3)
    db.add_all([npc, event])
    await db.flush()
    db.add(Campaign(
        framework_id=fw.id,
        name="主线",
        phases_json=json.dumps([{
            "phase_id": 1,
            "name": "调查",
            "prerequisite_phase_ids": [],
            "key_event_ids": [event.id],
            "required_count": 1,
        }]),
    ))
    sess = GameSession(
        name="run",
        world_id=world.id,
        character_id=char.id,
        framework_id=fw.id,
        gm_model_config_id=cfg.id,
        summarizer_model_config_id=cfg.id,
    )
    db.add(sess)
    await db.flush()
    return sess, start, other, npc, faction, event


async def test_framework_id_is_present_in_session_output(db: AsyncSession):
    sess, *_ = await _seed_framework_session(db)
    assert _to_out(sess).framework_id == sess.framework_id


async def test_framework_session_never_owns_auto_generated_screenplay(db: AsyncSession):
    sess, *_ = await _seed_framework_session(db)
    assert sess.turn_count == 0
    assert _should_auto_generate_screenplay(sess) is False


async def test_framework_runtime_is_initialized_from_templates(db: AsyncSession):
    sess, start, other, npc, faction, event = await _seed_framework_session(db)
    await _initialize_framework_runtime(db, sess, sess.framework_id)
    await db.flush()

    assert (await db.get(SessionNpcState, (sess.id, npc.id))).current_location_id == start.id
    assert (await db.get(SessionFactionState, (sess.id, faction.id))) is not None
    assert (await db.get(SessionEventState, (sess.id, event.id))).status == "pending"
    assert (await db.get(SessionCampaignState, sess.id)).current_phase_id == 1
    assert json.loads(sess.settings_json)["pc_location_id"] == other.id
    current = (await db.execute(
        select(Location).where(Location.session_id == sess.id, Location.is_current == True)  # noqa: E712
    )).scalar_one()
    assert current.name == "广场"
    runtime_names = set((await db.execute(
        select(Location.name).where(Location.session_id == sess.id)
    )).scalars().all())
    assert runtime_names == {"教堂", "广场"}
    edges = (await db.execute(
        select(LocationEdge).where(LocationEdge.session_id == sess.id)
    )).scalars().all()
    assert len(edges) == 2
    assert {edge.description for edge in edges} == {"east", "west"}


async def test_placeholder_and_unknown_framework_locations_are_rejected(db: AsyncSession):
    sess, _, start, *_ = await _seed_framework_session(db)
    await _initialize_framework_runtime(db, sess, sess.framework_id)
    accepted = await apply_tags(db, sess.id, 1, [
        TagComplete(name="location_enter", attrs={"name": "具体地点名", "description": "一句话"}),
        TagComplete(name="location_enter", attrs={"name": "安全屋", "description": "凭空出现"}),
    ])
    await db.flush()

    names = (await db.execute(
        select(Location.name).where(Location.session_id == sess.id)
    )).scalars().all()
    assert set(names) == {"教堂", "广场"}
    assert json.loads(sess.settings_json)["pc_location_id"] == start.id
    assert accepted == []


async def test_known_framework_location_updates_both_location_models(db: AsyncSession):
    sess, _, other, *_ = await _seed_framework_session(db)
    await _initialize_framework_runtime(db, sess, sess.framework_id)
    accepted = await apply_tags(db, sess.id, 2, [
        TagComplete(name="location_enter", attrs={"name": other.name, "description": other.description_md}),
    ])
    await db.flush()

    assert json.loads(sess.settings_json)["pc_location_id"] == other.id
    current = (await db.execute(
        select(Location).where(Location.session_id == sess.id, Location.is_current == True)  # noqa: E712
    )).scalar_one()
    assert current.name == other.name
    assert [tag.name for tag in accepted] == ["location_enter"]


async def test_framework_event_tags_accept_exact_event_name(db: AsyncSession):
    sess, _, _, _, _, event = await _seed_framework_session(db)
    await _initialize_framework_runtime(db, sess, sess.framework_id)

    triggered = await apply_tags(db, sess.id, 1, [
        TagComplete(name="event_trigger", attrs={"event_id": event.name}),
    ])
    completed = await apply_tags(db, sess.id, 2, [
        TagComplete(name="event_complete", attrs={"event_id": event.name}),
    ])

    state = await db.get(SessionEventState, (sess.id, event.id))
    assert state.status == "completed"
    assert [tag.name for tag in triggered] == ["event_trigger"]
    assert [tag.name for tag in completed] == ["event_complete"]


async def test_locked_campaign_event_does_not_auto_trigger(db: AsyncSession):
    from dzmm.service.event_evaluator import check_and_trigger_events

    sess, _, _, _, _, active_event = await _seed_framework_session(db)
    await _initialize_framework_runtime(db, sess, sess.framework_id)
    locked_event = WorldEvent(
        framework_id=sess.framework_id,
        name="后续阶段事件",
        trigger_conditions_json='{"type":"all","children":[]}',
    )
    db.add(locked_event)
    await db.flush()
    db.add(SessionEventState(
        session_id=sess.id,
        event_id=locked_event.id,
        status="pending",
    ))
    campaign = (await db.execute(
        select(Campaign).where(Campaign.framework_id == sess.framework_id)
    )).scalar_one()
    campaign.phases_json = json.dumps([
        {
            "phase_id": 1,
            "name": "调查",
            "prerequisite_phase_ids": [],
            "key_event_ids": [active_event.id],
            "required_count": 1,
        },
        {
            "phase_id": 2,
            "name": "决战",
            "prerequisite_phase_ids": [1],
            "key_event_ids": [locked_event.id],
            "required_count": 1,
        },
    ])

    triggered = await check_and_trigger_events(db, sess.id, 1)

    state = await db.get(SessionEventState, (sess.id, locked_event.id))
    assert locked_event.id not in triggered
    assert state.status == "pending"


async def test_framework_templates_are_injected_as_scene_ground_truth(db: AsyncSession):
    sess, start, _, npc, faction, _ = await _seed_framework_session(db)
    await _initialize_framework_runtime(db, sess, sess.framework_id)
    facts = await _build_key_facts(db, sess.id, current_turn=1)

    assert "开放世界框架（唯一事实源" in facts
    assert start.name in facts
    assert faction.name in facts
    assert npc.name in facts
    assert "不得虚构共同前情" in facts
