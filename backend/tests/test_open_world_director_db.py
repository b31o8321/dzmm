import json

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from dzmm.db import models  # noqa: F401
from dzmm.db.base import Base
from dzmm.db.models import (
    AgentMessage,
    Campaign,
    Character,
    ModelConfig,
    Session as GameSession,
    SessionCampaignState,
    SessionEventState,
    World,
    WorldEvent,
    WorldFramework,
    WorldLocation,
)
from dzmm.models.client import GenerationParams, Message, ModelClient, TokenUsage
from dzmm.service.agents.director_open_world import run_open_world_director


class _DirectorClient(ModelClient):
    name = "director-test"

    def __init__(self):
        self.messages: list[Message] = []

    async def stream(self, messages: list[Message], params: GenerationParams):
        if False:
            yield

    async def complete(self, messages, params):
        self.messages = messages
        return "<plot_directive>只推进候选事件</plot_directive>", TokenUsage()


@pytest.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


async def test_director_db_snapshot_keeps_triggered_and_filters_locked_phase(db):
    world = World(name="W", content_md="world")
    char = Character(world=world, name="PC", profile_md="profile", base_stats_json="{}")
    cfg = ModelConfig(name="m", type="ollama", base_url="http://x", model_name="m")
    framework = WorldFramework(name="FW")
    db.add_all([world, char, cfg, framework])
    await db.flush()
    location = WorldLocation(framework_id=framework.id, name="教堂")
    db.add(location)
    await db.flush()

    active = WorldEvent(
        framework_id=framework.id, name="当前阶段事件", scope_type="location",
        scope_ref=str(location.id), importance=3,
    )
    locked = WorldEvent(
        framework_id=framework.id, name="后续阶段事件", scope_type="location",
        scope_ref=str(location.id), importance=5,
    )
    ongoing = WorldEvent(
        framework_id=framework.id, name="已触发待完成", scope_type="location",
        scope_ref=str(location.id), importance=2,
    )
    completed = WorldEvent(
        framework_id=framework.id, name="已完成事件", scope_type="location",
        scope_ref=str(location.id), importance=5,
    )
    db.add_all([active, locked, ongoing, completed])
    await db.flush()
    db.add(Campaign(
        framework_id=framework.id,
        name="主线",
        phases_json=json.dumps([
            {
                "phase_id": 1, "name": "调查", "prerequisite_phase_ids": [],
                "key_event_ids": [active.id], "required_count": 1,
            },
            {
                "phase_id": 2, "name": "决战", "prerequisite_phase_ids": [1],
                "key_event_ids": [locked.id], "required_count": 1,
            },
        ]),
    ))
    session = GameSession(
        name="run", world_id=world.id, character_id=char.id,
        framework_id=framework.id, gm_model_config_id=cfg.id,
        summarizer_model_config_id=cfg.id,
    )
    db.add(session)
    await db.flush()
    db.add_all([
        SessionCampaignState(
            session_id=session.id, current_phase_id=1, triggered_key_events_json="[]",
        ),
        SessionEventState(session_id=session.id, event_id=active.id, status="pending"),
        SessionEventState(session_id=session.id, event_id=locked.id, status="pending"),
        SessionEventState(session_id=session.id, event_id=ongoing.id, status="triggered"),
        SessionEventState(session_id=session.id, event_id=completed.id, status="completed"),
    ])
    await db.flush()

    client = _DirectorClient()
    await run_open_world_director(
        db,
        session_id=session.id,
        framework_id=framework.id,
        client=client,
        current_turn=8,
        pc_location_id=location.id,
        character_name="PC",
        character_md="调查员",
        current_action="检查祭坛",
        recent_scene_facts="上一回合发现血迹",
    )
    await db.flush()

    snapshot_row = (await db.execute(
        select(AgentMessage).where(AgentMessage.role == "user")
    )).scalar_one()
    prompt = client.messages[-1].content
    assert "当前阶段事件" in prompt
    assert "已触发待完成" in prompt
    assert "triggered" in prompt
    assert "后续阶段事件" not in prompt
    assert "已完成事件" not in prompt
    assert "血迹" in prompt
    assert "调查（0/1 关键事件）" in prompt

    snapshot = json.loads(snapshot_row.content)
    assert set(snapshot) == {"turn", "current_location", "current_action"}
    assert snapshot["current_action"] == "检查祭坛"
