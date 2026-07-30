"""Tests for <say> auto-NPC creation (E1+ bug fix).

When GM emits <say speaker="X"> for an unknown speaker, apply_tags should
automatically create a minimal NPC row so that the dossier loader can inject
it on the next turn.
"""
import pytest

from sqlalchemy import select

from dzmm.db.base import init_db, get_engine, async_session
from dzmm.db.models import (
    Character,
    ModelConfig,
    NPC,
    Session as GameSession,
    World,
)
from dzmm.parsing.events import TagComplete
from dzmm.service.state_apply._impl import apply_tags


# ── Shared fixture ──────────────────────────────────────────────────────────

@pytest.fixture
async def db(tmp_path):
    engine = get_engine(f"sqlite+aiosqlite:///{tmp_path}/say_npc.db")
    await init_db(engine)
    SM = async_session(engine)
    async with SM() as s:
        world = World(name="W", content_md="x", style="dark")
        char = Character(world=world, name="Hero", profile_md="y", base_stats_json="{}")
        cfg = ModelConfig(
            name="m", type="ollama",
            base_url="http://localhost:11434", model_name="q",
        )
        s.add_all([world, char, cfg])
        await s.flush()
        sess = GameSession(
            name="r", world_id=world.id, character_id=char.id,
            gm_model_config_id=cfg.id, summarizer_model_config_id=cfg.id,
        )
        s.add(sess)
        await s.commit()
        yield SM, sess.id
    await engine.dispose()


# ── Tests ───────────────────────────────────────────────────────────────────

async def test_say_with_new_speaker_creates_npc(db):
    """A <say speaker="魁梧男人"> tag for an unknown speaker creates a new NPC row."""
    SM, sid = db
    async with SM() as s:
        await apply_tags(
            s, sid, 1,
            [TagComplete(name="say", attrs={"speaker": "魁梧男人"}, content="你好，旅行者。")],
        )
        await s.commit()

    async with SM() as s:
        npc = (await s.execute(
            select(NPC).where(NPC.session_id == sid, NPC.name == "魁梧男人")
        )).scalar_one_or_none()
        assert npc is not None, "NPC row should have been auto-created"


async def test_say_with_existing_speaker_no_duplicate(db):
    """A <say> for a speaker that already exists in the NPC table creates no duplicate."""
    SM, sid = db

    # Pre-create the NPC
    async with SM() as s:
        s.add(NPC(session_id=sid, name="长发女子", state="alive", favor=5))
        await s.commit()

    async with SM() as s:
        await apply_tags(
            s, sid, 2,
            [TagComplete(name="say", attrs={"speaker": "长发女子"}, content="你好。")],
        )
        await s.commit()

    async with SM() as s:
        count = len(
            (await s.execute(
                select(NPC).where(NPC.session_id == sid, NPC.name == "长发女子")
            )).scalars().all()
        )
        assert count == 1, "Should not have created a duplicate NPC row"


async def test_say_with_empty_speaker_skipped(db):
    """A <say> tag with no speaker attribute creates nothing."""
    SM, sid = db
    async with SM() as s:
        await apply_tags(
            s, sid, 1,
            [TagComplete(name="say", attrs={}, content="有人喃喃自语。")],
        )
        await s.commit()

    async with SM() as s:
        npcs = (await s.execute(
            select(NPC).where(NPC.session_id == sid)
        )).scalars().all()
        assert len(npcs) == 0


async def test_say_creates_npc_with_correct_defaults(db):
    """Auto-created NPC has state=alive, favor=0, and revealed_json with name=true."""
    import json
    SM, sid = db
    async with SM() as s:
        await apply_tags(
            s, sid, 3,
            [TagComplete(name="say", attrs={"speaker": "神秘老人"}, content="孩子，听着。")],
        )
        await s.commit()

    async with SM() as s:
        npc = (await s.execute(
            select(NPC).where(NPC.session_id == sid, NPC.name == "神秘老人")
        )).scalar_one()
        assert npc.state == "alive"
        assert npc.favor == 0
        revealed = json.loads(npc.revealed_json)
        assert revealed.get("name") is True
        assert npc.archetype == "neutral"
        assert npc.last_seen_turn == 3


async def test_say_with_whitespace_speaker_trimmed_and_skipped_if_empty(db):
    """A speaker value that is only whitespace is treated as empty and skipped."""
    SM, sid = db
    async with SM() as s:
        await apply_tags(
            s, sid, 1,
            [TagComplete(name="say", attrs={"speaker": "   "}, content="……")],
        )
        await s.commit()

    async with SM() as s:
        npcs = (await s.execute(
            select(NPC).where(NPC.session_id == sid)
        )).scalars().all()
        assert len(npcs) == 0


async def test_say_handler_continues_when_npc_create_fails(db):
    """If NPC insertion raises, the handler logs a warning and does not propagate the error."""
    SM, sid = db

    async with SM() as s:
        # Monkey-patch session.add to raise when given an NPC
        real_add = s.add

        def failing_add(obj):
            if isinstance(obj, NPC):
                raise RuntimeError("simulated DB error")
            real_add(obj)

        s.add = failing_add

        # Should not raise
        await apply_tags(
            s, sid, 1,
            [TagComplete(name="say", attrs={"speaker": "故障NPC"}, content="我会让插入失败。")],
        )
        # Restore for commit
        s.add = real_add
        await s.commit()

    # Session count should still be 0 (no NPC was created)
    async with SM() as s:
        npcs = (await s.execute(
            select(NPC).where(NPC.session_id == sid)
        )).scalars().all()
        assert len(npcs) == 0
