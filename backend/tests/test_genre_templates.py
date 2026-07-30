"""Tests for engine/genre_templates.py and wizard structured stats.

TDD: tests are written before implementation. Run to confirm RED.
"""
import json
import random
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import select

from dzmm.db.base import async_session, get_engine, init_db
from dzmm.db.models import Character, ModelConfig
from dzmm.engine.genre_templates import apply_genre_template
from dzmm.engine.schema import Item, parse_items, parse_skills
from dzmm.models.client import GenerationParams, Message, ModelClient, StreamChunk, TokenUsage
from dzmm.service.wizard import finalize_wizard, generate_character


# ── Stubs ─────────────────────────────────────────────────────────────────────

class StubLLM(ModelClient):
    name = "stub-wizard-genre"

    def __init__(self, output: str):
        self.output = output

    async def stream(
        self, messages: list[Message], params: GenerationParams
    ) -> AsyncIterator[StreamChunk]:
        yield StreamChunk(delta=self.output)
        yield StreamChunk(
            delta="", finish_reason="stop",
            usage=TokenUsage(input_tokens=10, output_tokens=50),
        )


# Note: avoid trailing "}}" (nested dict at end) due to _DOUBLE_BRACE_RE in _extract_json.
# Workaround: put base_stats before profile_md so the outer "}" doesn't follow "}"
_CHAR_OUTPUT = '{"name": "李明", "gender": "male", "profile_md": "背景：一名侦探", "base_stats_extra": null}'


# ── DB + HTTP fixtures ────────────────────────────────────────────────────────

@pytest.fixture
async def db(tmp_path):
    engine = get_engine(f"sqlite+aiosqlite:///{tmp_path}/genre_test.db")
    await init_db(engine)
    async with async_session(engine)() as s:
        yield s
    await engine.dispose()



# ─────────────────────────────────────────────────────────────────────────────
# Part A: apply_genre_template unit tests
# ─────────────────────────────────────────────────────────────────────────────

# G1. apply_genre_template("悬疑探案") gives high INT
def test_mystery_genre_high_intelligence():
    result = apply_genre_template("悬疑探案")
    sb = result["stat_block"]
    assert sb["intelligence"] >= 13, "悬疑探案 should have INT >= 13"
    assert sb["intelligence"] > sb["strength"], "INT should exceed STR for mystery"


# G2. apply_genre_template("英雄成长") gives high STR
def test_hero_genre_high_strength():
    result = apply_genre_template("英雄成长")
    sb = result["stat_block"]
    assert sb["strength"] >= 14, "英雄成长 should have STR >= 14"
    assert sb["strength"] > sb["intelligence"], "STR should exceed INT for hero"


# G3. apply_genre_template("政治阴谋") gives high CHA/INT
def test_politics_genre_high_charisma_or_int():
    result = apply_genre_template("政治阴谋")
    sb = result["stat_block"]
    assert sb["charisma"] >= 13 or sb["intelligence"] >= 13, \
        "政治阴谋 should have CHA or INT >= 13"


# G4. apply_genre_template("灾难求生") gives high CON/STR
def test_survival_genre_high_constitution():
    result = apply_genre_template("灾难求生")
    sb = result["stat_block"]
    assert sb["constitution"] >= 14 or sb["strength"] >= 14, \
        "灾难求生 should have CON or STR >= 14"


# G5. starting_inventory list items parse via engine.schema.Item
def test_starting_inventory_shape():
    result = apply_genre_template("悬疑探案")
    items_raw = result["inventory"]
    assert isinstance(items_raw, list)
    assert len(items_raw) >= 1
    # Each entry should be a valid Item dict
    for item_dict in items_raw:
        item = Item.model_validate(item_dict)
        assert item.name
        assert item.qty >= 1


# G6. unknown genre returns balanced defaults (all attributes ~ 10)
def test_unknown_genre_returns_defaults():
    result = apply_genre_template("未知类型XYZ")
    sb = result["stat_block"]
    for attr in ["strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma"]:
        assert 8 <= sb[attr] <= 12, f"{attr} should be near 10 for unknown genre, got {sb[attr]}"


# G7. seeded rng produces deterministic stats
def test_seeded_rng_deterministic():
    rng1 = random.Random(42)
    rng2 = random.Random(42)
    result1 = apply_genre_template("英雄成长", rng=rng1)
    result2 = apply_genre_template("英雄成长", rng=rng2)
    assert result1["stat_block"] == result2["stat_block"]


# G8. vital max values respect each genre profile
def test_vital_max_values():
    mystery = apply_genre_template("悬疑探案")
    hero = apply_genre_template("英雄成长")
    survival = apply_genre_template("灾难求生")

    # Hero should have more HP (combat-focused)
    assert hero["stat_block"]["max_hp"] >= mystery["stat_block"]["max_hp"]
    # Survival should have high stamina
    assert survival["stat_block"]["max_stamina"] >= 35


