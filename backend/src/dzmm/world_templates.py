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


def clocktower_mystery_template() -> dict[str, Any]:
    """Deduction preset: 钟楼谜案 — clue collection and accusation. (v1.6.0)"""
    return {
        "world_definition": {
            "schema_version": 3,
            "name": "钟楼谜案",
            "lorebook": {"entries": []},
            "character_cards": [],
            "locations": [
                {"id": "manor-hall", "name": "宅邸大厅"},
                {"id": "clockwork-tower", "name": "钟楼机房"},
                {"id": "old-chapel", "name": "旧礼拜堂"},
            ],
            "factions": [{"id": "manor-staff", "name": "宅邸仆从"}],
            "npcs": [
                {"id": "butler-graves", "name": "管家格雷夫斯", "location_id": "manor-hall"},
                {"id": "watchmaker-isa", "name": "钟表匠伊莎", "location_id": "clockwork-tower"},
                {"id": "sister-maren", "name": "玛伦嬷嬷", "location_id": "old-chapel"},
            ],
            "events": [],
            "resources": [{"id": "magnifier", "name": "黄铜放大镜"}],
            "ruleset": {
                "id": "hybrid",
                "enabled_capabilities": [
                    "trpg", "resources", "deduction",
                    "chapters", "choices", "relationships", "routes", "endings",
                ],
            },
            "mystery": {
                "culprit_id": "butler-graves",
                "required_clues": ["stopped-pendulum", "borrowed-key"],
                "max_accusations": 2,
                "wrong_accusation_ending_id": "scapegoat",
            },
            "story": {
                "chapters": [
                    {
                        "id": "ch1",
                        "title": "停摆的钟",
                        "order": 1,
                        "next_chapter_id": None,
                        "choices": [
                            {"id": "inspect-tower", "label": "检查钟楼机房",
                             "effects": [{"type": "set_story_flag", "flag_id": "tower-inspected", "value": True}]},
                            {"id": "question-staff", "label": "盘问仆从",
                             "effects": [{"type": "set_story_flag", "flag_id": "staff-questioned", "value": True}]},
                        ],
                    }
                ],
                "flags": [
                    {"id": "tower-inspected", "default": False, "writers": ["choice:inspect-tower"]},
                    {"id": "staff-questioned", "default": False, "writers": ["choice:question-staff"]},
                ],
                "relationships": [],
                "relationship_events": [],
                "routes": [],
                "endings": [
                    {"id": "case-closed", "kind": "good", "priority": 100,
                     "narrative_key": "ending.case_closed",
                     "title": "真相收网", "epitaph": "钟声再度响起。",
                     "when": {"flag": "__accusation_correct__", "equals": True}},
                    {"id": "scapegoat", "kind": "bad", "priority": 60,
                     "narrative_key": "ending.wrong_accusation",
                     "title": "替罪之火", "epitaph": "真凶仍在暗处。",
                     "when": {"flag": "__never__", "equals": True}},
                ],
            },
        },
        "hero": {"name": "顾问侦探", "profile": {"origin": " CID 顾问"}},
    }


def ember_cellar_template() -> dict[str, Any]:
    """Roguelike preset: 烬火地窖 — death carries boons into the next run. (v1.6.0)"""
    return {
        "world_definition": {
            "schema_version": 3,
            "name": "烬火地窖",
            "lorebook": {"entries": []},
            "character_cards": [],
            "locations": [
                {"id": "gate-hall", "name": "门厅"},
                {"id": "cinder-shrine", "name": "烬火神龛"},
                {"id": "rat-warren", "name": "鼠人巢穴"},
            ],
            "factions": [{"id": "rat-clan", "name": "鼠人部族"}],
            "npcs": [
                {"id": "shrine-keeper", "name": "守龛人", "location_id": "cinder-shrine"},
                {"id": "rat-elder", "name": "鼠人长老", "location_id": "rat-warren"},
            ],
            "events": [],
            "resources": [{"id": "torch", "name": "火把"}],
            "ruleset": {
                "id": "hybrid",
                "enabled_capabilities": [
                    "trpg", "resources", "roguelike",
                    "chapters", "choices", "relationships", "routes", "endings",
                ],
            },
            "legacy_config": {
                "boons": [
                    {"id": "ember-charm", "label": "烬火护符：首击伤害 +2"},
                    {"id": "rat-tome", "label": "鼠人典籍：解锁地下暗语"},
                    {"id": "iron-ration", "label": "铁壁干粮：起始补给翻倍"},
                ],
            },
            "story": {
                "chapters": [
                    {
                        "id": "ch1",
                        "title": "下潜",
                        "order": 1,
                        "next_chapter_id": None,
                        "choices": [
                            {"id": "descend-gate", "label": "穿过门厅下潜",
                             "effects": [{"type": "set_story_flag", "flag_id": "descended", "value": True}]},
                            {"id": "pray-shrine", "label": "向烬火神龛祈祷",
                             "effects": [{"type": "set_story_flag", "flag_id": "blessed", "value": True}]},
                        ],
                    }
                ],
                "flags": [
                    {"id": "descended", "default": False, "writers": ["choice:descend-gate"]},
                    {"id": "blessed", "default": False, "writers": ["choice:pray-shrine"]},
                ],
                "relationships": [],
                "relationship_events": [],
                "routes": [],
                "endings": [
                    {"id": "bottom-reached", "kind": "good", "priority": 100,
                     "narrative_key": "ending.bottom_reached",
                     "title": "触及烬火", "epitaph": "地窖的心跳与你同频。",
                     "when": {"flag": "descended", "equals": True}},
                    {"id": "ash-fallen", "kind": "bad", "priority": 50,
                     "narrative_key": "ending.ash_fallen",
                     "title": "灰烬长眠", "epitaph": "下一人将带着你的余温下潜。",
                     "when": {"flag": "blessed", "equals": True}},
                ],
            },
        },
        "hero": {"name": "下潜者", "profile": {"origin": "流放的掘宝人"}},
    }
