from __future__ import annotations

import asyncio
import json
import sqlite3
from copy import deepcopy
from pathlib import Path
from threading import Event

import pytest

from dzmm.ai_world_drafts import (
    AIWorldDraftGenerationError,
    AIWorldDraftInput,
    AIWorldDraftService,
    CreativeSource,
    _normalize_creative_source_payload,
)
from dzmm.model_profiles import ModelProfile, NarrationError, ProviderType


def table_counts(database: Path) -> dict[str, int]:
    names = ["worlds", "world_versions", "heroes", "runs", "compose_requests"]
    with sqlite3.connect(database) as connection:
        return {
            name: connection.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0] for name in names
        }


CREATIVE_SOURCE = {
    "world_name": "星潮港",
    "summary": "失落星图让潮门在月夜重开，选择会决定谁愿意相信主角。",
    "hero": {"name": "阿梨", "origin": "寻找失踪姐姐的见习领航员"},
    "locations": ["星潮码头", "坠月观测塔"],
    "characters": [
        {"name": "苏岚", "role": "谨慎的潮汐学者", "description": "她掌握星图的一半秘密。"},
        {"name": "季衡", "role": "嘴硬心软的港口守夜人", "description": "他不愿再失去任何人。"},
    ],
    "lore": [
        {"title": "星潮", "body": "月亮最低时，星潮会让旧航道显形。"},
        {"title": "断裂星图", "body": "两名守护者各自保管半张星图。"},
    ],
}


class StaticDraftGenerator:
    def __init__(self, source: dict | None = None, error: Exception | None = None) -> None:
        self.source = source or CREATIVE_SOURCE
        self.error = error
        self.prompts: list[dict] = []

    async def generate(self, _profile, prompt: dict):
        self.prompts.append(prompt)
        if self.error is not None:
            raise self.error
        return deepcopy(self.source), ["removed Markdown code fence"]


class BlockingDraftGenerator:
    def __init__(self) -> None:
        self.started = Event()
        self.release = Event()

    async def generate(self, _profile, _prompt):
        self.started.set()
        await asyncio.to_thread(self.release.wait)
        return {}, []


class StaticProfileService:
    async def get(self, _profile_id: str) -> ModelProfile:
        return ModelProfile(
            id="profile-1",
            name="test",
            provider_type=ProviderType.OLLAMA,
            base_url="http://127.0.0.1:11434",
            model_name="test",
        )


def _create_profile(client) -> str:
    response = client.post(
        "/api/v2/model-profiles",
        json={
            "name": "draft model",
            "provider_type": "lm_studio",
            "base_url": "http://desktop.local:1234/v1",
            "model_name": "huihui-ai_qwen3-14b-abliterated",
        },
    )
    assert response.status_code == 201
    return response.json()["id"]


def _draft_request(profile_id: str) -> dict:
    return {
        "model_profile_id": profile_id,
        "ruleset": "hybrid",
        "genre": "潮汐悬疑恋爱冒险",
        "tone": "温柔、危险",
        "core_conflict": "失踪航图打开了不该开启的潮门。",
        "hero_preference": "会做艰难选择的年轻领航员",
        "character_preferences": ["学者", "守夜人"],
    }


def test_weak_model_material_is_safely_normalized_before_creative_validation() -> None:
    normalized, repairs = _normalize_creative_source_payload(
        {
            **CREATIVE_SOURCE,
            "factions": [
                {
                    "name": "守望者",
                    "description": "守护城市。",
                    "initial_tension": -12,
                    "passive_gain_per_turn": -3,
                    "threshold_conflict": 140,
                }
            ],
            "events": [
                {
                    "name": "异常",
                    "summary": "网络短暂失灵。",
                    "importance": "high",
                    "trigger": [],
                    "completion": "later",
                }
            ],
        }
    )

    assert normalized["factions"][0]["initial_tension"] == 0
    assert normalized["factions"][0]["passive_gain_per_turn"] == 0
    assert normalized["factions"][0]["threshold_conflict"] == 100
    assert normalized["events"][0]["trigger"] == {}
    assert normalized["events"][0]["completion"] == {}
    assert normalized["events"][0]["importance"] == 2
    assert len(repairs) == 6


def test_weak_model_typo_in_known_faction_field_is_normalized() -> None:
    normalized, repairs = _normalize_creative_source_payload(
        {**CREATIVE_SOURCE, "factions": [{"name": "守望者", "description": "守护城市。", "passive_gain_per一点": 2}]}
    )

    assert normalized["factions"][0]["passive_gain_per_turn"] == 2
    assert "passive_gain_per_turn 已修正字段名称" in repairs[0]


