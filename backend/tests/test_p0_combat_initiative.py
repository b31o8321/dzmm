"""P0 增强：自由回合战斗 + proactive NPC 首次主动接触。

背景（12 维度评估 §七）：combat 引擎存在但主题世界从未开启；NPC 主动性
机制只覆盖已接触 NPC——没见过面的 NPC 永远无法发起联系（鸡生蛋）。
"""

from __future__ import annotations


def _world_payload(request_id: str, *, proactive: bool = False) -> dict:
    definition = {
        "schema_version": 3,
        "name": "边境哨站" if not proactive else "驿站来客",
        "lorebook": {"entries": []},
        "character_cards": [],
        "locations": [{"id": "camp", "name": "营地"}, {"id": "ridge", "name": "山脊"}],
        "factions": [],
        "npcs": [
            {
                "id": "raider",
                "name": "劫掠者",
                "location_id": "camp",
                "combat": {"max_hp": 8, "ac": 10, "attack_bonus": 1},
            }
        ],
        "events": [],
        "resources": [],
        "ruleset": {
            "id": "hybrid",
            "enabled_capabilities": [
                "trpg",
                "combat",
                "chapters",
                "choices",
                "endings",
            ],
        },
        "story": {
            "quests": [],
            "chapters": [
                {
                    "id": "ch1",
                    "title": "一章",
                    "order": 1,
                    "next_chapter_id": None,
                    "choices": [
                        {
                            "id": "rest",
                            "label": "休息",
                            "effects": [
                                {"type": "set_story_flag", "flag_id": "rested", "value": True}
                            ],
                        }
                    ],
                }
            ],
            "flags": [{"id": "rested", "default": False, "writers": ["choice:rest"]}],
            "relationships": [],
            "relationship_events": [],
            "routes": [],
            "endings": [
                {
                    "id": "done",
                    "kind": "normal",
                    "priority": 1,
                    "narrative_key": "ending.done",
                    "when": {"flag": "rested", "equals": True},
                }
            ],
        },
    }
    if proactive:
        definition["npcs"].append(
            {
                "id": "scout",
                "name": "斥候",
                "location_id": "ridge",
                "proactive": True,
            }
        )
    return {
        "request_id": request_id,
        "world_definition": definition,
        "hero": {"name": "哨兵", "profile": {}},
        "sandbox": True,
    }


def _turn(client, run_id: str, revision: int, request_id: str, commands: list[dict]):
    response = client.post(
        f"/api/v2/runs/{run_id}/turns",
        json={
            "request_id": request_id,
            "expected_revision": revision,
            "player_input": "我继续行动。",
            "commands": commands,
        },
    )
    return response


def test_attack_works_in_free_turns_of_choices_world(migrated_client) -> None:
    """choices 门禁不应拦截引擎裁决的 attack；战斗数值由引擎决定。"""

    client, _ = migrated_client
    compose = client.post("/api/v2/worlds:compose", json=_world_payload("atk-compose"))
    assert compose.status_code in (200, 201), compose.text
    run_id = compose.json()["run_id"]
    revision = compose.json()["state"]["revision"]

    defeated = False
    attacks = 0
    for i in range(20):
        response = _turn(
            client,
            run_id,
            revision,
            f"atk-t{i}",
            [{"type": "attack", "payload": {"target_id": "raider"}}, {"type": "narrate", "payload": {}}],
        )
        if defeated:
            # 倒下后继续攻击应被 409 拒绝
            assert response.status_code == 409, response.text
            break
        assert response.status_code == 201, response.text
        body = response.json()
        revision = body["state"]["revision"]
        attack_outcomes = [o for o in body["outcomes"] if o.get("type") == "attack"]
        assert attack_outcomes, body["outcomes"]
        outcome = attack_outcomes[0]
        assert 1 <= outcome["roll"] <= 20
        assert outcome["target_hp"] >= 0
        attacks += 1
        defeated = bool(outcome["defeated"])
        if defeated:
            state = client.get(f"/api/v2/runs/{run_id}").json()["state"]
            participants = state["combat"]["participants"]
            assert participants["raider"]["hp"] == 0
            assert participants["raider"]["defeated"] is True
    assert defeated, f"{attacks} 次攻击内未击倒（max_hp=8 应足够）"


def test_proactive_unmet_npc_initiates_first_contact(migrated_client) -> None:
    """未接触的 proactive NPC 可远程发起首次主动接触。"""

    client, _ = migrated_client
    compose = client.post(
        "/api/v2/worlds:compose", json=_world_payload("pro-compose", proactive=True)
    )
    assert compose.status_code in (200, 201), compose.text
    run_id = compose.json()["run_id"]
    revision = compose.json()["state"]["revision"]

    first = _turn(client, run_id, revision, "pro-t0", [{"type": "narrate", "payload": {}}])
    assert first.status_code == 201, first.text
    body = first.json()
    revision = body["state"]["revision"]
    scheduled = [o for o in body["outcomes"] if o.get("type") == "npc_initiative_scheduled"]
    assert scheduled, body["outcomes"]
    assert scheduled[0]["npc_id"] == "scout"
    assert scheduled[0]["first_contact"] is True

    # 下一回合：pending 进入 payload 并被结算，未堆积
    second = _turn(client, run_id, revision, "pro-t1", [{"type": "narrate", "payload": {}}])
    assert second.status_code == 201, second.text
    types = [o.get("type") for o in second.json()["outcomes"]]
    assert "npc_initiative_resolved" in types
    assert second.json()["state"]["pending_interactions"] == []
    # met 翻转由叙事中出现 NPC 名触发（_record_npc_presence）；确定性叙述
    # 占位文本不含名字，此处不断言——真实模型首触场景自然完成初见。


def test_non_proactive_unmet_npc_never_initiates(migrated_client) -> None:
    """未接触且非主动型的 NPC 不进入候选（回归保护）。"""

    client, _ = migrated_client
    compose = client.post("/api/v2/worlds:compose", json=_world_payload("np-compose"))
    assert compose.status_code in (200, 201), compose.text
    run_id = compose.json()["run_id"]
    revision = compose.json()["state"]["revision"]

    for i in range(3):
        response = _turn(client, run_id, revision, f"np-t{i}", [{"type": "narrate", "payload": {}}])
        assert response.status_code == 201, response.text
        revision = response.json()["state"]["revision"]
        types = [o.get("type") for o in response.json()["outcomes"]]
        assert "npc_initiative_scheduled" not in types
        assert response.json()["state"]["pending_interactions"] == []
