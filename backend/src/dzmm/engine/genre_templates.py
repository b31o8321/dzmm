"""
engine/genre_templates.py — Genre-based stat templates for v0.15 wizard.

GENRE_TEMPLATES: 5 canonical genres with attribute priorities, base stats,
starting skills, and starting inventory (structured Item dicts).

apply_genre_template(genre, *, rng=None) -> dict:
  Returns {stat_block: dict, skills: dict, inventory: list[Item dict]}.
  Unknown genre → balanced defaults (all stats 10, modest vitals).
  Optional rng (random.Random) adds ±2 to each attribute deterministically.
"""

from __future__ import annotations

import random as _random_module
from typing import Any

# ── Templates ─────────────────────────────────────────────────────────────────
#
# stat_base: Six D&D attributes (str/dex/con/int/wis/cha)
# vitals: max_hp, max_sanity, max_stamina
# starting_skills: dict[skill_name, level 0-100]
# starting_inventory: list[Item-compatible dicts]

GENRE_TEMPLATES: dict[str, dict] = {
    "悬疑探案": {
        "attribute_priorities": ["intelligence", "wisdom", "charisma"],
        "stat_base": {
            "strength": 9, "dexterity": 12, "constitution": 10,
            "intelligence": 14, "wisdom": 13, "charisma": 11,
        },
        "vitals": {"max_hp": 24, "max_sanity": 60, "max_stamina": 20},
        "starting_skills": {
            "调查": 50, "察言观色": 45, "搜索": 40,
            "潜行": 25, "说服": 35,
        },
        "starting_inventory": [
            {"name": "侦探笔记本", "qty": 1, "item_type": "quest", "effects": []},
            {"name": "放大镜", "qty": 1, "item_type": "key", "effects": []},
            {"name": "小型治疗药水", "qty": 2, "item_type": "consumable",
             "effects": [{"type": "heal_hp", "amount": 10}]},
        ],
    },

    "英雄成长": {
        "attribute_priorities": ["strength", "constitution", "dexterity"],
        "stat_base": {
            "strength": 15, "dexterity": 13, "constitution": 14,
            "intelligence": 10, "wisdom": 10, "charisma": 10,
        },
        "vitals": {"max_hp": 34, "max_sanity": 40, "max_stamina": 30},
        "starting_skills": {
            "近战": 55, "格挡": 40, "运动": 45,
            "威吓": 30, "求生": 35,
        },
        "starting_inventory": [
            {"name": "铁剑", "qty": 1, "item_type": "weapon",
             "effects": [{"type": "attack_attribute", "stat": "strength"},
                         {"type": "damage", "amount": 6, "formula": "1d8+STR"}]},
            {"name": "皮甲", "qty": 1, "item_type": "armor",
             "effects": [{"type": "armor_bonus", "amount": 2}]},
            {"name": "治疗药剂", "qty": 3, "item_type": "consumable",
             "effects": [{"type": "heal_hp", "amount": 15}]},
        ],
    },

    "政治阴谋": {
        "attribute_priorities": ["charisma", "intelligence", "wisdom"],
        "stat_base": {
            "strength": 9, "dexterity": 11, "constitution": 10,
            "intelligence": 13, "wisdom": 12, "charisma": 15,
        },
        "vitals": {"max_hp": 20, "max_sanity": 50, "max_stamina": 18},
        "starting_skills": {
            "说服": 55, "欺骗": 50, "洞察": 45,
            "历史": 40, "政治": 50,
        },
        "starting_inventory": [
            {"name": "密函", "qty": 1, "item_type": "quest", "effects": []},
            {"name": "印章戒指", "qty": 1, "item_type": "key", "effects": []},
            {"name": "毒药（少量）", "qty": 1, "item_type": "consumable",
             "effects": [{"type": "damage", "amount": 5}]},
        ],
    },

    "灾难求生": {
        "attribute_priorities": ["constitution", "strength", "dexterity"],
        "stat_base": {
            "strength": 13, "dexterity": 13, "constitution": 15,
            "intelligence": 10, "wisdom": 11, "charisma": 8,
        },
        "vitals": {"max_hp": 30, "max_sanity": 35, "max_stamina": 40},
        "starting_skills": {
            "求生": 60, "医疗": 40, "运动": 50,
            "潜行": 35, "搜索": 40,
        },
        "starting_inventory": [
            {"name": "急救包", "qty": 2, "item_type": "consumable",
             "effects": [{"type": "heal_hp", "amount": 20}]},
            {"name": "求生刀", "qty": 1, "item_type": "weapon",
             "effects": [{"type": "attack_attribute", "stat": "dexterity"},
                         {"type": "damage", "amount": 4, "formula": "1d4+DEX"}]},
            {"name": "绳索", "qty": 1, "item_type": "key", "effects": []},
            {"name": "净水片", "qty": 5, "item_type": "consumable",
             "effects": [{"type": "heal_stamina", "amount": 5}]},
        ],
    },

    "恋爱攻略": {
        "attribute_priorities": ["charisma", "wisdom", "dexterity"],
        "stat_base": {
            "strength": 8, "dexterity": 12, "constitution": 10,
            "intelligence": 11, "wisdom": 13, "charisma": 15,
        },
        "vitals": {"max_hp": 20, "max_sanity": 55, "max_stamina": 22},
        "starting_skills": {
            "魅力": 60, "察言观色": 50, "说服": 45,
            "表演": 40, "烹饪": 30,
        },
        "starting_inventory": [
            {"name": "精致礼物", "qty": 1, "item_type": "quest", "effects": []},
            {"name": "情书草稿", "qty": 3, "item_type": "quest", "effects": []},
            {"name": "香水", "qty": 1, "item_type": "consumable",
             "effects": [{"type": "stat_bonus", "stat": "charisma", "amount": 2, "duration_turns": 3}]},
        ],
    },
}