def test_referenced_location_is_added_to_creative_material_when_capacity_allows() -> None:
    normalized, repairs = _normalize_creative_source_payload(
        {
            **CREATIVE_SOURCE,
            "npcs": [{"name": "迷路的信使", "role": "信使", "description": "带来坏消息。", "location": "盐雾集市"}],
        }
    )

    assert normalized["locations"] == ["星潮码头", "坠月观测塔", "盐雾集市"]
    assert any("npcs[0].location 已将引用地点加入地点列表" in repair for repair in repairs)


def test_unrepresentable_location_reference_blocks_world_creation(migrated_client) -> None:
    client, _ = migrated_client
    profile_id = _create_profile(client)
    source = {
        **CREATIVE_SOURCE,
        "locations": ["星潮码头", "坠月观测塔", "盐雾集市"],
        "npcs": [{"name": "迷路的信使", "role": "信使", "description": "带来坏消息。", "location": "迷雾谷"}],
    }
    client.app.state.ai_world_drafts._generator = StaticDraftGenerator(source=source)

    response = client.post("/api/v2/ai-world-drafts:generate", json=_draft_request(profile_id))

    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is False
    assert any(issue["path"] == "npcs[0].location" for issue in body["issues"])

    normalized, repairs = _normalize_creative_source_payload(
        {**CREATIVE_SOURCE, "npcs": [{"name": "观察员", "role": "记录者", "description": "记录异常。", "contact_cooldown_turn个数": "2", "reputation": "中立"}]}
    )
    npc = normalized["npcs"][0]
    assert npc["contact_cooldown_turns"] == 2
    assert npc["reputation"] == 0
    assert any("contact_cooldown_turns 已修正字段名称" in repair for repair in repairs)

    normalized, repairs = _normalize_creative_source_payload(
        {**CREATIVE_SOURCE, "factions": [{"name": "守望者", "description": "守护城市。", "passive_gain_per turn": 2}]}
    )
    assert normalized["factions"][0]["passive_gain_per_turn"] == 2
    assert "passive_gain_per_turn 已修正字段名称" in repairs[0]


def test_ai_draft_normalization_keeps_weak_model_material_reviewable(migrated_client) -> None:
    client, _ = migrated_client
    profile_id = _create_profile(client)
    source = {
        **CREATIVE_SOURCE,
        "factions": [
            {
                "name": "守望者",
                "description": "守护城市。",
                "initial_tension": -12,
                "passive_gain_per_turn": -3,
                "threshold_conflict": 140,
            }
        ],
        "events": [
            {
                "name": "异常",
                "summary": "网络短暂失灵。",
                "trigger": [],
                "completion": "later",
            }
        ],
    }
    client.app.state.ai_world_drafts._generator = StaticDraftGenerator(source=source)

    response = client.post("/api/v2/ai-world-drafts:generate", json=_draft_request(profile_id))

    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is True
    assert any("factions[0].initial_tension" in repair for repair in body["repairs"])
    assert body["world_definition"]["factions"][0]["initial_tension"] == 0
    assert body["world_definition"]["events"][0]["trigger_conditions"] == {}


def test_ai_draft_deduplicates_character_cards_repeated_as_npcs(migrated_client) -> None:
    client, _ = migrated_client
    profile_id = _create_profile(client)
    source = {
        **CREATIVE_SOURCE,
        "npcs": [
            {"name": "苏岚", "role": "学者", "description": "掌握星图。"},
            {"name": "李老渔", "role": "摆渡人", "description": "熟悉旧航道。"},
        ],
    }
    client.app.state.ai_world_drafts._generator = StaticDraftGenerator(source=source)

    response = client.post("/api/v2/ai-world-drafts:generate", json=_draft_request(profile_id))

    assert response.status_code == 200
    assert response.json()["valid"] is True
    names = [npc["name"] for npc in response.json()["world_definition"]["npcs"]]
    assert names == ["苏岚", "季衡", "李老渔"]


