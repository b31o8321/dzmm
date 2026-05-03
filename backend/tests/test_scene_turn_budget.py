import json
import pytest
from sqlalchemy import select

from dzmm.db.base import init_db, get_engine, async_session
from dzmm.db.models import (
    Character, CharState, ModelConfig, Session as GameSession, World, Location,
)
from dzmm.models.client import GenerationParams, Message, ModelClient, StreamChunk, TokenUsage
from dzmm.parsing.events import NarrativeDelta, TagComplete
from dzmm.service.game import run_turn, SCENE_SOFT_PRESSURE_TURNS, SCENE_HARD_EXIT_TURNS, _build_key_facts


class FakeClient(ModelClient):
    name = "fake"
    def __init__(self, output: str):
        self.output = output
    async def stream(self, messages, params):
        for ch in self.output:
            yield StreamChunk(delta=ch)
        yield StreamChunk(delta="", finish_reason="stop",
                          usage=TokenUsage(input_tokens=5, output_tokens=10))


@pytest.fixture
async def seeded(tmp_path):
    engine = get_engine(f"sqlite+aiosqlite:///{tmp_path}/t.db")
    await init_db(engine)
    SM = async_session(engine)
    async with SM() as s:
        world = World(name="W", content_md="x", style="dark",
                      rules_json='{"mode":"light"}')
        char = Character(world=world, name="Riku", profile_md="黑客",
                         base_stats_json='{"hp":20}')
        cfg = ModelConfig(name="m", type="ollama",
                          base_url="http://localhost:11434", model_name="q")
        s.add_all([world, char, cfg])
        await s.flush()
        sess = GameSession(name="run", world_id=world.id, character_id=char.id,
                           gm_model_config_id=cfg.id, summarizer_model_config_id=cfg.id)
        s.add(sess)
        await s.flush()
        s.add(CharState(session_id=sess.id, stats_json='{"hp":20}', inventory_json="[]"))
        await s.commit()
        yield SM, sess.id
    await engine.dispose()


async def test_scene_turn_count_increments_without_location_change(seeded):
    """scene_turn_count += 1 each turn when no location_enter tag is emitted."""
    SM, sid = seeded
    client = FakeClient("<narrative>test</narrative>")
    async with SM() as s:
        async for _ in run_turn(s, sid, "环顾", client):
            pass
        await s.commit()
    async with SM() as s:
        sess = await s.get(GameSession, sid)
        assert sess.scene_turn_count == 1

    # Second turn — should reach 2
    client2 = FakeClient("<narrative>test2</narrative>")
    async with SM() as s:
        async for _ in run_turn(s, sid, "等待", client2):
            pass
        await s.commit()
    async with SM() as s:
        sess = await s.get(GameSession, sid)
        assert sess.scene_turn_count == 2


async def test_scene_turn_count_resets_on_location_enter(seeded):
    """scene_turn_count resets to 1 when GM emits <location_enter>."""
    SM, sid = seeded
    # Preset to 5 to simulate a stuck scene
    async with SM() as s:
        sess = await s.get(GameSession, sid)
        sess.scene_turn_count = 5
        await s.commit()

    output = '<narrative>走进酒馆。</narrative><location_enter name="酒馆" description="热闹"/>'
    client = FakeClient(output)
    async with SM() as s:
        async for _ in run_turn(s, sid, "进入酒馆", client):
            pass
        await s.commit()

    async with SM() as s:
        sess = await s.get(GameSession, sid)
        assert sess.scene_turn_count == 1


async def test_scene_pressure_appears_in_key_facts_above_threshold(seeded):
    """_build_key_facts injects scene pressure when scene_turn_count >= SCENE_SOFT_PRESSURE_TURNS."""
    SM, sid = seeded
    async with SM() as s:
        sess = await s.get(GameSession, sid)
        sess.scene_turn_count = SCENE_SOFT_PRESSURE_TURNS
        s.add(Location(session_id=sid, name="酒馆", description="",
                       first_visited_turn=1, last_visited_turn=4, is_current=True))
        await s.commit()
    async with SM() as s:
        kf = await _build_key_facts(s, sid, current_turn=5)
    assert "场景时间提醒" in kf or "场景强推" in kf


async def test_scene_pressure_absent_below_threshold(seeded):
    """No scene pressure injected when scene_turn_count < SCENE_SOFT_PRESSURE_TURNS."""
    SM, sid = seeded
    async with SM() as s:
        sess = await s.get(GameSession, sid)
        sess.scene_turn_count = 2
        s.add(Location(session_id=sid, name="酒馆", description="",
                       first_visited_turn=1, last_visited_turn=2, is_current=True))
        await s.commit()
    async with SM() as s:
        kf = await _build_key_facts(s, sid, current_turn=3)
    assert "场景时间提醒" not in kf
    assert "场景强推" not in kf


async def test_hard_exit_pressure_at_scene_hard_exit_turns(seeded):
    """Hard exit pressure (场景强推) appears at SCENE_HARD_EXIT_TURNS threshold."""
    SM, sid = seeded
    async with SM() as s:
        sess = await s.get(GameSession, sid)
        sess.scene_turn_count = SCENE_HARD_EXIT_TURNS
        s.add(Location(session_id=sid, name="酒馆", description="",
                       first_visited_turn=1, last_visited_turn=6, is_current=True))
        await s.commit()
    async with SM() as s:
        kf = await _build_key_facts(s, sid, current_turn=8)
    assert "场景强推" in kf
    assert "场景时间提醒" not in kf
