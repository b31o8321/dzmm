"""Tests for engine/items.py — resolve_use_item, add_item_to_inventory,
remove_item_from_inventory."""

import json

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.db.base import async_session, get_engine, init_db
from dzmm.db.models import Character, CharState, ModelConfig, Session as GameSession, World
from dzmm.engine.items import (
    add_item_to_inventory,
    remove_item_from_inventory,
    resolve_use_item,
)
from dzmm.engine.schema import Item, ItemEffect, parse_items


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
async def db(tmp_path):
    engine = get_engine(f"sqlite+aiosqlite:///{tmp_path}/items_test.db")
    await init_db(engine)
    async with async_session(engine)() as s:
        yield s
    await engine.dispose()


async def _make_scenario(s: AsyncSession, inventory_items=None):
    """Create a minimal World / Character / CharState / Session setup."""
    world = World(name="W", content_md="x", style="realistic")
    s.add(world)
    await s.flush()

    if inventory_items is None:
        inventory_items = []

    inv_json = json.dumps([i.model_dump() for i in inventory_items])

    char = Character(
        world_id=world.id,
        name="PC",
        profile_md="x",
        base_stats_json="{}",
        max_hp=30,
        max_sanity=50,
        max_stamina=30,
        inventory_json=inv_json,
    )
    s.add(char)

    cfg = ModelConfig(name="m", type="ollama", base_url="http://localhost", model_name="test")
    s.add(cfg)
    await s.flush()

    sess = GameSession(
        name="run",
        world_id=world.id,
        character_id=char.id,
        gm_model_config_id=cfg.id,
        summarizer_model_config_id=cfg.id,
    )
    s.add(sess)
    await s.flush()

    state = CharState(
        session_id=sess.id,
        stats_json=json.dumps({"hp": 20, "sanity": 40}),
        stamina=20,
    )
    s.add(state)
    await s.commit()
    return char, sess, state


def _potion(qty=1):
    return Item(
        name="Health Potion",
        qty=qty,
        item_type="consumable",
        effects=[ItemEffect(type="heal_hp", amount=10)],
    )


def _key():
    return Item(name="Iron Key", qty=1, item_type="key")


# ── resolve_use_item ──────────────────────────────────────────────────────────

async def test_resolve_use_item_heals_hp(db):
    char, sess, state = await _make_scenario(db, [_potion()])
    result = await resolve_use_item(db, sess.id, char.id, "Health Potion")
    # HP started at 20, healed 10 → 30 (capped at max_hp=30)
    applied = result["applied_effects"]
    assert any(e["type"] == "heal_hp" for e in applied)


async def test_resolve_use_item_consumable_decrements(db):
    char, sess, _ = await _make_scenario(db, [_potion(qty=3)])
    await resolve_use_item(db, sess.id, char.id, "Health Potion")
    await db.refresh(char)
    items = parse_items(char.inventory_json)
    assert len(items) == 1
    assert items[0].qty == 2


async def test_resolve_use_item_removes_when_qty_hits_zero(db):
    char, sess, _ = await _make_scenario(db, [_potion(qty=1)])
    result = await resolve_use_item(db, sess.id, char.id, "Health Potion")
    assert result["removed_from_inventory"] is True
    await db.refresh(char)
    items = parse_items(char.inventory_json)
    assert len(items) == 0


async def test_resolve_use_item_raises_on_unknown_item(db):
    char, sess, _ = await _make_scenario(db, [])
    with pytest.raises(ValueError, match="not found"):
        await resolve_use_item(db, sess.id, char.id, "Nonexistent Sword")


async def test_resolve_use_item_non_consumable_decrements(db):
    """Non-consumable items also lose qty on use (decrement, not necessarily removed)."""
    sword = Item(name="Sword", qty=2, item_type="weapon")
    char, sess, _ = await _make_scenario(db, [sword])
    result = await resolve_use_item(db, sess.id, char.id, "Sword")
    assert result["removed_from_inventory"] is False
    await db.refresh(char)
    items = parse_items(char.inventory_json)
    assert items[0].qty == 1


# ── add_item_to_inventory ─────────────────────────────────────────────────────

async def test_add_item_new(db):
    char, _, _ = await _make_scenario(db, [])
    await add_item_to_inventory(db, char.id, _key())
    await db.refresh(char)
    items = parse_items(char.inventory_json)
    assert len(items) == 1
    assert items[0].name == "Iron Key"


async def test_add_item_merges_qty_on_same_name_and_type(db):
    char, _, _ = await _make_scenario(db, [_potion(qty=2)])
    await add_item_to_inventory(db, char.id, _potion(qty=3))
    await db.refresh(char)
    items = parse_items(char.inventory_json)
    # Should merge to qty=5, not create a second entry
    assert len(items) == 1
    assert items[0].qty == 5


async def test_add_item_different_type_not_merged(db):
    """Same name but different type should NOT merge."""
    key1 = Item(name="Key", qty=1, item_type="key")
    key2 = Item(name="Key", qty=1, item_type="quest")
    char, _, _ = await _make_scenario(db, [key1])
    await add_item_to_inventory(db, char.id, key2)
    await db.refresh(char)
    items = parse_items(char.inventory_json)
    assert len(items) == 2


# ── remove_item_from_inventory ────────────────────────────────────────────────

async def test_remove_item_success(db):
    char, _, _ = await _make_scenario(db, [_potion(qty=3)])
    ok = await remove_item_from_inventory(db, char.id, "Health Potion", qty=2)
    assert ok is True
    await db.refresh(char)
    items = parse_items(char.inventory_json)
    assert items[0].qty == 1


async def test_remove_item_returns_false_when_not_enough(db):
    char, _, _ = await _make_scenario(db, [_potion(qty=1)])
    ok = await remove_item_from_inventory(db, char.id, "Health Potion", qty=5)
    assert ok is False
    # inventory unchanged
    await db.refresh(char)
    items = parse_items(char.inventory_json)
    assert items[0].qty == 1


async def test_remove_item_not_found_returns_false(db):
    char, _, _ = await _make_scenario(db, [])
    ok = await remove_item_from_inventory(db, char.id, "Ghost Item")
    assert ok is False


async def test_remove_item_removes_when_qty_reaches_zero(db):
    char, _, _ = await _make_scenario(db, [_potion(qty=1)])
    ok = await remove_item_from_inventory(db, char.id, "Health Potion", qty=1)
    assert ok is True
    await db.refresh(char)
    items = parse_items(char.inventory_json)
    assert len(items) == 0
