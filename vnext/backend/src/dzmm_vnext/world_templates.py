from __future__ import annotations

from copy import deepcopy
from typing import Any


def fog_harbor_template() -> dict[str, Any]:
    """Return the native, deterministic sample for the story-and-relationship slice."""
    definition = {
        "schema_version": 2,
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
                "relationship_dimensions": {"affection": 40, "trust": 0},
            },
            {
                "id": "shen_yan",
                "name": "沈砚",
                "format": "native",
                "relationship_dimensions": {"affection": 40, "trust": 0},
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
                {"id": "tide-gate-opened", "default": False, "writers": ["choice:open-tide-gate"]},
                {"id": "tide-gate-failed", "default": False, "writers": ["choice:miss-the-tide"]},
            ],
            "relationship_events": [
                {
                    "id": "lan-rescued",
                    "character_card_id": "lan",
                    "deltas": {"affection": 5, "trust": 20},
                    "reason_key": "relation.lan.rescued",
                    "once_scope": "run",
                    "cooldown_turns": 0,
                },
                {
                    "id": "lan-truth",
                    "character_card_id": "lan",
                    "deltas": {"trust": 20},
                    "reason_key": "relation.lan.truth",
                    "once_scope": "run",
                    "cooldown_turns": 0,
                },
                {
                    "id": "shen-protected",
                    "character_card_id": "shen_yan",
                    "deltas": {"affection": 8, "trust": 15},
                    "reason_key": "relation.shen.protected",
                    "once_scope": "run",
                    "cooldown_turns": 0,
                },
                {
                    "id": "shen-confession",
                    "character_card_id": "shen_yan",
                    "deltas": {"affection": 10, "trust": 25},
                    "reason_key": "relation.shen.confession",
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
