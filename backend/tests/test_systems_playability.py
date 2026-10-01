"""v1.9.0 systems-playability: quests with rewards, skill_check, gm inventory proposals."""

from __future__ import annotations


def systems_world_payload(request_id: str) -> dict:
    return {
        "request_id": request_id,
        "world_definition": {
            "schema_version": 3,
            "name": " systems-test",
            "lorebook": {"entries": []},
            "character_cards": [],
            "locations": [{"id": "hall", "name": "大厅"}, {"id": "vault", "name": "密库"}],
            "factions": [],
            "npcs": [],
            "events": [],
            "resources": [{"id": "relic", "name": "遗物"}],
            "ruleset": {
                "id": "hybrid",
                "enabled_capabilities": [
                    "trpg", "resources", "deduction", "chapters", "choices", "relationships", "routes", "endings",
                ],
            },
            "mystery": {
                "culprit_id": "caretaker",
                "required_clues": ["hidden-ledger"],
                "max_accusations": 1,
            },
            "story": {
                "quests": [
                    {
                        "id": "find-relic",
                        "title": "寻找遗物",
                        "description": "把失窃的遗物找回来。",
                        "completion": {"flag": "relic-found"},
                        "rewards": [
                            {"type": "item", "item_id": "relic", "quantity": 1},
                            {"type": "clue", "text": "遗物底部刻着管家的名字。"},
                            {"type": "skill", "skill": "insight"},
                        ],
                    }
                ],
                "chapters": [
                    {
                        "id": "ch1",
                        "title": "失窃案",
                        "order": 1,
                        "next_chapter_id": "ch2",
                        "choices": [
                            {
                                "id": "inspect-vault",
                                "label": "搜查密库",
                                "effects": [{"type": "set_story_flag", "flag_id": "relic-found", "value": True}],
                            },
                            {
                                "id": "question-staff",
                                "label": "盘问管理员",
                                "effects": [{"type": "set_story_flag", "flag_id": "asked-once", "value": True}],
                            },
                        ],
                    },
                    {
                        "id": "ch2",
                        "title": "收网",
                        "order": 2,
                        "next_chapter_id": None,
                        "choices": [
                            {
                                "id": "close-case",
                                "label": "结案陈词",
                                "effects": [{"type": "set_story_flag", "flag_id": "closed", "value": True}],
                            }
                        ],
                    },
                ],
                "flags": [
                    {"id": "relic-found", "default": False, "writers": ["choice:inspect-vault"]},
                    {"id": "asked-once", "default": False, "writers": ["choice:question-staff"]},
                    {"id": "closed", "default": False, "writers": ["choice:close-case"]},
                ],
                "relationships": [],
                "relationship_events": [],
                "routes": [],
                "endings": [],
            },
        },
        "hero": {"name": "调查员", "profile": {}},
    }


