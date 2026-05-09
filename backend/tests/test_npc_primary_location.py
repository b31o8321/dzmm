"""v0.10.5 Feature 2 — scene-aware NPC encounters.

Verifies:
- check_encounter_warnings flags first-appearance NPCs that materialize
  outside their primary_location with no encounter_setup bridge
- PC physically present at the NPC's primary_location → no warning
- Recent encounter_setup plot_event in the prior turn → no warning
- NPC who appeared in a previous turn (not first appearance) → no warning
- Legacy screenplays without primary_location → silent (backward-compat)
"""
from __future__ import annotations

import json

import pytest
from sqlalchemy import select

from dzmm.db.base import async_session, get_engine, init_db
from dzmm.db.models import (
    Character,
    Location,
    Message as MessageRow,
    ModelConfig,
    NPC,
    Screenplay,
    Session as GameSession,
    World,
)
from dzmm.parsing.events import TagComplete


@pytest.fixture
async def session_maker(tmp_path):
    db_url = f"sqlite+aiosqlite:///{tmp_path}/t.db"
    engine = get_engine(db_url)
    await init_db(engine)
    sm = async_session(engine)
    yield sm
    await engine.dispose()


async def _seed(sm) -> tuple[int, str]:
    """Returns (session_id, npc_name).

    Builds a baseline that should *trigger* a warning unless modified by
    the individual test (e.g., move PC, add encounter_setup, etc.):
      - Active screenplay declares NPC "张三" with primary_location 凯旋酒馆
      - PC currently at 街角 (NOT 凯旋酒馆)
      - 张三's last_seen_turn == current turn (first appearance this turn)
      - No prior assistant messages
    """
    async with sm() as s:
        w = World(name="W", content_md="")
        s.add(w)
        await s.flush()
        c = Character(
            world_id=w.id, name="PC", profile_md="", base_stats_json="{}",
        )
        s.add(c)
        m = ModelConfig(name="m", type="ollama", base_url="x", model_name="y")
        s.add(m)
        await s.flush()
        sess = GameSession(
            name="t",
            world_id=w.id,
            character_id=c.id,
            gm_model_config_id=m.id,
            summarizer_model_config_id=m.id,
            turn_count=2,
            topology_warning_json="[]",
        )
        s.add(sess)
        await s.flush()

        s.add(Screenplay(
            session_id=sess.id,
            world_id=w.id,
            status="active",
            chapters_json=json.dumps([
                {"title": "开端", "main_locations": ["凯旋酒馆", "街角"]},
            ], ensure_ascii=False),
            main_characters_json=json.dumps([
                {"name": "张三", "primary_location": "凯旋酒馆"},
            ], ensure_ascii=False),
            current_chapter=1,
        ))
        s.add(Location(
            session_id=sess.id, name="街角", is_current=True,
            first_visited_turn=1, last_visited_turn=2,
        ))
        s.add(NPC(
            session_id=sess.id, name="张三", favor=0, last_seen_turn=2,
        ))
        await s.commit()
        return sess.id, "张三"


@pytest.mark.asyncio
async def test_warns_when_npc_appears_off_primary_location_no_setup(session_maker):
    from dzmm.service.encounter_check import check_encounter_warnings
    sid, name = await _seed(session_maker)
    async with session_maker() as s:
        tags = [TagComplete(name="say", attrs={"speaker": name}, content="「你好」")]
        await check_encounter_warnings(s, sid, tags, current_turn=2)
        await s.commit()
        sess = await s.get(GameSession, sid)
    warnings = json.loads(sess.topology_warning_json)
    assert any("凭空出场" in w for w in warnings), warnings
    assert any(name in w for w in warnings), warnings
    assert any("凯旋酒馆" in w for w in warnings), warnings


@pytest.mark.asyncio
async def test_no_warning_when_pc_at_primary_location(session_maker):
    from dzmm.service.encounter_check import check_encounter_warnings
    sid, name = await _seed(session_maker)
    async with session_maker() as s:
        # Move PC to 凯旋酒馆 (the NPC's primary_location)
        loc = (await s.execute(
            select(Location).where(Location.session_id == sid)
        )).scalar_one()
        loc.is_current = False
        s.add(Location(
            session_id=sid, name="凯旋酒馆", is_current=True,
            first_visited_turn=2, last_visited_turn=2,
        ))
        await s.commit()
        tags = [TagComplete(name="say", attrs={"speaker": name}, content="「你好」")]
        await check_encounter_warnings(s, sid, tags, current_turn=2)
        await s.commit()
        sess = await s.get(GameSession, sid)
    warnings = json.loads(sess.topology_warning_json)
    assert not any("凭空出场" in w for w in warnings), warnings


