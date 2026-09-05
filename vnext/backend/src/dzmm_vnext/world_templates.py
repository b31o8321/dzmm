from __future__ import annotations

from copy import deepcopy
from typing import Any


def fog_harbor_template() -> dict[str, Any]:
    """Return the native, deterministic sample for the story-and-relationship slice."""
    definition = {
        "schema_version": 3,
        "name": "雾港",
        "lorebook": {
            "entries": [
                {
                    "id": "gray-tide",
                    "title": "灰潮",
                    "body": "雾港的潮水会吞没失约者。",
                    "activation": "always",
                    "priority": 90,
                }
            ]
        },
        "character_cards": [
            {
                "id": "lan",
                "name": "岚",
                "format": "native",
            },
            {
                "id": "shen_yan",
                "name": "沈砚",
                "format": "native",
            },
        ],
        "locations": [
            {"id": "harbor", "name": "雾港码头"},
            {"id": "lighthouse", "name": "旧灯塔"},
        ],
        "factions": [],
        "npcs": [],
        "events": [],
        "resources": [{"id": "fog-lantern", "name": "雾灯"}],
        "ruleset": {
            "id": "hybrid",
            "enabled_capabilities": [
                "chapters",
                "choices",
                "relationships",
                "routes",
                "endings",
                "resources",
            ],
        },
        "story": {
            "flags": [
                {"id": "lan-rescued", "default": False, "writers": ["choice:rescue-lan"]},
                {
                    "id": "chart-recovered",
                    "default": False,
                    "writers": ["choice:rescue-lan", "choice:hide-chart"],
                },
                {"id": "lan-kept-faith", "default": False, "writers": ["choice:lan-testimony"]},
                {"id": "shen-confessed", "default": False, "writers": ["choice:shen-confession"]},
                {"id": "heard-the-bell", "default": False, "writers": ["choice:unite-witnesses"]},
                {"id": "tide-gate-opened", "default": False, "writers": ["choice:open-tide-gate"]},
                {"id": "tide-gate-failed", "default": False, "writers": ["choice:miss-the-tide"]},
            ],
            "relationships": [
                {
                    "id": "lan",
                    "character_card_id": "lan",
                    "dimensions": {
                        "affection": {"initial": 40, "min": 0, "max": 100},
                        "trust": {"initial": 0, "min": -100, "max": 100},
                    },
                },
                {
                    "id": "shen_yan",
                    "character_card_id": "shen_yan",
                    "dimensions": {
                        "affection": {"initial": 40, "min": 0, "max": 100},
                        "trust": {"initial": 0, "min": -100, "max": 100},
                    },
                },
            ],
            "relationship_events": [
                {
                    "id": "lan-rescued",
                    "relationship_id": "lan",
                    "deltas": {"affection": 5, "trust": 20},
                    "reason_key": "relation.lan.rescued",
                    "once_scope": "run",
                    "cooldown_turns": 0,
                },
                {
                    "id": "lan-truth",
                    "relationship_id": "lan",
                    "deltas": {"trust": 20},
                    "reason_key": "relation.lan.truth",
                    "once_scope": "run",
                    "cooldown_turns": 0,
                },
                {
                    "id": "shen-protected",
                    "relationship_id": "shen_yan",
                    "deltas": {"affection": 8, "trust": 15},
                    "reason_key": "relation.shen.protected",
                    "once_scope": "run",
                    "cooldown_turns": 0,
                },
                {
                    "id": "shen-confession",
                    "relationship_id": "shen_yan",
                    "deltas": {"affection": 10, "trust": 25},
                    "reason_key": "relation.shen.confession",
                    "once_scope": "run",
                    "cooldown_turns": 0,
                },
                {
                    "id": "lan-shared-testimony",
                    "relationship_id": "lan",
                    "deltas": {"trust": 40},
                    "reason_key": "relation.lan.shared_testimony",
                    "once_scope": "run",
                    "cooldown_turns": 0,
                },
                {
                    "id": "shen-shared-testimony",
                    "relationship_id": "shen_yan",
                    "deltas": {"trust": 60},
                    "reason_key": "relation.shen.shared_testimony",
                    "once_scope": "run",
                    "cooldown_turns": 0,
                },
            ],
            "routes": [
                {"id": "lan-route", "name": "岚路线"},
                {"id": "shen-route", "name": "沈砚路线"},
                {"id": "neutral-route", "name": "中立路线"},
            ],
            "chapters": [
                {
                    "id": "ch1",
                    "title": "潮雾抵港",
                    "order": 1,
                    "next_chapter_id": "ch2",
                    "choices": [
                        {
                            "id": "rescue-lan",
                            "label": "救岚",
                            "effects": [
                                {"type": "set_story_flag", "flag_id": "lan-rescued", "value": True},
                                {"type": "set_story_flag", "flag_id": "chart-recovered", "value": True},
                                {"type": "grant_resource", "resource_id": "fog-lantern", "quantity": 1},
                                {"type": "apply_relationship_event", "relationship_event_id": "lan-rescued"},
                            ],
                        },
                        {
                            "id": "hide-chart",
                            "label": "替沈砚藏起航图",
                            "effects": [
                                {"type": "set_story_flag", "flag_id": "chart-recovered", "value": True},
                                {"type": "grant_resource", "resource_id": "fog-lantern", "quantity": 1},
                                {"type": "apply_relationship_event", "relationship_event_id": "shen-protected"},
                            ],
                        },
                    ],
                },
                {
                    "id": "ch2",
                    "title": "沉船的证词",
                    "order": 2,
                    "next_chapter_id": "ch3",
                    "choices": [
                        {
                            "id": "lan-testimony",
                            "label": "把证词交给岚",
                            "effects": [
                                {"type": "set_story_flag", "flag_id": "lan-kept-faith", "value": True},
                                {"type": "set_route", "route_id": "lan-route"},
                                {"type": "apply_relationship_event", "relationship_event_id": "lan-truth"},
                            ],
                        },
                        {
                            "id": "shen-confession",
                            "label": "帮助沈砚坦白",
                            "effects": [
                                {"type": "set_story_flag", "flag_id": "shen-confessed", "value": True},
                                {"type": "set_route", "route_id": "shen-route"},
                                {"type": "apply_relationship_event", "relationship_event_id": "shen-confession"},
                            ],
                        },
                        {
                            "id": "neutral-lead",
                            "label": "独自追查潮门",
                            "effects": [{"type": "set_route", "route_id": "neutral-route"}],
                        },
                        {
                            "id": "unite-witnesses",
                            "label": "让岚与沈砚共同作证",
                            "effects": [
                                {"type": "set_story_flag", "flag_id": "heard-the-bell", "value": True},
                                {"type": "set_route", "route_id": "neutral-route"},
                                {
                                    "type": "apply_relationship_event",
                                    "relationship_event_id": "lan-shared-testimony",
                                },
                                {
                                    "type": "apply_relationship_event",
                                    "relationship_event_id": "shen-shared-testimony",
                                },
                            ],
                        },
                    ],
                },
                {
                    "id": "ch3",
                    "title": "潮门之夜",
                    "order": 3,
                    "next_chapter_id": None,
                    "choices": [
                        {
                            "id": "open-tide-gate",
                            "label": "点亮雾灯",
                            "effects": [{"type": "set_story_flag", "flag_id": "tide-gate-opened", "value": True}],
                        },
                        {
                            "id": "miss-the-tide",
                            "label": "错失潮门",
                            "effects": [{"type": "set_story_flag", "flag_id": "tide-gate-failed", "value": True}],
                        },
                    ],
                },
            ],
            "endings": [
                {
                    "id": "bell-beyond-fog",
                    "kind": "hidden",
                    "priority": 120,
                    "narrative_key": "ending.bell",
                    "when": {
                        "all": [
                            {"flag": "tide-gate-opened", "equals": True},
                            {"flag": "heard-the-bell", "equals": True},
                            {"relationship": "lan", "dimension": "trust", "at_least": 60},
                            {
                                "relationship": "shen_yan",
                                "dimension": "trust",
                                "at_least": 60,
                            },
                        ]
                    },
                },
                {
                    "id": "lan-dawn",
                    "kind": "good",
                    "priority": 100,
                    "narrative_key": "ending.lan_dawn",
                    "when": {
                        "all": [
                            {"flag": "tide-gate-opened", "equals": True},
                            {"route": "lan-route"},
                            {"relationship": "lan", "dimension": "trust", "at_least": 40},
                            {"relationship": "lan", "dimension": "affection", "at_least": 45},
                        ]
                    },
                },
                {
                    "id": "shen-low-tide",
                    "kind": "good",
                    "priority": 95,
                    "narrative_key": "ending.shen_low_tide",
                    "when": {
                        "all": [
                            {"flag": "tide-gate-opened", "equals": True},
                            {"route": "shen-route"},
                            {"relationship": "shen_yan", "dimension": "trust", "at_least": 40},
                        ]
                    },
                },
                {
                    "id": "neutral-harbor",
                    "kind": "normal",
                    "priority": 50,
                    "narrative_key": "ending.neutral",
                    "when": {"flag": "tide-gate-opened", "equals": True},
                },
                {
                    "id": "fog-drowned",
                    "kind": "bad",
                    "priority": 0,
                    "narrative_key": "ending.fog_drowned",
                    "when": {"flag": "tide-gate-failed", "equals": True},
                },
            ],
        },
    }
    return {"world_definition": deepcopy(definition), "hero": {"name": "米拉", "profile": {"origin": "水手"}}}