def test_ai_draft_cancellation_discards_result_before_validation() -> None:
    generator = BlockingDraftGenerator()
    service = AIWorldDraftService(StaticProfileService(), generator=generator)
    payload = AIWorldDraftInput(
        model_profile_id="profile-1",
        ruleset="hybrid",
        genre="悬疑",
        tone="温柔",
        core_conflict="潮门重开",
        hero_preference="领航员",
        request_id="draft-cancel-1",
    )

    async def run() -> None:
        task = asyncio.create_task(service.generate(payload))
        await asyncio.to_thread(generator.started.wait)
        assert service.cancel_operation(payload.request_id or "") is True
        generator.release.set()
        with pytest.raises(AIWorldDraftGenerationError, match="draft was discarded"):
            await task
        assert service.cancel_operation(payload.request_id or "") is False

    asyncio.run(run())


def test_ai_draft_is_ephemeral_then_composes_and_reaches_a_python_ending(migrated_client) -> None:
    client, database = migrated_client
    profile_id = _create_profile(client)
    generator = StaticDraftGenerator()
    client.app.state.ai_world_drafts._generator = generator

    draft = client.post("/api/v2/ai-world-drafts:generate", json=_draft_request(profile_id))

    assert draft.status_code == 200
    body = draft.json()
    assert body["valid"] is True
    assert body["repairs"] == ["removed Markdown code fence"]
    assert body["world_definition"]["schema_version"] == 3
    assert body["world_definition"]["ruleset"]["id"] == "hybrid"
    chapters = body["world_definition"]["story"]["chapters"]
    assert len(chapters) == 10
    assert chapters[-1]["next_chapter_id"] is None
    assert len(body["world_definition"]["story"]["relationships"]) == 2
    assert "command" not in str(generator.prompts[0]).lower()
    assert table_counts(database) == {
        "worlds": 0,
        "world_versions": 0,
        "heroes": 0,
        "runs": 0,
        "compose_requests": 0,
    }

    compose_payload = {
        "request_id": "ai-draft-confirm-1",
        "model_profile_id": None,
        "world_definition": body["world_definition"],
        "hero": body["hero"],
    }
    created = client.post("/api/v2/worlds:compose", json=compose_payload)
    assert created.status_code == 201
    run_id = created.json()["run_id"]

    choice_ids = [
        "rescue-lan",
        "lan-testimony",
        "investigate-3",
        "ask-4",
        "investigate-5",
        "ask-6",
        "investigate-7",
        "ask-8",
        "investigate-9",
        "open-tide-gate",
    ]
    for revision, choice_id in enumerate(choice_ids):
        chosen = client.post(
            f"/api/v2/runs/{run_id}/choices",
            json={
                "request_id": f"ai-draft-choice-{revision}",
                "expected_revision": revision,
                "player_input": choice_id,
                "choice_id": choice_id,
            },
        )
        assert chosen.status_code == 201
    assert chosen.json()["state"]["ending"]["id"] == "lan-dawn"
    presentation = client.get(f"/api/v2/runs/{run_id}").json()["presentation"]
    assert presentation["locations"]["harbor"] == "星潮码头"
    assert presentation["resources"]["fog-lantern"] == "关键线索"
    assert presentation["relationships"]["lan"] == "苏岚"
    assert presentation["chapters"]["ch2"] == "星潮港的证词"

    retry = client.post("/api/v2/worlds:compose", json=compose_payload)
    assert retry.status_code == 200
    assert retry.json()["run_id"] == run_id
    assert table_counts(database)["runs"] == 1

    card = client.get(
        f"/api/v2/world-versions/{created.json()['world_version_id']}/character-cards/lan:export"
    )
    assert card.status_code == 200
    assert card.json()["spec"] == "chara_card_v3"
    assert card.json()["data"]["name"] == "苏岚"


def test_ai_draft_rejects_invalid_model_material_without_creating_worlds(migrated_client) -> None:
    client, database = migrated_client
    profile_id = _create_profile(client)
    invalid = {**CREATIVE_SOURCE, "commands": [{"type": "python"}]}
    client.app.state.ai_world_drafts._generator = StaticDraftGenerator(source=invalid)

    response = client.post("/api/v2/ai-world-drafts:generate", json=_draft_request(profile_id))

    assert response.status_code == 200
    assert response.json()["valid"] is False
    assert any(issue["path"] == "commands" for issue in response.json()["issues"])
    assert table_counts(database)["worlds"] == 0


