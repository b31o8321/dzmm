"""P1 增强：技能目录、use_item 使用语义、任务链与限时。

12 维度评估 §七 P1：技能只有单一形态（仅 insight 被测）、道具只是计数器、
任务只有单步 flag→奖励。
"""

from __future__ import annotations


def _world_payload(request_id: str, *, deadline_turns: int | None = None) -> dict:
    quests = [
        {
            "id": "find-key",
            "title": "找到钥匙",
            "completion": {"flag": "has-key"},
            "rewards": [{"type": "skill", "skill": "ancient-tongue"}],
        }
    ]
    if deadline_turns is None:
        quests.append(
            {
                "id": "open-vault",
                "title": "打开密库",
                "requires_quest": "find-key",
                "completion": {"flag": "vault-open"},
                "rewards": [{"type": "item", "item_id": "relic", "quantity": 1}],
            }
        )
    else:
        quests[0]["deadline_turns"] = deadline_turns
    definition = {
        "schema_version": 3,
        "name": "古语密库",
        "skills": ["ancient-tongue"],
        "lorebook": {"entries": []},
        "character_cards": [],
        "locations": [{"id": "camp", "name": "营地"}, {"id": "vault-door", "name": "密库门"}],
        "factions": [],
        "npcs": [],
        "events": [],
        "resources": [
            {"id": "healing-herb", "name": "治疗草药", "on_use": {"heal": 5}},
            {"id": "vault-sigil", "name": "密库印记", "on_use": {"flag_id": "vault-open"}},
            {"id": "relic", "name": "遗物"},
            {"id": "plain-rock", "name": "普通石头"},
        ],
        "ruleset": {
            "id": "hybrid",
            "enabled_capabilities": ["trpg", "resources", "combat", "chapters", "choices", "endings"],
        },
        "story": {
            "quests": quests,
            "chapters": [
                {
                    "id": "ch1",
                    "title": "一章",
                    "order": 1,
                    "next_chapter_id": None,
                    "choices": [
                        {
                            "id": "take-key",
                            "label": "拾取钥匙",
                            "effects": [{"type": "set_story_flag", "flag_id": "has-key", "value": True}],
                        },
                        {
                            "id": "open-vault-choice",
                            "label": "开启密库",
                            "effects": [{"type": "set_story_flag", "flag_id": "vault-open", "value": True}],
                        },
                    ],
                }
            ],
            "flags": [
                {"id": "has-key", "default": False, "writers": ["choice:take-key"]},
                {"id": "vault-open", "default": False, "writers": ["choice:open-vault-choice"]},
            ],
            "relationships": [],
            "relationship_events": [],
            "routes": [],
            "endings": [
                {
                    "id": "done",
                    "kind": "normal",
                    "priority": 1,
                    "narrative_key": "ending.done",
                    "when": {"flag": "vault-open", "equals": True},
                }
            ],
        },
    }
    return {
        "request_id": request_id,
        "world_definition": definition,
        "hero": {"name": "探险者", "profile": {}},
        "sandbox": True,
    }


def _compose(client, payload: dict) -> tuple[str, int]:
    response = client.post("/api/v2/worlds:compose", json=payload)
    assert response.status_code in (200, 201), response.text
    body = response.json()
    return body["run_id"], body["state"]["revision"]


def _turn(client, run_id: str, revision: int, request_id: str, commands: list[dict]):
    return client.post(
        f"/api/v2/runs/{run_id}/turns",
        json={
            "request_id": request_id,
            "expected_revision": revision,
            "player_input": "我继续行动。",
            "commands": commands,
        },
    )


def _types(body: dict) -> list[str]:
    return [o.get("type") for o in body.get("outcomes", [])]


def test_skill_catalog_rejects_unknown_and_accepts_world_skills(migrated_client) -> None:
    """目录外技能 409；世界声明技能可未受训检定。"""

    client, _ = migrated_client
    run_id, revision = _compose(client, _world_payload("skill-compose"))

    unknown = _turn(client, run_id, revision, "sk-unknown",
                    [{"type": "skill_check", "payload": {"skill": "fireball", "dc": 10}}])
    assert unknown.status_code == 409, unknown.text
    assert "unknown skill" in unknown.json()["detail"]

    world_skill = _turn(client, run_id, revision, "sk-world",
                        [{"type": "skill_check", "payload": {"skill": "ancient-tongue", "dc": 10}}])
    assert world_skill.status_code == 201, world_skill.text
    result = next(o for o in world_skill.json()["outcomes"] if o.get("type") == "skill_check_result")
    assert result["trained"] is False and result["modifier"] == 0

    base_skill = _turn(client, run_id, world_skill.json()["state"]["revision"], "sk-base",
                       [{"type": "skill_check", "payload": {"skill": "survival", "dc": 10}}])
    assert base_skill.status_code == 201, base_skill.text


