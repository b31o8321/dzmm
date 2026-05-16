"""
engine/schema.py — Pydantic models for the v0.15 Python-first mechanical engine.

StatBlock: D&D-style 6 attributes + 3 vitals max values (stored on Character).
Skill:     Name + level (0-100), CoC-style.
ItemEffect: Discriminated by 'type'; shapes documented below.
Item:       Named item with qty, type, effects list.

Helpers:
  parse_skills(json_str) -> dict[str, int]  — safe parse, {} on error
  parse_items(json_str)  -> list[Item]      — safe parse, [] on error
"""

from __future__ import annotations

import json
import logging
from typing import Literal

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class StatBlock(BaseModel):
    """Six D&D-style attributes (3-18 range) plus max vitals stored on Character."""
    strength: int = Field(10, ge=1, le=30)
    dexterity: int = Field(10, ge=1, le=30)
    constitution: int = Field(10, ge=1, le=30)
    intelligence: int = Field(10, ge=1, le=30)
    wisdom: int = Field(10, ge=1, le=30)
    charisma: int = Field(10, ge=1, le=30)
    max_hp: int = Field(30, ge=1)
    max_sanity: int = Field(50, ge=1)
    max_stamina: int = Field(30, ge=1)


class Skill(BaseModel):
    """CoC-style skill: name + level 0-100."""
    name: str
    level: int = Field(0, ge=0, le=100)
    description: str = ""


class ItemEffect(BaseModel):
    """A single effect a item can produce when used."""
    type: Literal[
        "heal_hp",
        "heal_sanity",
        "heal_stamina",
        "damage",
        "stat_bonus",
        "skill_bonus",
        "consume",
        "unlock",
    ]
    amount: int = 0               # for heal_hp / heal_sanity / heal_stamina / damage
    stat: str | None = None       # for stat_bonus: which attribute name
    skill: str | None = None      # for skill_bonus: which skill name
    duration_turns: int = 0       # 0 = instant; >0 = lasts N turns


class Item(BaseModel):
    """An item in a character's inventory."""
    name: str
    qty: int = 1
    item_type: Literal["weapon", "armor", "consumable", "key", "quest"]
    effects: list[ItemEffect] = []
    description: str = ""


# ── Safe parse helpers ────────────────────────────────────────────────────────

def parse_skills(json_str: str) -> dict[str, int]:
    """Parse skills_json column into dict[str, int].

    Returns {} on any error (malformed JSON, wrong shape, etc.).
    """
    try:
        data = json.loads(json_str)
        if not isinstance(data, dict):
            return {}
        return {k: int(v) for k, v in data.items() if isinstance(v, (int, float))}
    except Exception:
        logger.warning("parse_skills: failed to parse %r, returning {}", json_str[:80])
        return {}


def parse_items(json_str: str) -> list[Item]:
    """Parse inventory_json column into list[Item].

    Returns [] on any error (malformed JSON, validation failures, etc.).
    """
    try:
        data = json.loads(json_str)
        if not isinstance(data, list):
            return []
        items: list[Item] = []
        for raw in data:
            try:
                items.append(Item.model_validate(raw))
            except Exception:
                logger.warning("parse_items: skipping invalid item %r", raw)
        return items
    except Exception:
        logger.warning("parse_items: failed to parse JSON, returning []")
        return []