@pytest.mark.asyncio
async def test_no_warning_when_recent_encounter_setup_exists(session_maker):
    from dzmm.service.encounter_check import check_encounter_warnings
    sid, name = await _seed(session_maker)
    async with session_maker() as s:
        # Prior assistant turn emitted an encounter_setup plot_event for 张三
        s.add(MessageRow(
            session_id=sid, role="assistant", turn=1,
            content="<plot_event ...>",
            events_json=json.dumps([{
                "type": "plot_event",
                "payload": {"type": "encounter_setup", "importance": "2"},
                "content": f"PC 收到 {name} 的信，约在街角见面",
            }], ensure_ascii=False),
        ))
        await s.commit()
        tags = [TagComplete(name="say", attrs={"speaker": name}, content="「你好」")]
        await check_encounter_warnings(s, sid, tags, current_turn=2)
        await s.commit()
        sess = await s.get(GameSession, sid)
    warnings = json.loads(sess.topology_warning_json)
    assert not any("凭空出场" in w for w in warnings), warnings


@pytest.mark.asyncio
async def test_no_warning_when_npc_already_appeared_before(session_maker):
    """NPCs that already showed up in previous turns are not 'first appearance'."""
    from dzmm.service.encounter_check import check_encounter_warnings
    sid, name = await _seed(session_maker)
    async with session_maker() as s:
        # Prior assistant turn with say from 张三 — not first appearance any more
        s.add(MessageRow(
            session_id=sid, role="assistant", turn=1,
            content=f'<say speaker="{name}">「之前的对话」</say>',
            events_json=json.dumps([{
                "type": "say",
                "payload": {"speaker": name},
                "content": "之前的对话",
            }], ensure_ascii=False),
        ))
        await s.commit()
        tags = [TagComplete(name="say", attrs={"speaker": name}, content="「现在说」")]
        await check_encounter_warnings(s, sid, tags, current_turn=2)
        await s.commit()
        sess = await s.get(GameSession, sid)
    warnings = json.loads(sess.topology_warning_json)
    assert not any("凭空出场" in w for w in warnings), warnings


@pytest.mark.asyncio
async def test_no_warning_when_screenplay_has_no_primary_location(session_maker):
    """Backward-compat: legacy screenplays whose main_characters lack a
    primary_location (pre-v0.10.5) should not produce false-positive warnings."""
    from dzmm.service.encounter_check import check_encounter_warnings
    sid, name = await _seed(session_maker)
    async with session_maker() as s:
        # Replace screenplay's main_characters with one missing primary_location
        sp = (await s.execute(
            select(Screenplay).where(Screenplay.session_id == sid)
        )).scalars().first()
        sp.main_characters_json = json.dumps(
            [{"name": name, "role": "盟友"}], ensure_ascii=False,
        )
        await s.commit()
        tags = [TagComplete(name="say", attrs={"speaker": name}, content="「你好」")]
        await check_encounter_warnings(s, sid, tags, current_turn=2)
        await s.commit()
        sess = await s.get(GameSession, sid)
    warnings = json.loads(sess.topology_warning_json)
    assert not any("凭空出场" in w for w in warnings), warnings


@pytest.mark.asyncio
async def test_outliner_schema_documents_primary_location():
    """Schema-level smoke test: outliner prompt must mention the new fields
    so the LLM is instructed to emit them."""
    from dzmm.prompts.outliner_template import _OUTLINER_SYSTEM
    assert "main_locations" in _OUTLINER_SYSTEM
    assert "primary_location" in _OUTLINER_SYSTEM


@pytest.mark.asyncio
async def test_gm_template_iron_rule_36_present():
    """GM iron rule 36 must be in the system template."""
    from dzmm.prompts import gm_template
    src = open(gm_template.__file__, encoding="utf-8").read()
    assert "36." in src
    assert "encounter_setup" in src
    assert "primary_location" in src
