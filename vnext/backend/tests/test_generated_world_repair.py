import json
from copy import deepcopy

from dzmm_vnext.generated_world_repair import (
    map_to_safe_story_skeleton,
    repair_generated_definition,
)
from dzmm_vnext.story_beats import build_opening_story_beat
from dzmm_vnext.world_templates import fog_harbor_template


def test_generated_definition_repairs_only_derivable_links_on_a_copy() -> None:
    definition = deepcopy(fog_harbor_template()["world_definition"])
    first_chapter = definition["story"]["chapters"][0]
    first_relationship = definition["story"]["relationships"][0]
    first_chapter.pop("order")
    first_chapter.pop("next_chapter_id")
    first_relationship.pop("character_card_id")

    repaired, repairs = repair_generated_definition(definition)

    assert "order" not in first_chapter
    assert repaired["story"]["chapters"][0]["order"] == 1
    assert repaired["story"]["chapters"][0]["next_chapter_id"] == "ch2"
    assert repaired["story"]["relationships"][0]["character_card_id"] == "lan"
    assert len(repairs) == 3


def test_invalid_model_mechanics_are_replaced_by_the_vetted_story_skeleton() -> None:
    definition = {
        "name": "模型雾城",
        "story": {"chapters": [{"id": "unsafe"}]},
        "character_cards": [{"name": "守夜人"}, {"name": "档案员"}],
        "locations": [{"name": "北塔"}, {"name": "盐市"}],
        "ruleset": {"id": "model-invented-rules"},
    }

    safe_definition, safe_hero, repairs = map_to_safe_story_skeleton(
        definition, {"name": "远行者"}
    )

    assert safe_definition["name"] == "模型雾城"
    assert safe_definition["ruleset"]["id"] == "hybrid"
    assert safe_definition["character_cards"][0]["name"] == "守夜人"
    assert safe_definition["locations"][0]["name"] == "北塔"
    assert safe_hero["name"] == "远行者"
    assert any("受控 hybrid 规则骨架" in repair for repair in repairs)
    assert safe_definition["story"]["chapters"][0]["title"] == "抵达北塔"
    assert safe_definition["story"]["chapters"][0]["choices"][0]["label"] == "援手守夜人"
    assert safe_definition["story"]["chapters"][0]["choices"][1]["label"] == "替档案员保守秘密"
    assert safe_definition["lorebook"]["entries"] == []
    assert safe_definition["resources"][0]["name"] == "关键线索"


def test_safe_mapping_rejects_a_world_without_enough_player_material() -> None:
    safe_definition, safe_hero, repairs = map_to_safe_story_skeleton(
        {
            "name": "缺素材的世界",
            "story": {"chapters": [{"id": "unsafe"}]},
            "character_cards": [{"name": "唯一角色"}],
            "locations": [{"name": "唯一地点"}],
        },
        {"name": "旅行者"},
    )

    assert safe_definition == {}
    assert safe_hero == {}
    assert repairs == []


def test_story_surface_uses_mapped_names_for_new_world_recommendations() -> None:
    definition = {
        "name": "潮汐之门",
        "story": {"chapters": [{"id": "unsafe"}]},
        "character_cards": [{"name": "林霖"}, {"name": "顾潮生"}],
        "locations": [{"name": "启航港"}, {"name": "回声灯塔"}],
    }

    safe_definition, _safe_hero, repairs = map_to_safe_story_skeleton(
        definition, {"name": "米拉"}
    )

    story = safe_definition["story"]
    assert story["routes"][0]["name"] == "林霖路线"
    assert story["routes"][1]["name"] == "顾潮生路线"
    assert story["chapters"][0]["title"] == "抵达启航港"
    assert [choice["label"] for choice in story["chapters"][0]["choices"]] == [
        "援手林霖",
        "替顾潮生保守秘密",
    ]
    assert story["chapters"][1]["title"] == "启航港的证词"
    assert story["chapters"][1]["choices"][3]["label"] == "让林霖与顾潮生共同作证"
    assert story["chapters"][2]["title"] == "回声灯塔的决断"
    assert any("story surface" in repair for repair in repairs)
    serialized = json.dumps(safe_definition, ensure_ascii=False)
    assert "雾港" not in serialized
    assert "岚" not in serialized
    assert "雾灯" not in serialized


