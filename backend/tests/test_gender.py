"""Gender attribute wiring (E):
- wizard normalization accepts male/female/男/女 + aliases
- _format_character_card surfaces 性别: 男/女 to GM
- _format_npc_dossier prepends ♂/♀ marker after the NPC name
- state_apply <npc_update> creates NPC with normalized gender, but
  refuses to overwrite an existing assignment (continuity guard)
"""
from sqlalchemy import select

import pytest

from dzmm.db.base import async_session, get_engine, init_db
from dzmm.db.models import (
    Character, ModelConfig, NPC, Session as GameSession, World,
)
from dzmm.service.game import _format_character_card
from dzmm.service.npc_dossier import _format_npc_dossier, _format_npc_short
from dzmm.service.state_apply.npc import _apply_npc_update, _normalize_gender_str
from dzmm.service.wizard import _normalize_gender


@pytest.fixture
async def db_session(tmp_path):
    engine = get_engine(f"sqlite+aiosqlite:///{tmp_path}/g.db")
    await init_db(engine)
    SessionMaker = async_session(engine)
    async with SessionMaker() as s:
        yield s
    await engine.dispose()


@pytest.fixture
async def session_id(db_session):
    world = World(name="W", content_md="x", style="dark")
    char = Character(world=world, name="C", profile_md="y",
                     base_stats_json='{"hp":20}')
    cfg = ModelConfig(name="m", type="ollama",
                      base_url="http://localhost:11434", model_name="qwen")
    db_session.add_all([world, char, cfg])
    await db_session.flush()
    sess = GameSession(name="run", world_id=world.id, character_id=char.id,
                       gm_model_config_id=cfg.id, summarizer_model_config_id=cfg.id)
    db_session.add(sess)
    await db_session.flush()
    await db_session.commit()
    return sess.id


@pytest.mark.parametrize("raw,expected", [
    ("male", "male"),
    ("Male", "male"),
    ("female", "female"),
    ("FEMALE", "female"),
    ("男", "male"),
    ("女", "female"),
    ("男性", "male"),
    ("女性", "female"),
    ("m", "male"),
    ("F", "female"),
    ("nonbinary", ""),
    ("", ""),
    (None, ""),
])
def test_normalize_gender_handles_aliases(raw, expected):
    assert _normalize_gender(raw) == expected
    # state_apply has its own copy of the function — same contract.
    assert _normalize_gender_str(raw) == expected


def test_format_character_card_with_gender():
    char = Character(
        world_id=1, name="林默",
        gender="female",
        profile_md="## 基本信息\n- 姓名：林默\n## 背景\n来自九龙",
        base_stats_json="{}", level=3,
    )
    out = _format_character_card(char)
    assert "等级: Lv 3" in out
    assert "性别: 女" in out
    assert "来自九龙" in out


def test_format_character_card_without_gender_legacy():
    char = Character(
        world_id=1, name="无名",
        gender="",  # legacy
        profile_md="## 基本信息\n- 姓名：无名",
        base_stats_json="{}", level=1,
    )
    out = _format_character_card(char)
    assert "等级: Lv 1" in out
    # No gender line for legacy data — GM must not invent one.
    assert "性别:" not in out


def _make_npc(gender: str = "") -> NPC:
    return NPC(
        session_id=1, name="阿离", gender=gender,
        description="干净利落的女打手",
        favor=10, state="戒备",
        last_seen_turn=5, archetype="对手",
        notes_json="[]", purpose="找出真凶",
        affinity_json="{}", emotion_json="{}",
        revealed_json='{"name": true, "state": true, "favor": true, "archetype": true, "description": true}',
        pinned=True,
    )


def test_npc_dossier_marks_gender():
    npc = _make_npc(gender="female")
    out = _format_npc_dossier(npc)
    assert out.startswith("- 阿离(♀)")
    assert "[对手]" in out


def test_npc_dossier_male_marker():
    npc = _make_npc(gender="male")
    out = _format_npc_dossier(npc)
    assert out.startswith("- 阿离(♂)")


def test_npc_dossier_legacy_no_marker():
    npc = _make_npc(gender="")
    out = _format_npc_dossier(npc)
    # Legacy: name only, no gender symbol injected.
    assert out.startswith("- 阿离 ")
    assert "♂" not in out and "♀" not in out


def test_npc_short_marks_gender():
    npc = _make_npc(gender="male")
    out = _format_npc_short(npc)
    assert "阿离(♂)" in out


# ── state_apply <npc_update gender=...> ─────────────────────────

async def test_apply_npc_update_creates_with_gender(db_session, session_id):
    """Creating an NPC via <npc_update> with gender=female persists it."""
    await _apply_npc_update(
        db_session, session_id, 1,
        {"name": "新人", "gender": "female", "description": "黑发瘦削"},
        "",
    )
    await db_session.commit()
    fetched = (await db_session.execute(
        select(NPC).where(NPC.name == "新人")
    )).scalar_one()
    assert fetched.gender == "female"


async def test_apply_npc_update_creates_with_chinese_gender_alias(
    db_session, session_id,
):
    """`gender="男"` is normalized to `male`."""
    await _apply_npc_update(
        db_session, session_id, 1,
        {"name": "老张", "gender": "男"},
        "",
    )
    await db_session.commit()
    fetched = (await db_session.execute(
        select(NPC).where(NPC.name == "老张")
    )).scalar_one()
    assert fetched.gender == "male"


async def test_apply_npc_update_preserves_existing_gender(db_session, session_id):
    """Once a gender is set, a later GM emit cannot flip it — that would
    silently corrupt continuity."""
    db_session.add(NPC(
        session_id=session_id, name="阿离", gender="female",
        description="女打手", favor=0, state="未知", last_seen_turn=1,
        notes_json="[]", purpose="", archetype="",
        affinity_json="{}", emotion_json="{}",
        revealed_json='{"name": true}', pinned=False,
    ))
    await db_session.commit()

    await _apply_npc_update(
        db_session, session_id, 2,
        {"name": "阿离", "gender": "male", "state": "受伤"},
        "",
    )
    await db_session.commit()

    fetched = (await db_session.execute(
        select(NPC).where(NPC.name == "阿离")
    )).scalar_one()
    assert fetched.gender == "female"  # unchanged
    assert fetched.state == "受伤"  # other fields still update
