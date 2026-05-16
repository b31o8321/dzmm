"""Tests for engine/schema.py — StatBlock, Item, ItemEffect, parse_* helpers."""

import pytest
from pydantic import ValidationError

from dzmm.engine.schema import (
    Item,
    ItemEffect,
    StatBlock,
    parse_items,
    parse_skills,
)


# ── StatBlock ─────────────────────────────────────────────────────────────────

def test_statblock_defaults():
    sb = StatBlock()
    assert sb.strength == 10
    assert sb.max_hp == 30
    assert sb.max_sanity == 50
    assert sb.max_stamina == 30


def test_statblock_rejects_strength_zero():
    with pytest.raises(ValidationError):
        StatBlock(strength=0)


def test_statblock_rejects_strength_too_high():
    with pytest.raises(ValidationError):
        StatBlock(strength=50)


def test_statblock_rejects_max_hp_zero():
    with pytest.raises(ValidationError):
        StatBlock(max_hp=0)


def test_statblock_accepts_boundary_values():
    sb = StatBlock(strength=1, charisma=30, max_hp=1)
    assert sb.strength == 1
    assert sb.charisma == 30


# ── Item ─────────────────────────────────────────────────────────────────────

def test_item_rejects_unknown_item_type():
    with pytest.raises(ValidationError):
        Item(name="sword", item_type="magic_scroll")


def test_item_valid_types():
    for t in ("weapon", "armor", "consumable", "key", "quest"):
        i = Item(name="x", item_type=t)
        assert i.item_type == t


# ── ItemEffect ────────────────────────────────────────────────────────────────

def test_itemeffect_rejects_unknown_type():
    with pytest.raises(ValidationError):
        ItemEffect(type="explode")


def test_itemeffect_valid_types():
    for t in ("heal_hp", "heal_sanity", "heal_stamina", "damage",
              "stat_bonus", "skill_bonus", "consume", "unlock"):
        e = ItemEffect(type=t)
        assert e.type == t


# ── parse_skills ──────────────────────────────────────────────────────────────

def test_parse_skills_normal():
    result = parse_skills('{"Dodge": 40, "Stealth": 60}')
    assert result == {"Dodge": 40, "Stealth": 60}


def test_parse_skills_empty_object():
    assert parse_skills("{}") == {}


def test_parse_skills_malformed_json():
    assert parse_skills("not json") == {}


def test_parse_skills_wrong_type():
    assert parse_skills("[1,2,3]") == {}


# ── parse_items ───────────────────────────────────────────────────────────────

def test_parse_items_normal():
    raw = '[{"name": "Potion", "qty": 2, "item_type": "consumable"}]'
    items = parse_items(raw)
    assert len(items) == 1
    assert items[0].name == "Potion"
    assert items[0].qty == 2


def test_parse_items_empty_array():
    assert parse_items("[]") == []


def test_parse_items_malformed_json():
    assert parse_items("{bad json}") == []


def test_parse_items_wrong_top_level_type():
    assert parse_items('{"name": "x"}') == []


def test_parse_items_skips_invalid_items():
    raw = '[{"name": "ok", "qty": 1, "item_type": "weapon"}, {"name": "bad", "item_type": "INVALID"}]'
    items = parse_items(raw)
    assert len(items) == 1
    assert items[0].name == "ok"
