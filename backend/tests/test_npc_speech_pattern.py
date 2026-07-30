"""Tests for v0.53 NPC speech_pattern feature (E5)."""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.db.base import async_session, get_engine, init_db
from dzmm.db.models import (
    NPC,
    ModelConfig,
    Session as GameSession,
    World,
)
from dzmm.service.npc_dossier import _format_npc_dossier
from dzmm.prompts.npc_actor_template import build_npc_actor_messages


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
async def db(tmp_path):
    engine = get_engine(f"sqlite+aiosqlite:///{tmp_path}/speech_test.db")
    await init_db(engine)
    async with async_session(engine)() as s:
        yield s, engine
    await engine.dispose()


@pytest.fixture
async def db_session(tmp_path):
    engine = get_engine(f"sqlite+aiosqlite:///{tmp_path}/speech_s.db")
    await init_db(engine)
    async with async_session(engine)() as s:
        yield s
    await engine.dispose()


async def _make_npc(s: AsyncSession, speech_pattern: str = "") -> NPC:
    world = World(name="W", content_md="x", style="realistic")
    s.add(world)
    cfg = ModelConfig(name="m", type="ollama", base_url="http://localhost", model_name="t")
    s.add(cfg)
    await s.flush()

    sess = GameSession(
        name="run",
        world_id=world.id,
        character_id=1,  # dummy — not used in these tests
        gm_model_config_id=cfg.id,
        summarizer_model_config_id=cfg.id,
    )
    # We need a real character for the FK; create one minimally
    from dzmm.db.models import Character
    char = Character(
        world_id=world.id,
        name="PC",
        profile_md="x",
        base_stats_json="{}",
    )
    s.add(char)
    await s.flush()
    sess.character_id = char.id
    s.add(sess)
    await s.flush()

    npc = NPC(
        session_id=sess.id,
        name="老张",
        archetype="商人",
        description="一个矮小的中年男人",
        purpose="卖消息赚钱",
        favor=10,
        speech_pattern=speech_pattern,
    )
    s.add(npc)
    await s.commit()
    return npc


# ── Column existence tests (V053 migration) ───────────────────────────────────

async def test_v053_npc_speech_pattern_column_exists(db):
    """npcs.speech_pattern column should exist after init_db."""
    s, engine = db
    async with engine.connect() as conn:
        cols = await conn.execute(text("PRAGMA table_info(npcs)"))
        col_names = {row[1] for row in cols.fetchall()}
    assert "speech_pattern" in col_names


async def test_v053_world_npc_template_speech_pattern_column_exists(db):
    """world_npc_templates.speech_pattern column should exist after init_db."""
    s, engine = db
    async with engine.connect() as conn:
        cols = await conn.execute(text("PRAGMA table_info(world_npc_templates)"))
        col_names = {row[1] for row in cols.fetchall()}
    assert "speech_pattern" in col_names


# ── npc_actor prompt tests ────────────────────────────────────────────────────

async def test_npc_actor_prompt_injects_speech_pattern(db_session):
    """build_npc_actor_messages should include speech_pattern in system prompt."""
    npc = await _make_npc(db_session, speech_pattern="总用反问句反将一军")
    msgs = build_npc_actor_messages(
        npc=npc,
        history=[],
        plot_directive="NPC test",
        scene_narrative="场景",
        user_action="你好",
    )
    system_content = msgs[0].content
    assert "总用反问句反将一军" in system_content
    assert "说话风格" in system_content


async def test_npc_actor_prompt_no_speech_pattern_when_empty(db_session):
    """When speech_pattern is empty, prompt should use the default fallback."""
    npc = await _make_npc(db_session, speech_pattern="")
    msgs = build_npc_actor_messages(
        npc=npc,
        history=[],
        plot_directive="NPC test",
        scene_narrative="场景",
        user_action="你好",
    )
    system_content = msgs[0].content
    # Fallback text should appear; no empty placeholder
    assert "说话自然" in system_content or "无特殊" in system_content


# ── npc_dossier tests ─────────────────────────────────────────────────────────

async def test_dossier_includes_speech_pattern_when_set(db_session):
    """_format_npc_dossier should show speech_pattern when present."""
    npc = await _make_npc(db_session, speech_pattern="口头禅：「啧，麻烦」")
    dossier = _format_npc_dossier(npc)
    assert "口头禅：「啧，麻烦」" in dossier
    assert "说话风格" in dossier


async def test_dossier_excludes_when_empty(db_session):
    """_format_npc_dossier should NOT include a speech_pattern line when empty."""
    npc = await _make_npc(db_session, speech_pattern="")
    dossier = _format_npc_dossier(npc)
    assert "说话风格" not in dossier
