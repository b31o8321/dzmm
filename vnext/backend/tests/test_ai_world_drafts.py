from __future__ import annotations

import sqlite3
from copy import deepcopy
from pathlib import Path

from dzmm_vnext.model_profiles import NarrationError


def table_counts(database: Path) -> dict[str, int]:
    names = ["worlds", "world_versions", "heroes", "runs", "compose_requests"]
    with sqlite3.connect(database) as connection:
        return {name: connection.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0] for name in names}


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
    assert len(body["world_definition"]["story"]["chapters"]) == 3
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

    for revision, choice_id in enumerate(("rescue-lan", "lan-testimony", "open-tide-gate")):
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
            "/api/v2/ai-world-drafts:generate", json={**_draft_request(profile_id), "ruleset": ruleset}
        )
        assert response.status_code == 200
        assert response.json()["valid"] is True
        assert response.json()["world_definition"]["ruleset"]["id"] == ruleset


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
        "issues": [{"path": "model_profile_id", "message": "configured model profile does not exist"}],
    }
