"""v1.6.0 special modes batch 2: deduction (clue + accuse) and roguelike legacy."""

from __future__ import annotations


def deduction_world_payload(request_id: str) -> dict:
    return {
        "request_id": request_id,
        "world_definition": {
            "schema_version": 3,
            "name": "钟楼谜案",
            "lorebook": {"entries": []},
            "character_cards": [],
            "locations": [{"id": "parlor", "name": "宅邸客厅"}, {"id": "tower", "name": "钟楼"}],
            "factions": [],
            "npcs": [],
            "events": [],
            "resources": [],
            "ruleset": {
                "id": "hybrid",
                "enabled_capabilities": [
                    "trpg", "resources", "deduction", "chapters", "choices", "relationships", "routes", "endings",
                ],
            },
            "mystery": {
                "culprit_id": "butler",
                "required_clues": ["broken-gear", "midnight-footstep"],
                "max_accusations": 2,
                "wrong_accusation_ending_id": "scapegoat",
            },
            "story": {
                "chapters": [
                    {"id": "ch1", "title": "钟楼疑云", "order": 1, "next_chapter_id": None,
                     "choices": [
                         {"id": "examine-tower", "label": "检查钟楼",
                          "effects": [{"type": "set_story_flag", "flag_id": "tower-seen", "value": True}]},
                     ]},
                ],
                "flags": [{"id": "tower-seen", "default": False, "writers": ["choice:examine-tower"]}],
                "relationships": [],
                "relationship_events": [],
                "routes": [],
                "endings": [
                    {"id": "scapegoat", "kind": "bad", "priority": 60, "narrative_key": "ending.scapegoat",
                     "title": "替罪之火", "epitaph": "真凶仍在暗处。", "when": {"flag": "__never__", "equals": True}},
                ],
            },
        },
        "hero": {"name": "侦探", "profile": {}},
    }


def roguelike_world_payload(request_id: str, legacy=None) -> dict:
    return {
        "request_id": request_id,
        "world_definition": {
            "schema_version": 3,
            "name": "烬火地窖",
            "lorebook": {"entries": []},
            "character_cards": [],
            "locations": [{"id": "cellar", "name": "地窖"}, {"id": "shrine", "name": "烬火神龛"}],
            "factions": [],
            "npcs": [],
            "events": [],
            "resources": [],
            "ruleset": {
                "id": "hybrid",
                "enabled_capabilities": [
                    "trpg", "resources", "roguelike", "chapters", "choices", "relationships", "routes", "endings",
                ],
            },
            "legacy_config": {
                "boons": [
                    {"id": "ember-charm", "label": "烬火护符：首击伤害 +2"},
                    {"id": "rat-tome", "label": "鼠人典籍：解锁地下暗语"},
                    {"id": "iron-ration", "label": "铁壁干粮：起始补给翻倍"},
                    {"id": "hidden-one", "label": "不应被继承的隐藏加成"},
                ],
            },
            "story": {
                "chapters": [
                    {"id": "ch1", "title": "下潜", "order": 1, "next_chapter_id": None,
                     "choices": [
                         {"id": "descend", "label": "下潜",
                          "effects": [{"type": "set_story_flag", "flag_id": "descended", "value": True}]},
                     ]},
                ],
                "flags": [{"id": "descended", "default": False, "writers": ["choice:descend"]}],
                "relationships": [],
                "relationship_events": [],
                "routes": [],
                "endings": [],
            },
        },
        "hero": {"name": " descending者", "profile": {}},
        **({"legacy": legacy} if legacy is not None else {}),
    }