def d20_frontier_template() -> dict[str, Any]:
    """Return the deterministic d20-style TRPG sample exercising the combat capability.

    Combat numbers come from ``ruleset.combat_rules`` overrides merged over the
    engine defaults; the wounded scout keeps definition-level stats empty to
    show plain NPCs fall back to role defaults.
    """

    definition = {
        "schema_version": 3,
        "name": "D20 边境前哨",
        "lorebook": {
            "entries": [
                {
                    "id": "frontier-law",
                    "title": "边境法则",
                    "body": "废墟的主人在夜里巡猎，火光是唯一的谈判筹码。",
                    "activation": "always",
                    "priority": 90,
                }
            ]
        },
        "character_cards": [],
        "locations": [
            {"id": "camp", "name": "边境营地"},
            {"id": "ruins", "name": "哨塔废墟"},
        ],
        "factions": [],
        "npcs": [
            {
                "id": "goblin-chief",
                "name": "哥布林头目",
                "location_id": "ruins",
                "combat": {"max_hp": 14, "ac": 12, "attack_bonus": 3, "damage": {"count": 1, "sides": 6, "bonus": 1}},
            },
            {"id": "wounded-scout", "name": "受伤的斥候", "location_id": "camp"},
        ],
        "events": [],
        "resources": [
            {"id": "healing-herb", "name": "治疗草药"},
            {"id": "iron-sword", "name": "铁剑"},
        ],
        "ruleset": {
            "id": "hybrid",
            "enabled_capabilities": [
                "trpg",
                "combat",
                "chapters",
                "choices",
                "endings",
                "resources",
            ],
            "combat_rules": {
                "hero": {
                    "max_hp": 22,
                    "ac": 13,
                    "attack_bonus": 4,
                    "damage": {"count": 1, "sides": 10, "bonus": 2},
                }
            },
        },
        "story": {
            "flags": [
                {"id": "chief-confronted", "default": False, "writers": ["choice:confront-chief"]},
                {"id": "ruins-avoided", "default": False, "writers": ["choice:avoid-ruins"]},
            ],
            "relationships": [],
            "relationship_events": [],
            "routes": [],
            "chapters": [
                {
                    "id": "ch1",
                    "title": "哨塔废墟之夜",
                    "order": 1,
                    "next_chapter_id": None,
                    "choices": [
                        {
                            "id": "confront-chief",
                            "label": "夜袭废墟，正面迎战头目",
                            "effects": [{"type": "set_story_flag", "flag_id": "chief-confronted", "value": True}],
                        },
                        {
                            "id": "avoid-ruins",
                            "label": "护送斥候，绕开废墟",
                            "effects": [{"type": "set_story_flag", "flag_id": "ruins-avoided", "value": True}],
                        },
                    ],
                }
            ],
            "endings": [
                {
                    "id": "chief-felled",
                    "kind": "good",
                    "priority": 100,
                    "narrative_key": "ending.chief_felled",
                    "when": {"flag": "chief-confronted", "equals": True},
                },
                {
                    "id": "quiet-frontier",
                    "kind": "normal",
                    "priority": 50,
                    "narrative_key": "ending.quiet_frontier",
                    "when": {"flag": "ruins-avoided", "equals": True},
                },
            ],
        },
    }
    return {
        "world_definition": deepcopy(definition),
        "hero": {"name": "艾登", "profile": {"origin": "frontier-scout"}, "combat": {"max_hp": 22}},
    }