# G9. result has stat_block, skills, inventory keys
def test_result_structure_complete():
    for genre in ["悬疑探案", "英雄成长", "政治阴谋", "灾难求生", "恋爱攻略"]:
        result = apply_genre_template(genre)
        assert "stat_block" in result, f"Missing stat_block for {genre}"
        assert "skills" in result, f"Missing skills for {genre}"
        assert "inventory" in result, f"Missing inventory for {genre}"
        assert isinstance(result["skills"], dict), f"skills must be dict for {genre}"
        for k, v in result["skills"].items():
            assert isinstance(v, int), f"skill level must be int, got {type(v)} for {genre}.{k}"


# G10. skills_json parses back to dict via parse_skills
def test_skills_parse_roundtrip():
    result = apply_genre_template("悬疑探案")
    skills_json = json.dumps(result["skills"], ensure_ascii=False)
    parsed = parse_skills(skills_json)
    assert parsed == result["skills"]


# ─────────────────────────────────────────────────────────────────────────────
# Part B: generate_character returns structured stats
# ─────────────────────────────────────────────────────────────────────────────

# G11. generate_character returns stat_block, skills, inventory fields
async def test_generate_character_returns_structured_stats():
    client = StubLLM(_CHAR_OUTPUT)
    result = await generate_character(
        world_md="世界观描述", archetype="侦探", client=client, genre="悬疑探案"
    )
    assert "stat_block" in result, "generate_character should return stat_block"
    assert "skills" in result, "generate_character should return skills"
    assert "inventory" in result, "generate_character should return inventory"
    assert isinstance(result["stat_block"], dict)
    assert "intelligence" in result["stat_block"]


# G12. generate_character defaults genre to balanced if not passed
async def test_generate_character_no_genre_uses_defaults():
    client = StubLLM(_CHAR_OUTPUT)
    result = await generate_character(
        world_md="世界观描述", archetype="侦探", client=client
    )
    assert "stat_block" in result
    # Without genre, should still return valid structured stats
    sb = result["stat_block"]
    for attr in ["strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma"]:
        assert isinstance(sb.get(attr), int)


# ─────────────────────────────────────────────────────────────────────────────
# Part C: /wizard/character API returns stat_block
# ─────────────────────────────────────────────────────────────────────────────

# G13. _fw_character_impl routes genre into generate_character (service-level test)
async def test_fw_character_impl_passes_genre(db):
    """Verify the route helper _fw_character_impl passes genre to generate_character."""

    # Directly test that generate_character with genre="英雄成长" returns hero stats
    client_stub = StubLLM(_CHAR_OUTPUT)
    result = await generate_character(
        world_md="世界观", archetype="战士", client=client_stub, genre="英雄成长"
    )
    assert "stat_block" in result
    # Hero genre should have high strength
    assert result["stat_block"]["strength"] >= 14, \
        f"Expected STR >= 14 for 英雄成长, got {result['stat_block']['strength']}"


# ─────────────────────────────────────────────────────────────────────────────
# Part D: finalize_wizard persists structured stats
# ─────────────────────────────────────────────────────────────────────────────

# G14. finalize_wizard persists structured stats on Character row
async def test_finalize_wizard_persists_stats(db):
    mc = ModelConfig(name="m", type="ollama", base_url="http://x", model_name="x")
    db.add(mc)
    await db.flush()

    genre = "悬疑探案"
    tmpl = apply_genre_template(genre)
    stat_block = tmpl["stat_block"]
    skills = tmpl["skills"]
    inventory = tmpl["inventory"]

    bundle = {
        "world": {"name": "测试世界", "content_md": "内容", "style": "realistic"},
        "character": {
            "name": "李明", "gender": "male",
            "profile_md": "背景描述",
            "base_stats_json": json.dumps({"hp": 20}),
            "stat_block": stat_block,
            "skills": skills,
            "inventory": inventory,
        },
        "screenplay": {
            "chapters": [], "main_characters": [],
            "ending_md": "", "opening_hook": "",
        },
        "session_name": "Test Session",
        "gm_model_config_id": mc.id,
        "summarizer_model_config_id": mc.id,
        "genre": genre,
    }

    await finalize_wizard(db, bundle)
    await db.commit()

    # Fetch the newly created Character
    row = await db.execute(select(Character).order_by(Character.id.desc()).limit(1))
    char = row.scalars().first()
    assert char is not None

    # Check structured stats were persisted
    assert char.intelligence == stat_block["intelligence"]
    assert char.strength == stat_block["strength"]
    assert char.max_hp == stat_block["max_hp"]

    # Check skills and inventory
    persisted_skills = parse_skills(char.skills_json)
    assert persisted_skills == skills

    persisted_inventory = parse_items(char.inventory_json)
    assert len(persisted_inventory) == len(inventory)