# Balanced defaults for unknown genres
_DEFAULTS: dict = {
    "attribute_priorities": [],
    "stat_base": {
        "strength": 10, "dexterity": 10, "constitution": 10,
        "intelligence": 10, "wisdom": 10, "charisma": 10,
    },
    "vitals": {"max_hp": 25, "max_sanity": 45, "max_stamina": 25},
    "starting_skills": {
        "察言观色": 30, "搜索": 30, "说服": 25,
    },
    "starting_inventory": [
        {"name": "简单补给包", "qty": 1, "item_type": "consumable",
         "effects": [{"type": "heal_hp", "amount": 10}]},
    ],
}


def apply_genre_template(genre: str, *, rng: _random_module.Random | None = None) -> dict[str, Any]:
    """Return {stat_block: dict, skills: dict, inventory: list[Item dict]}.

    stat_block includes six attributes + max_hp / max_sanity / max_stamina.
    If rng is provided, each attribute is randomized ±2 (deterministic via seed).
    Unknown genre returns balanced defaults (all stats ~10).
    """
    tmpl = GENRE_TEMPLATES.get(genre, _DEFAULTS)

    # Build attribute dict with optional ±2 jitter
    stat_base: dict[str, int] = dict(tmpl["stat_base"])
    if rng is not None:
        for attr in list(stat_base.keys()):
            stat_base[attr] += rng.randint(-2, 2)
            # Clamp to valid range [3, 20]
            stat_base[attr] = max(3, min(20, stat_base[attr]))

    vitals: dict[str, int] = dict(tmpl["vitals"])

    stat_block: dict[str, int] = {**stat_base, **vitals}

    skills: dict[str, int] = dict(tmpl["starting_skills"])
    inventory: list[dict] = list(tmpl["starting_inventory"])

    return {
        "stat_block": stat_block,
        "skills": skills,
        "inventory": inventory,
    }