def test_ai_draft_projects_each_supported_narrative_ruleset(migrated_client) -> None:
    client, _ = migrated_client
    profile_id = _create_profile(client)
    client.app.state.ai_world_drafts._generator = StaticDraftGenerator()

    for ruleset in ("story_adventure", "relationship_drama", "hybrid"):
        response = client.post(
            "/api/v2/ai-world-drafts:generate",
            json={**_draft_request(profile_id), "ruleset": ruleset},
        )
        assert response.status_code == 200
        assert response.json()["valid"] is True
        assert response.json()["world_definition"]["ruleset"]["id"] == ruleset


def test_ai_draft_projects_runtime_npcs_events_factions_and_location_links(migrated_client) -> None:
    client, _ = migrated_client
    profile_id = _create_profile(client)
    source = {
        **CREATIVE_SOURCE,
        "locations": ["星潮码头", "坠月观测塔", "盐雾集市"],
        "npcs": [
            {
                "name": "白檀",
                "role": "集市情报贩子",
                "description": "她总能比守卫更早听见风声。",
                "motivation": "想找到失踪的弟弟。",
                "location": "盐雾集市",
                "contact_cooldown_turns": 6,
            }
        ],
        "factions": [{"name": "潮门守望会", "description": "守护旧航道的松散组织。"}],
        "events": [
            {
                "name": "潮门异响",
                "summary": "夜里潮门传出第三次敲击。",
                "location": "星潮码头",
                "importance": 4,
                "trigger_turn": 2,
            }
        ],
        "campaign": {
            "name": "星潮战役",
            "phases": [
                {
                    "name": "潮门异响",
                    "description": "查明第一声敲击的来源。",
                    "key_event_names": ["潮门异响"],
                    "required_count": 1,
                }
            ],
        },
        "location_links": [
            {
                "from_location": "星潮码头",
                "to_location": "盐雾集市",
                "direction": "向南",
                "travel_turns": 2,
            }
        ],
    }
    client.app.state.ai_world_drafts._generator = StaticDraftGenerator(source=source)

    response = client.post("/api/v2/ai-world-drafts:generate", json=_draft_request(profile_id))

    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is True
    definition = body["world_definition"]
    assert [location["name"] for location in definition["locations"]] == [
        "星潮码头",
        "坠月观测塔",
        "盐雾集市",
    ]
    assert {npc["name"] for npc in definition["npcs"]} == {"苏岚", "季衡", "白檀"}
    assert definition["npcs"][2]["location_id"] == "location-3"
    assert definition["events"] == [
        {
            "id": "event-1",
            "name": "潮门异响",
            "summary": "夜里潮门传出第三次敲击。",
            "scope_ref": "harbor",
            "importance": 4,
            "trigger_turn": 2,
            "initial_active": False,
            "trigger_conditions": {},
            "completion_conditions": {},
            "campaign_phase_id": "phase-1",
        }
    ]
    assert definition["factions"] == [
        {
            "id": "faction-1",
            "name": "潮门守望会",
            "description": "守护旧航道的松散组织。",
            "initial_tension": 0,
            "tension_rules": {"passive_gain_per_turn": 0, "threshold_conflict": 80},
        }
    ]
    assert definition["story"]["campaign"] == {
        "id": "campaign-main",
        "name": "星潮战役",
        "phases": [
            {
                "id": "phase-1",
                "name": "潮门异响",
                "description": "查明第一声敲击的来源。",
                "key_event_ids": ["event-1"],
                "required_count": 1,
            }
        ],
    }
    assert {link["target_id"] for link in definition["locations"][0]["connections"]} == {
        "lighthouse",
        "location-3",
    }


def test_ai_draft_handles_model_failure_and_invalid_user_edits(migrated_client) -> None:
    client, database = migrated_client
    profile_id = _create_profile(client)
    client.app.state.ai_world_drafts._generator = StaticDraftGenerator(
        error=NarrationError("model returned no draft content")
    )

    failure = client.post("/api/v2/ai-world-drafts:generate", json=_draft_request(profile_id))
    assert failure.status_code == 502
    assert failure.json()["detail"] == "model returned no draft content"
    assert table_counts(database)["worlds"] == 0

    invalid_edit = client.post(
        "/api/v2/ai-world-drafts:validate",
        json={"world_definition": {"schema_version": 3}, "hero": {"name": ""}},
    )
    assert invalid_edit.status_code == 200
    assert invalid_edit.json()["valid"] is False
    assert invalid_edit.json()["issues"]
    assert table_counts(database)["worlds"] == 0