def test_use_item_heals_and_flag_effects_drive_quests(migrated_client) -> None:
    """heal 效果入战斗数值、flag 效果联动任务完成；目录外/无效果/未持有拒绝。"""

    client, _ = migrated_client
    run_id, revision = _compose(client, _world_payload("item-compose"))

    # 道具入包
    grant = _turn(client, run_id, revision, "it-grant",
                  [{"type": "inventory_change", "payload": {"item_id": "healing-herb", "delta": 1}}])
    assert grant.status_code == 201, grant.text
    revision = grant.json()["state"]["revision"]

    # 无效果物品拒绝
    plain = _turn(client, run_id, revision, "it-plain",
                  [{"type": "inventory_change", "payload": {"item_id": "plain-rock", "delta": 1}}])
    assert plain.status_code == 201, plain.text
    revision = plain.json()["state"]["revision"]
    no_effect = _turn(client, run_id, revision, "it-noeffect",
                      [{"type": "use_item", "payload": {"item_id": "plain-rock"}}])
    assert no_effect.status_code == 409, no_effect.text

    # 未持有拒绝
    not_held = _turn(client, run_id, revision, "it-notheld",
                     [{"type": "use_item", "payload": {"item_id": "vault-sigil"}}])
    assert not_held.status_code == 409, not_held.text

    # heal：战斗外为 no-op（healed=0），仍消耗一个
    heal = _turn(client, run_id, revision, "it-heal",
                 [{"type": "use_item", "payload": {"item_id": "healing-herb"}}])
    assert heal.status_code == 201, heal.text
    used = next(o for o in heal.json()["outcomes"] if o.get("type") == "item_used")
    assert used["healed"] == 0 and used["hp"] is None
    inventory = heal.json()["state"]["inventory"]
    assert sum(i["quantity"] for i in inventory if i["id"] == "healing-herb") == 0
    revision = heal.json()["state"]["revision"]

    # flag 效果：印记置位 vault-open → 驱动任务链（见 test_quest_chain）
    grant_sigil = _turn(client, run_id, revision, "it-sigil",
                        [{"type": "inventory_change", "payload": {"item_id": "vault-sigil", "delta": 1}}])
    assert grant_sigil.status_code == 201, grant_sigil.text
    revision = grant_sigil.json()["state"]["revision"]
    sigil = _turn(client, run_id, revision, "it-sigil-use",
                  [{"type": "use_item", "payload": {"item_id": "vault-sigil"}}])
    assert sigil.status_code == 201, sigil.text
    assert "item_used" in _types(sigil.json())
    assert sigil.json()["state"]["flags"]["vault-open"] is True

    # 未知旗标拒绝
    client2_payload = _world_payload("item-compose-2")
    client2_payload["world_definition"]["resources"][1]["on_use"] = {"flag_id": "nonexistent"}
    run2, rev2 = _compose(client, client2_payload)
    grant2 = _turn(client, run2, rev2, "it2-grant",
                   [{"type": "inventory_change", "payload": {"item_id": "vault-sigil", "delta": 1}}])
    assert grant2.status_code == 201, grant2.text
    bad = _turn(client, run2, grant2.json()["state"]["revision"], "it2-bad",
                [{"type": "use_item", "payload": {"item_id": "vault-sigil"}}])
    assert bad.status_code == 409, bad.text
    assert "unknown story flag" in bad.json()["detail"]


def test_quest_chain_activates_and_completes_in_order(migrated_client) -> None:
    """pending → 前置完成即激活 → 完成发奖；奖励技能进入 hero.skills。"""

    client, _ = migrated_client
    run_id, revision = _compose(client, _world_payload("chain-compose"))
    state = client.get(f"/api/v2/runs/{run_id}").json()["state"]
    assert state["quests"]["find-key"]["status"] == "active"
    assert state["quests"]["open-vault"]["status"] == "pending"

    # 完成 q1：奖励技能 ancient-tongue；q2 同回合激活
    first = _turn(client, run_id, revision, "chain-t0",
                  [{"type": "choose_story_choice", "payload": {"choice_id": "take-key"}}])
    assert first.status_code == 201, first.text
    types = _types(first.json())
    assert "quest_completed" in types and "quest_activated" in types
    assert "quest_reward_skill" in types
    state = first.json()["state"]
    revision = state["revision"]
    assert state["quests"]["find-key"]["status"] == "completed"
    assert state["quests"]["open-vault"]["status"] == "active"
    assert "ancient-tongue" in state["hero"]["skills"]

    # 完成 q2：奖励遗物入包
    second = _turn(client, run_id, revision, "chain-t1",
                   [{"type": "choose_story_choice", "payload": {"choice_id": "open-vault-choice"}}])
    assert second.status_code == 201, second.text
    types = _types(second.json())
    assert "quest_completed" in types and "quest_reward_item" in types
    inventory = second.json()["state"]["inventory"]
    assert any(i["id"] == "relic" and i["quantity"] >= 1 for i in inventory)

    # 奖励的技能立即可检定且受训（+3）
    third = _turn(client, run_id, second.json()["state"]["revision"], "chain-t2",
                  [{"type": "skill_check", "payload": {"skill": "ancient-tongue", "dc": 10}}])
    assert third.status_code == 201, third.text
    result = next(o for o in third.json()["outcomes"] if o.get("type") == "skill_check_result")
    assert result["trained"] is True and result["modifier"] == 3


def test_quest_deadline_expires_once(migrated_client) -> None:
    """deadline_turns 到期未完成 → expired（一次性 outcome），不再发奖。"""

    client, _ = migrated_client
    run_id, revision = _compose(client, _world_payload("deadline-compose", deadline_turns=2))

    expired_seen = 0
    for i in range(4):
        response = _turn(client, run_id, revision, f"dl-t{i}", [{"type": "narrate", "payload": {}}])
        assert response.status_code == 201, response.text
        revision = response.json()["state"]["revision"]
        if "quest_expired" in _types(response.json()):
            expired_seen += 1
        if i >= 2:
            assert "quest_expired" not in _types(response.json()), "过期 outcome 不得重复"
    assert expired_seen == 1
    state = client.get(f"/api/v2/runs/{run_id}").json()["state"]
    assert state["quests"]["find-key"]["status"] == "expired"