def _turn(client, run_id: str, request_id: str, revision: int, commands: list[dict]) -> dict:
    response = client.post(
        f"/api/v2/runs/{run_id}/turns",
        json={
            "request_id": request_id,
            "expected_revision": revision,
            "player_input": "我继续调查。",
            "commands": commands,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_deduction_world_collects_clues_and_composes(migrated_client) -> None:
    client, _ = migrated_client
    created = client.post("/api/v2/worlds:compose", json=deduction_world_payload("deduction-compose"))
    assert created.status_code == 201, created.text
    run_id = created.json()["run_id"]
    state = (client.get(f"/api/v2/runs/{run_id}").json())["state"]
    assert state["deduction"] == {"clues": [], "accusations": []}


def test_collect_clue_and_wrong_then_right_accusation(migrated_client) -> None:
    client, _ = migrated_client
    run_id = client.post("/api/v2/worlds:compose", json=deduction_world_payload("deduction-play")).json()["run_id"]

    result = _turn(client, run_id, "clue-1", 0, [
        {"type": "collect_clue", "payload": {"id": "broken-gear", "text": "齿轮上新鲜的撬痕"}},
    ])
    block = result["state"]["deduction"]
    assert [item["id"] for item in block["clues"]] == ["broken-gear"]

    # 重复提交同 id → 更新而不是新增
    result = _turn(client, run_id, "clue-2", 1, [
        {"type": "collect_clue", "payload": {"id": "broken-gear", "text": "撬痕属于管家钥匙"}},
    ])
    assert len(result["state"]["deduction"]["clues"]) == 1

    # 第一次错误指证：未到上限，继续
    result = _turn(client, run_id, "accuse-1", 2, [
        {"type": "accuse", "payload": {"suspect_id": "maid"}},
    ])
    state = result["state"]
    assert state["deduction"]["accusations"][0]["correct"] is False
    assert state["ending"] is None
    assert any(item["type"] == "accusation_wrong" for item in result["outcomes"])

    # 第二次（到达 max_accusations=2）错误指证 → 锁定冤案结局
    result = _turn(client, run_id, "accuse-2", 3, [
        {"type": "accuse", "payload": {"suspect_id": "chef"}},
    ])
    state = result["state"]
    assert state["ending"] is not None
    assert state["ending"]["id"] == "scapegoat"
    assert state["ending"]["kind"] == "bad"

    recovered = client.get(f"/api/v2/runs/{run_id}")
    assert recovered.json()["status"] == "completed"


def test_correct_accusation_locks_good_ending(migrated_client) -> None:
    client, _ = migrated_client
    run_id = client.post("/api/v2/worlds:compose", json=deduction_world_payload("deduction-win")).json()["run_id"]
    result = _turn(client, run_id, "accuse-win", 0, [
        {"type": "accuse", "payload": {"suspect_id": "butler"}},
    ])
    state = result["state"]
    assert state["ending"] == {
        "id": "case-closed",
        "kind": "good",
        "narrative_key": "ending.case_closed",
    }
    assert any(item["type"] == "accusation_correct" for item in result["outcomes"])


def test_deduction_requires_mystery_block(migrated_client) -> None:
    client, _ = migrated_client
    payload = deduction_world_payload("deduction-invalid")
    del payload["world_definition"]["mystery"]
    response = client.post("/api/v2/worlds:compose", json=payload)
    assert response.status_code == 422
    assert "mystery" in response.text


def test_roguelike_legacy_carryover_is_whitelisted_and_capped(migrated_client) -> None:
    client, _ = migrated_client
    payload = roguelike_world_payload("roguelike-compose", legacy=[
        {"id": "ember-charm", "label": "烬火护符：首击伤害 +2"},
        {"id": "rat-tome", "label": "鼠人典籍：解锁地下暗语"},
        {"id": "iron-ration", "label": "铁壁干粮：起始补给翻倍"},
        {"id": "hidden-one", "label": "不应被继承的隐藏加成"},
        {"id": "not-declared", "label": "世界未声明的加成"},
    ])
    created = client.post("/api/v2/worlds:compose", json=payload)
    assert created.status_code == 201, created.text
    boons = created.json()["state"]["legacy"]["boons"]
    assert [boon["id"] for boon in boons] == ["ember-charm", "rat-tome", "iron-ration"]


def test_roguelike_without_legacy_starts_empty(migrated_client) -> None:
    client, _ = migrated_client
    created = client.post("/api/v2/worlds:compose", json=roguelike_world_payload("roguelike-fresh"))
    assert created.status_code == 201, created.text
    assert created.json()["state"]["legacy"] == {"boons": []}