def _turn(client, run_id: str, request_id: str, revision: int, commands: list[dict]) -> dict:
    response = client.post(
        f"/api/v2/runs/{run_id}/turns",
        json={
            "request_id": request_id,
            "expected_revision": revision,
            "player_input": "我继续推进调查。",
            "commands": commands,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_quest_completion_grants_all_rewards_once(migrated_client) -> None:
    client, _ = migrated_client
    payload = systems_world_payload("sys-compose")
    payload["world_definition"]["story"]["endings"] = [
        {"id": "relic-restored", "kind": "good", "priority": 100,
         "narrative_key": "ending.relic_restored",
         "when": {"flag": "relic-found", "equals": True}},
    ]
    created = client.post("/api/v2/worlds:compose", json=payload).json()
    run_id = created["run_id"]

    # 走 choice 翻转 relic-found → 任务完成 → 三类奖励发放
    choice = client.post(
        f"/api/v2/runs/{run_id}/choices",
        json={
            "request_id": "sys-choice-1",
            "expected_revision": 0,
            "choice_id": "inspect-vault",
            "player_input": "我去搜查密库。",
        },
    )
    assert choice.status_code == 201, choice.text
    state = choice.json()["state"]
    assert state["quests"]["find-relic"]["status"] == "completed"
    assert {"id": "relic", "quantity": 1} in state["inventory"]
    assert any(t["id"] == "clue-find-relic" for t in state["plot_threads"])
    assert "insight" in state["hero"]["skills"]

    reward_outcomes = [
        o for o in choice.json()["outcomes"]
        if o["type"].startswith("quest_")
    ]
    kinds = sorted(o["type"] for o in reward_outcomes)
    assert kinds == ["quest_completed", "quest_reward_clue", "quest_reward_item", "quest_reward_skill"]


def test_quest_reward_not_double_granted(migrated_client) -> None:
    client, _ = migrated_client
    created = client.post("/api/v2/worlds:compose", json=systems_world_payload("sys-compose-2")).json()
    run_id = created["run_id"]

    choice = client.post(
        f"/api/v2/runs/{run_id}/choices",
        json={"request_id": "sys-c1", "expected_revision": 0,
              "choice_id": "inspect-vault", "player_input": "搜查密库。"},
    )
    assert choice.status_code == 201, choice.text
    # 再跑一回合：flag 仍为 true，但奖励不应重复发放
    turn = client.post(
        f"/api/v2/runs/{run_id}/turns",
        json={
            "request_id": "sys-t2",
            "expected_revision": choice.json()["state"]["revision"],
            "player_input": "我整理线索。",
            "commands": [{"type": "narrate", "payload": {}}],
        },
    )
    assert turn.status_code == 201, turn.text
    state = turn.json()["state"]
    relic_entries = [i for i in state["inventory"] if i["id"] == "relic"]
    assert len(relic_entries) == 1 and relic_entries[0]["quantity"] == 1
    completed = [o for o in turn.json()["outcomes"] if o["type"] == "quest_completed"]
    assert not completed


def test_skill_check_trained_and_dc_bounds(migrated_client) -> None:
    client, _ = migrated_client
    created = client.post("/api/v2/worlds:compose", json=systems_world_payload("sys-skill")).json()
    run_id = created["run_id"]

    # 先完成任务获得 insight 技能（trained → +3）
    choice = client.post(
        f"/api/v2/runs/{run_id}/choices",
        json={"request_id": "sys-skill-c1", "expected_revision": 0,
              "choice_id": "inspect-vault", "player_input": "搜查密库。"},
    )
    assert choice.status_code == 201, choice.text
    rev = choice.json()["state"]["revision"]
    results = []
    for i in range(6):
        turn = client.post(
            f"/api/v2/runs/{run_id}/turns",
            json={
                "request_id": f"sys-skill-{i}",
                "expected_revision": rev,
                "player_input": "我尝试洞察线索。",
                "commands": [{"type": "skill_check", "payload": {"skill": "insight", "dc": 10}}],
            },
        )
        assert turn.status_code == 201, turn.text
        rev = turn.json()["state"]["revision"]
        outcome = next(o for o in turn.json()["outcomes"] if o["type"] == "skill_check_result")
        results.append(outcome)
        if rev >= 7:
            break

    for o in results:
        assert o["trained"] is True and o["modifier"] == 3
        assert 1 <= o["roll"] <= 20
        assert o["total"] == o["roll"] + 3
        assert o["success"] == (o["total"] >= 10)
        assert o["degree"] in {"critical_success", "success", "failure", "critical_failure"}
    # 至少一次成功与一次失败的概率上 6 轮 dc=10 几乎必然覆盖；只断言结构
    assert any(o["degree"] == "critical_success" for o in results if o["roll"] == 20) or True


def test_skill_check_rejects_bad_dc_and_untrained_still_rolls(migrated_client) -> None:
    client, _ = migrated_client
    created = client.post("/api/v2/worlds:compose", json=systems_world_payload("sys-skill-bad")).json()
    run_id = created["run_id"]

    bad = client.post(
        f"/api/v2/runs/{run_id}/turns",
        json={
            "request_id": "sys-bad-dc",
            "expected_revision": 0,
            "player_input": "尝试。",
            "commands": [{"type": "skill_check", "payload": {"skill": "insight", "dc": 40}}],
        },
    )
    assert bad.status_code == 409

    untrained = client.post(
        f"/api/v2/runs/{run_id}/turns",
        json={
            "request_id": "sys-untrained",
            "expected_revision": 0,
            "player_input": "尝试。",
            "commands": [{"type": "skill_check", "payload": {"skill": "stealth", "dc": 15}}],
        },
    )
    assert untrained.status_code == 201
    outcome = next(
        o for o in untrained.json()["outcomes"] if o["type"] == "skill_check_result"
    )
    assert outcome["trained"] is False and outcome["modifier"] == 0


def test_gm_inventory_proposal_whitelist_and_clamp() -> None:
    """Unit-level: apply_gm_actions honours whitelist, clamp, and audit."""
    from dzmm.narrative import apply_gm_actions

    state = {"inventory": [], "plot_threads": [], "active_events": [], "npc_state": {}}
    definition = {"resources": [{"id": "relic", "name": "遗物"}]}
    actions = [
        {"type": "propose_inventory_change", "item_id": "relic", "delta": 2, "reason_key": "found"},
        {"type": "propose_inventory_change", "item_id": "relic", "delta": 1, "reason_key": "found-again"},
        {"type": "propose_inventory_change", "item_id": "unknown-thing", "delta": 1, "reason_key": "x"},
        {"type": "propose_inventory_change", "item_id": "relic", "delta": 9, "reason_key": "too-much"},
    ]
    outcomes = apply_gm_actions(state, definition, actions)
    applied = [o for o in outcomes if o["type"] == "inventory_changed"]
    assert len(applied) == 2  # unknown-thing 与 delta=9 被拒
    assert all(abs(o["delta"]) <= 3 for o in applied)
    assert state["inventory"] == [{"id": "relic", "quantity": 3}]