def test_ai_draft_requires_a_configured_model_profile(migrated_client) -> None:
    client, _ = migrated_client

    response = client.post("/api/v2/ai-world-drafts:generate", json=_draft_request("missing"))

    assert response.status_code == 200
    assert response.json() == {
        "valid": False,
        "summary": None,
        "world_definition": None,
        "hero": None,
        "repairs": [],
        "issues": [
            {"path": "model_profile_id", "message": "configured model profile does not exist"}
        ],
    }


def test_normalize_strips_npc_only_fields_from_characters() -> None:
    """真实失败案例（灾难求生）：characters 混入 NPC 专属字段曾被整体拒绝。"""

    payload = {
        "world_name": "深空货运站",
        "summary": "失压后的抉择。",
        "hero": {"name": "老周", "origin": "值班工程师"},
        "locations": ["货运站A舱", "救生舱"],
        "characters": [
            {
                "name": "晕血站长",
                "role": "站长",
                "description": "晕血。",
                "motivation": "活下去",
                "location": "货运站A舱",
                "contact_cooldown_turns": 3,
                "faction": "站务组",
                "reputation": 10,
            },
            {"name": "货运员", "role": "货运员", "description": "乐观。"},
        ],
        "lore": [{"title": "氧气账本", "body": "每人每小时一升。"}],
    }
    normalized, repairs = _normalize_creative_source_payload(payload)
    character = normalized["characters"][0]
    assert not {"motivation", "location", "contact_cooldown_turns", "faction", "reputation"} & set(character)
    assert character["name"] == "晕血站长"
    assert any("NPC 专属字段" in repair for repair in repairs)
    source = CreativeSource.model_validate(normalized)
    assert source.characters[0].name == "晕血站长"


def test_normalize_strips_event_only_fields_from_lore() -> None:
    """真实失败案例：lore.0.trigger_turn 属 Extra inputs 曾被整体拒绝。"""

    payload = {
        "world_name": "深空货运站",
        "summary": "失压后的抉择。",
        "hero": {"name": "老周", "origin": "值班工程师"},
        "locations": ["货运站A舱", "救生舱"],
        "characters": [
            {"name": "晕血站长", "role": "站长", "description": "晕血。"},
            {"name": "货运员", "role": "货运员", "description": "乐观。"},
        ],
        "lore": [
            {
                "title": "氧气账本",
                "body": "每人每小时一升。",
                "trigger_turn": 3,
                "location": "货运站A舱",
            }
        ],
    }
    normalized, repairs = _normalize_creative_source_payload(payload)
    assert set(normalized["lore"][0]) == {"title", "body"}
    assert any("非世界书字段" in repair for repair in repairs)
    CreativeSource.model_validate(normalized)


def test_normalize_clamps_event_trigger_turn() -> None:
    """真实失败案例：events.0.trigger_turn=0 曾因 ge=1 被整体拒绝。"""

    payload = {
        "world_name": "深空货运站",
        "summary": "失压后的抉择。",
        "hero": {"name": "老周", "origin": "值班工程师"},
        "locations": ["货运站A舱", "救生舱"],
        "characters": [
            {"name": "晕血站长", "role": "站长", "description": "晕血。"},
            {"name": "货运员", "role": "货运员", "description": "乐观。"},
        ],
        "lore": [{"title": "氧气账本", "body": "每人每小时一升。"}],
        "events": [
            {"name": "氧量告警", "summary": "氧气跌破红线。", "trigger_turn": 0},
            {"name": "救援窗", "summary": "救援窗口开启。", "trigger_turn": 99},
        ],
    }
    normalized, repairs = _normalize_creative_source_payload(payload)
    turns = [event["trigger_turn"] for event in normalized["events"]]
    assert turns == [1, 40]
    assert any("trigger_turn 已按安全范围规范化" in repair for repair in repairs)
    CreativeSource.model_validate(normalized)


def test_normalize_unwraps_world_definition_shape() -> None:
    """真实案例（qwen3-14b）：模型直接输出最终 world_definition 形状而非素材格式。"""

    raw = json.loads(
        (Path(__file__).parent / "fixtures" / "genre_raw_world_definition.json").read_text()
    )
    normalized, repairs = _normalize_creative_source_payload(raw)
    assert any("world_definition 形状解包" in repair for repair in repairs)
    source = CreativeSource.model_validate(normalized)
    assert source.world_name == "摄政王的夜宴"
    assert source.hero.name  # 模型自拟主角名
    assert len(source.locations) >= 2 and len(source.characters) >= 2
    assert len(source.npcs) >= 1 and len(source.events) >= 1
