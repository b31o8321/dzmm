"""多题材健壮性验收（ADR：多题材多样性评审的三项增强）。

覆盖：修复器吞掉此前两类真实失败；四个题材的章节名/选择标签互不相同；
开场与 NPC 首句按骨架变体、按世界+主角轮换。
"""

import jsonschema

from dzmm.ai_world_drafts import (
    CreativeSource,
    _map_creative_source,
    _normalize_creative_source_payload,
)
from dzmm.genre_presets import DEFAULT_SKELETON, skeleton_for_genre
from dzmm.narrative import validate_definition
from dzmm.story_beats import build_opening_story_beat
from dzmm.world_templates import fog_harbor_template

FOUR_GENRES = ["悬疑探案", "灾难求生", "政治阴谋", "蒸汽朋克西部"]


def _source(world_name: str, genre: str) -> dict:
    flavor = {
        "悬疑探案": ("钟表匠坠楼", ["旧城钟楼", "钟表匠工坊", "市长办公室"], "林峰", "李明", "夏琳"),
        "灾难求生": ("氧气只够一半人", ["货运站A舱", "救生舱", "维修通道"], "老周", "站长", "货运员"),
        "政治阴谋": ("摄政王车队被劫", ["摄政王府", "墨家秘境", "档案馆"], "林静言", "白羽", "墨承恩"),
        "蒸汽朋克西部": ("铁路公司碾平自由镇", ["自由镇", "齿轮站", "公司办事处"], "艾文", "梅琳达", "罗伯特"),
    }[genre]
    conflict, locations, hero_name, first_name, second_name = flavor
    return {
        "world_name": world_name,
        "summary": f"{genre}题材验证世界。",
        "hero": {"name": hero_name, "origin": "测试出身"},
        "locations": locations,
        "characters": [
            {"name": first_name, "role": "关键人物", "description": "测试人物。"},
            {"name": second_name, "role": "次要人物", "description": "测试人物。"},
        ],
        "lore": [{"title": "背景设定", "body": f"{conflict}。"}],
    }


def _build_definition(genre: str, *, input_genre: str | None = None) -> dict:
    source = _normalize_creative_source_payload(_source(f"验证·{genre}", genre))[0]
    source_obj = CreativeSource.model_validate(source)
    skeleton = skeleton_for_genre(input_genre or genre)
    definition, _hero = _map_creative_source(
        source_obj, "story_adventure", skeleton=skeleton
    )
    from dzmm.generated_world_repair import extend_story_for_long_run

    locations = [item["name"] for item in definition["locations"]]
    character_names = [item["name"] for item in definition["character_cards"]]
    extend_story_for_long_run(
        definition, source_obj.world_name, locations, character_names, skeleton=skeleton
    )
    validate_definition(definition)
    jsonschema.validate(definition, _world_contract())
    return definition


def _world_contract() -> dict:
    import json
    from pathlib import Path

    return json.loads(
        (Path(__file__).parents[2] / "contracts" / "world_definition.schema.json").read_text()
    )


def test_repairer_swallows_the_two_historical_failure_classes() -> None:
    """此前两类真实失败：characters 混 NPC 字段；lore 混事件字段+数值越界。"""

    source = _normalize_creative_source_payload(
        {
            **_source("验证·灾难求生", "灾难求生"),
            "characters": [
                {
                    "name": "站长",
                    "role": "站长",
                    "description": "晕血。",
                    "motivation": "活下去",
                    "contact_cooldown_turns": 3,
                    "faction": "站务组",
                    "reputation": 5,
                    "location": "货运站A舱",
                },
                {"name": "货运员", "role": "货运员", "description": "乐观。"},
            ],
            "lore": [
                {"title": "氧气账本", "body": "每人每小时一升。", "trigger_turn": 2}
            ],
            "events": [
                {"name": "氧量告警", "summary": "跌破红线", "trigger_turn": 0}
            ],
        }
    )[0]
    CreativeSource.model_validate(source)  # 修复后可整体通过


def test_four_genres_skeletons_diverge_pairwise() -> None:
    """四个题材的章节名/选择标签两两不同，且都与默认模板不同。"""

    built = {}
    for genre in FOUR_GENRES:
        definition = _build_definition(genre)
        chapters = definition["story"]["chapters"]
        built[genre] = {
            "ch1_choice": chapters[0]["choices"][0]["label"],
            "ch2_title": chapters[1]["title"],
            "longrun_title": chapters[2]["title"],
        }
    labels = list(built.values())
    for i in range(len(labels)):
        for j in range(i + 1, len(labels)):
            for key in ("ch1_choice", "ch2_title", "longrun_title"):
                assert labels[i][key] != labels[j][key], (labels[i], labels[j])
    for genre, observed in built.items():
        assert observed["ch1_choice"] != DEFAULT_SKELETON["ch1_choices"][0].format(
            a="X", b="Y"
        ), genre


def test_unknown_genre_falls_back_to_default_skeleton() -> None:
    definition = _build_definition("悬疑探案", input_genre="雾都孤儿式的循环剧")
    chapters = definition["story"]["chapters"]
    assert chapters[1]["title"].endswith("的证词")
    assert chapters[0]["choices"][0]["label"].startswith("援手")
    validate_definition(definition)


def test_opening_variants_rotate_by_world_and_hero() -> None:
    template = fog_harbor_template()
    definition = dict(template["world_definition"])
    definition["story"]["chapters"][0]["choices"] = [
        {"id": "c1", "label": "协助李明勘查现场"},
        {"id": "c2", "label": "替夏琳隐瞒线索"},
    ]
    seen = set()
    hero_names = [f"侦探{i:02d}" for i in range(12)]
    for hero in hero_names:
        beat = build_opening_story_beat(definition, {"name": hero, "origin": "警探"})
        seen.add(beat["narrative"])
    # 至少出现两种开场变体；且都不再是默认句式
    assert len(seen) >= 2
    for narrative in seen:
        assert "的故事从此刻开始" not in narrative


def test_npc_first_line_variants_by_skeleton() -> None:
    definition = dict(fog_harbor_template()["world_definition"])
    definition["story"]["chapters"][0]["choices"] = [
        {"id": "c1", "label": "协助李明勘查现场"},
        {"id": "c2", "label": "替夏琳隐瞒线索"},
    ]
    default_beat = build_opening_story_beat(
        fog_harbor_template()["world_definition"], {"name": "米拉", "origin": "水手"}
    )
    assert "别让这里替你作出第一个决定" in default_beat["dialogue"]["text"]

    variant_seen = False
    for hero in (f"侦探{i:02d}" for i in range(12)):
        beat = build_opening_story_beat(definition, {"name": hero, "origin": "警探"})
        if "别让这里替你作出第一个决定" not in beat["dialogue"]["text"]:
            variant_seen = True
    assert variant_seen
