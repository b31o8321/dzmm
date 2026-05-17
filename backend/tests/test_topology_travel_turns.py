"""
Tests for v0.15.1 D2: travel_turns visibility in topology key_facts section.

When a GameSession has a framework_id and WorldLocation.connections_json contains
travel_turns, the topology section of _build_key_facts should render
"路程 N 回合" for each neighbouring location.

Non-framework sessions should be unchanged.
"""

import json
import pytest

from dzmm.db.base import init_db, get_engine, async_session
from dzmm.db.models import (
    Character, CharState, Location, LocationEdge, ModelConfig,
    Session as GameSession, World, WorldFramework, WorldLocation,
)
from dzmm.service.game import _build_key_facts


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

async def _seed_base(SM):
    """Seed world, char, cfg; return (world_id, char_id, cfg_id)."""
    async with SM() as s:
        world = World(name="W", content_md="x", style="dark", rules_json='{"mode":"light"}')
        char = Character(world=world, name="Hero", profile_md="", base_stats_json='{"hp":20}')
        cfg = ModelConfig(name="m", type="ollama", base_url="http://localhost:11434", model_name="q")
        s.add_all([world, char, cfg])
        await s.flush()
        wid, cid, mid = world.id, char.id, cfg.id
        await s.commit()
    return wid, cid, mid


async def _make_session(SM, world_id, char_id, cfg_id, framework_id=None):
    async with SM() as s:
        sess = GameSession(
            name="test",
            world_id=world_id,
            character_id=char_id,
            gm_model_config_id=cfg_id,
            summarizer_model_config_id=cfg_id,
            framework_id=framework_id,
        )
        s.add(sess)
        await s.flush()
        sid = sess.id
        s.add(CharState(session_id=sid, stats_json='{"hp":20}', inventory_json="[]"))
        await s.commit()
    return sid


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------

async def test_framework_session_includes_travel_turns_in_topology(tmp_path):
    """Seed a framework + WorldLocation connections; key_facts should contain 路程 N 回合."""
    engine = get_engine(f"sqlite+aiosqlite:///{tmp_path}/topo1.db")
    await init_db(engine)
    SM = async_session(engine)

    wid, cid, mid = await _seed_base(SM)

    # Create framework + world locations
    async with SM() as s:
        fw = WorldFramework(name="测试框架", description_md="", genre="fantasy")
        s.add(fw)
        await s.flush()

        wl_dock = WorldLocation(framework_id=fw.id, name="码头", description_md="", connections_json="[]")
        wl_bar = WorldLocation(framework_id=fw.id, name="酒吧", description_md="", connections_json="[]")
        s.add_all([wl_dock, wl_bar])
        await s.flush()

        # dock → bar: 2 turns travel
        wl_dock.connections_json = json.dumps([
            {"target_id": wl_bar.id, "direction": "north", "distance": 1, "travel_turns": 2}
        ])
        fw_id = fw.id
        await s.commit()

    sid = await _make_session(SM, wid, cid, mid, framework_id=fw_id)

    # Create the in-game Location for 码头 and mark it current
    async with SM() as s:
        loc = Location(session_id=sid, name="码头", description="海边", is_current=True)
        s.add(loc)
        await s.commit()

    # Call _build_key_facts — should include "路程 2 回合"
    async with SM() as s:
        kf = await _build_key_facts(s, sid, current_turn=3)

    assert "路程 2 回合" in kf, f"Expected '路程 2 回合' in key_facts, got:\n{kf}"
    assert "酒吧" in kf
    await engine.dispose()


async def test_non_framework_session_topology_unchanged(tmp_path):
    """Sessions without framework_id should NOT have 路程 in the topology."""
    engine = get_engine(f"sqlite+aiosqlite:///{tmp_path}/topo2.db")
    await init_db(engine)
    SM = async_session(engine)

    wid, cid, mid = await _seed_base(SM)
    sid = await _make_session(SM, wid, cid, mid, framework_id=None)

    async with SM() as s:
        loc_a = Location(session_id=sid, name="公寓", description="狭小", is_current=True)
        loc_b = Location(session_id=sid, name="酒馆", description="嘈杂", is_current=False)
        s.add_all([loc_a, loc_b])
        await s.flush()
        edge = LocationEdge(
            session_id=sid,
            from_loc_id=loc_a.id,
            to_loc_id=loc_b.id,
            relation="通往",
            description="走五分钟",
        )
        s.add(edge)
        await s.commit()

    async with SM() as s:
        kf = await _build_key_facts(s, sid, current_turn=2)

    # Topology should still render, just without travel_turns
    assert "酒馆" in kf
    assert "路程" not in kf
    await engine.dispose()


async def test_framework_with_no_matching_world_location_falls_back_gracefully(tmp_path):
    """Framework exists but current location name doesn't match any WorldLocation → no crash."""
    engine = get_engine(f"sqlite+aiosqlite:///{tmp_path}/topo3.db")
    await init_db(engine)
    SM = async_session(engine)

    wid, cid, mid = await _seed_base(SM)

    async with SM() as s:
        fw = WorldFramework(name="框架2", description_md="", genre="sci-fi")
        s.add(fw)
        await s.flush()
        fw_id = fw.id
        await s.commit()

    sid = await _make_session(SM, wid, cid, mid, framework_id=fw_id)

    async with SM() as s:
        loc = Location(session_id=sid, name="未知遗迹", description="神秘", is_current=True)
        s.add(loc)
        await s.commit()

    async with SM() as s:
        kf = await _build_key_facts(s, sid, current_turn=1)

    # Must not crash and 路程 should not appear
    assert isinstance(kf, str)
    assert "路程" not in kf
    await engine.dispose()