def test_compact_qwen_story_and_descriptions_are_mapped_to_safe_runtime() -> None:
    definition = {
        "name": "潮汐之门",
        "story": {"chapter_1": "月圆之夜，潮门即将开启。"},
        "character_cards": [
            {"name": "林若兮", "description": "勇敢的探险家。"},
            {"name": "墨寒", "description": "神秘的船长。"},
        ],
        "locations": [{"name": "月影港"}, {"name": "潮汐之心"}],
        "npcs": [{"name": "李老渔", "description": "知晓潮门秘密。"}],
        "events": [{"name": "月圆之夜的秘密", "description": "解开潮门谜题。"}],
    }

    safe_definition, _safe_hero, repairs = map_to_safe_story_skeleton(
        definition, {"name": "林若兮"}
    )

    assert safe_definition["character_cards"][0]["name"] == "林若兮"
    assert safe_definition["npcs"][0]["description"] == "勇敢的探险家。"
    assert {npc["name"] for npc in safe_definition["npcs"]} == {"林若兮", "墨寒", "李老渔"}
    assert safe_definition["events"][0]["summary"] == "解开潮门谜题。"
    assert any("compact story" in repair for repair in repairs)


def test_opening_does_not_make_the_hero_talk_to_themselves() -> None:
    definition = fog_harbor_template()["world_definition"]
    definition["character_cards"][0]["name"] = "艾莉"
    definition["character_cards"][1]["name"] = "杰克"

    opening = build_opening_story_beat(definition, {"name": "艾莉"})

    assert opening["dialogue"]["speaker"] == "杰克"


def test_safe_story_repair_preserves_descriptive_runtime_entities() -> None:
    definition = {
        "name": "模型雾城",
        "story": {"chapters": [{"id": "unsafe"}]},
        "character_cards": [
            {"name": "守夜人", "mapped": {"description": "守着北塔。"}},
            {"name": "摆渡人", "description": "只在涨潮时出现。"},
        ],
        "locations": [{"name": "北塔"}, {"name": "盐市"}, {"name": "旧闸门"}],
        "npcs": [
            {
                "name": "摆渡人",
                "role": "船夫",
                "description": "只在涨潮时出现。",
                "motivation": "寻找失去的铃铛。",
                "location": "盐市",
                "contact_cooldown_turns": 8,
            }
        ],
        "factions": [{"name": "北塔守望者", "description": "守护旧闸门。"}],
        "events": [
            {
                "name": "闸门异响",
                "summary": "夜里传出三次敲击。",
                "location": "旧闸门",
                "importance": 4,
                "trigger_turn": 3,
            }
        ],
        "ruleset": {"id": "model-invented-rules"},
    }

    safe_definition, _safe_hero, _repairs = map_to_safe_story_skeleton(
        definition, {"name": "远行者"}
    )

    assert [location["name"] for location in safe_definition["locations"]] == [
        "北塔",
        "盐市",
        "旧闸门",
    ]
    assert {npc["name"] for npc in safe_definition["npcs"]} == {"守夜人", "摆渡人"}
    assert safe_definition["npcs"][1]["location_id"] == "lighthouse"
    assert safe_definition["events"] == [
        {
            "id": "event-1",
            "name": "闸门异响",
            "summary": "夜里传出三次敲击。",
            "scope_ref": "location-3",
            "importance": 4,
            "trigger_turn": 3,
            "initial_active": False,
            "trigger_conditions": {},
            "completion_conditions": {},
            "campaign_phase_id": None,
        }
    ]
    assert safe_definition["factions"] == [
        {
            "id": "faction-1",
            "name": "北塔守望者",
            "description": "守护旧闸门。",
            "initial_tension": 0,
            "tension_rules": {"passive_gain_per_turn": 0, "threshold_conflict": 80},
        }
    ]
