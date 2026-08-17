from __future__ import annotations


def fog_harbor_payload(request_id: str) -> dict:
    return {
        "request_id": request_id,
        "world_definition": {
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
                    {"id": "chart-recovered", "default": False, "writers": ["choice:rescue-lan", "choice:hide-chart"]},
                    {"id": "lan-kept-faith", "default": False, "writers": ["choice:lan-testimony"]},
                    {"id": "shen-confessed", "default": False, "writers": ["choice:shen-confession"]},
                    {"id": "tide-gate-opened", "default": False, "writers": ["choice:open-tide-gate"]},
                    {"id": "tide-gate-failed", "default": False, "writers": ["choice:miss-the-tide"]},
                ],
                "relationship_events": [
                    {"id": "lan-rescued", "character_card_id": "lan", "deltas": {"affection": 5, "trust": 20}, "reason_key": "relation.lan.rescued", "once_scope": "run", "cooldown_turns": 0},
                    {"id": "lan-truth", "character_card_id": "lan", "deltas": {"trust": 20}, "reason_key": "relation.lan.truth", "once_scope": "run", "cooldown_turns": 0},
                    {"id": "shen-protected", "character_card_id": "shen_yan", "deltas": {"affection": 8, "trust": 15}, "reason_key": "relation.shen.protected", "once_scope": "run", "cooldown_turns": 0},
                    {"id": "shen-confession", "character_card_id": "shen_yan", "deltas": {"affection": 10, "trust": 25}, "reason_key": "relation.shen.confession", "once_scope": "run", "cooldown_turns": 0},
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
                            {"id": "rescue-lan", "label": "救岚", "effects": [{"type": "set_story_flag", "flag_id": "lan-rescued", "value": True}, {"type": "set_story_flag", "flag_id": "chart-recovered", "value": True}, {"type": "grant_resource", "resource_id": "fog-lantern", "quantity": 1}, {"type": "apply_relationship_event", "relationship_event_id": "lan-rescued"}]},
                            {"id": "hide-chart", "label": "替沈砚藏起航图", "effects": [{"type": "set_story_flag", "flag_id": "chart-recovered", "value": True}, {"type": "grant_resource", "resource_id": "fog-lantern", "quantity": 1}, {"type": "apply_relationship_event", "relationship_event_id": "shen-protected"}]},
                        ],
                    },
                    {
                        "id": "ch2",
                        "title": "沉船的证词",
                        "order": 2,
                        "next_chapter_id": "ch3",
                        "choices": [
                            {"id": "lan-testimony", "label": "把证词交给岚", "effects": [{"type": "set_story_flag", "flag_id": "lan-kept-faith", "value": True}, {"type": "set_route", "route_id": "lan-route"}, {"type": "apply_relationship_event", "relationship_event_id": "lan-truth"}]},
                            {"id": "shen-confession", "label": "帮助沈砚坦白", "effects": [{"type": "set_story_flag", "flag_id": "shen-confessed", "value": True}, {"type": "set_route", "route_id": "shen-route"}, {"type": "apply_relationship_event", "relationship_event_id": "shen-confession"}]},
                            {"id": "neutral-lead", "label": "独自追查潮门", "effects": [{"type": "set_route", "route_id": "neutral-route"}]},
                        ],
                    },
                    {
                        "id": "ch3",
                        "title": "潮门之夜",
                        "order": 3,
                        "next_chapter_id": None,
                        "choices": [
                            {"id": "open-tide-gate", "label": "点亮雾灯", "effects": [{"type": "set_story_flag", "flag_id": "tide-gate-opened", "value": True}]},
                            {"id": "miss-the-tide", "label": "错失潮门", "effects": [{"type": "set_story_flag", "flag_id": "tide-gate-failed", "value": True}]},
                        ],
                    },
                ],
                "endings": [
                    {"id": "bell-beyond-fog", "kind": "hidden", "priority": 120, "narrative_key": "ending.bell", "when": {"all": [{"flag": "tide-gate-opened", "equals": True}, {"relationship": "lan", "dimension": "trust", "at_least": 60}, {"relationship": "shen_yan", "dimension": "trust", "at_least": 60}]}},
                    {"id": "lan-dawn", "kind": "good", "priority": 100, "narrative_key": "ending.lan_dawn", "when": {"all": [{"flag": "tide-gate-opened", "equals": True}, {"route": "lan-route"}, {"relationship": "lan", "dimension": "trust", "at_least": 40}, {"relationship": "lan", "dimension": "affection", "at_least": 45}]}},
                    {"id": "shen-low-tide", "kind": "good", "priority": 95, "narrative_key": "ending.shen_low_tide", "when": {"all": [{"flag": "tide-gate-opened", "equals": True}, {"route": "shen-route"}, {"relationship": "shen_yan", "dimension": "trust", "at_least": 40}]}},
                    {"id": "neutral-harbor", "kind": "normal", "priority": 50, "narrative_key": "ending.neutral", "when": {"flag": "tide-gate-opened", "equals": True}},
                    {"id": "fog-drowned", "kind": "bad", "priority": 0, "narrative_key": "ending.fog_drowned", "when": {"flag": "tide-gate-failed", "equals": True}},
                ],
            },
        },
        "hero": {"name": "米拉", "profile": {"origin": "水手"}},
    }


def _choose(client, run_id: str, revision: int, request_id: str, choice_id: str) -> dict:
    response = client.post(
        f"/api/v2/runs/{run_id}/choices",
        json={
            "request_id": request_id,
            "expected_revision": revision,
            "player_input": "继续雾港故事",
            "choice_id": choice_id,
        },
    )
    assert response.status_code == 201, response.json()
    return response.json()


def test_fog_harbor_good_ending_is_audited_and_recoverable(migrated_client) -> None:
    client, _ = migrated_client
    composed = client.post("/api/v2/worlds:compose", json=fog_harbor_payload("fog-good")).json()
    run_id = composed["run_id"]
    assert composed["state"]["chapter"] == {"id": "ch1", "status": "active", "resolved_choice_ids": []}
    assert composed["state"]["relationships"]["lan"]["dimensions"] == {"affection": 40, "trust": 0}

    first = _choose(client, run_id, 0, "fog-1", "rescue-lan")
    assert first["state"]["chapter"]["id"] == "ch2"
    assert first["state"]["flags"]["lan-rescued"] is True
    assert first["state"]["inventory"] == [{"id": "fog-lantern", "quantity": 1}]
    assert first["state"]["relationships"]["lan"]["dimensions"] == {"affection": 45, "trust": 20}
    assert {outcome["type"] for outcome in first["outcomes"]} >= {"choose_story_choice", "set_story_flag", "grant_resource", "apply_relationship_event", "advance_chapter"}

    second = _choose(client, run_id, 1, "fog-2", "lan-testimony")
    assert second["state"]["chapter"]["id"] == "ch3"
    assert second["state"]["route"] == {"id": "lan-route", "status": "locked"}
    assert second["state"]["relationships"]["lan"]["dimensions"]["trust"] == 40

    third = _choose(client, run_id, 2, "fog-3", "open-tide-gate")
    assert third["state"]["ending"] == {"id": "lan-dawn", "kind": "good", "narrative_key": "ending.lan_dawn"}
    locked = client.post(f"/api/v2/runs/{run_id}/turns", json={"request_id": "fog-locked", "expected_revision": 3, "player_input": "再向前一步", "commands": [{"type": "narrate", "payload": {}}]})
    assert locked.status_code == 409
    assert "choices endpoint" in locked.json()["detail"]

    rollback = client.post(f"/api/v2/runs/{run_id}/rollbacks", json={"request_id": "fog-rollback", "expected_revision": 3, "target_turn_id": first["turn_id"]})
    assert rollback.status_code == 201
    restored = rollback.json()["state"]
    assert restored["revision"] == 4
    assert restored["chapter"]["id"] == "ch2"
    assert restored["ending"] is None
    assert restored["relationships"]["lan"]["applied_events"]["lan-rescued"]["reason_key"] == "relation.lan.rescued"


def test_fog_harbor_rejects_unavailable_or_direct_state_changes_and_locks_bad_ending(migrated_client) -> None:
    client, _ = migrated_client
    composed = client.post("/api/v2/worlds:compose", json=fog_harbor_payload("fog-bad")).json()
    run_id = composed["run_id"]

    invalid = client.post(f"/api/v2/runs/{run_id}/turns", json={"request_id": "fog-invalid", "expected_revision": 0, "player_input": "我直接刷好感", "commands": [{"type": "set_story_flag", "payload": {"flag_id": "lan-rescued", "value": True}}]})
    assert invalid.status_code == 409
    assert "choices endpoint" in invalid.json()["detail"]
    assert client.get(f"/api/v2/runs/{run_id}").json()["state"]["revision"] == 0
    streamed = client.post(
        f"/api/v2/runs/{run_id}/turns:stream",
        json={
            "request_id": "fog-stream-invalid",
            "expected_revision": 0,
            "player_input": "我直接刷好感",
            "commands": [{"type": "set_story_flag", "payload": {"flag_id": "lan-rescued", "value": True}}],
        },
    )
    assert streamed.status_code == 200
    assert "event: turn_failed" in streamed.text
    assert "choices endpoint" in streamed.text
    assert client.get(f"/api/v2/runs/{run_id}").json()["state"]["revision"] == 0

    _choose(client, run_id, 0, "fog-bad-1", "hide-chart")
    _choose(client, run_id, 1, "fog-bad-2", "neutral-lead")
    final = _choose(client, run_id, 2, "fog-bad-3", "miss-the-tide")
    assert final["state"]["ending"] == {"id": "fog-drowned", "kind": "bad", "narrative_key": "ending.fog_drowned"}


def test_narrative_definition_rejects_invalid_relationship_dimension(migrated_client) -> None:
    client, _ = migrated_client
    payload = fog_harbor_payload("fog-invalid-definition")
    payload["world_definition"]["story"]["relationship_events"][0]["deltas"] = {"devotion": 20}

    response = client.post("/api/v2/worlds:compose", json=payload)

    assert response.status_code == 422
    assert "undefined dimension" in response.json()["detail"]


def test_choice_endpoint_only_accepts_a_current_choice_and_is_idempotent(migrated_client) -> None:
    client, _ = migrated_client
    composed = client.post("/api/v2/worlds:compose", json=fog_harbor_payload("fog-choice-endpoint")).json()
    run_id = composed["run_id"]
    snapshot = client.get(f"/api/v2/runs/{run_id}")
    assert snapshot.status_code == 200
    assert snapshot.json()["available_choices"] == [
        {"id": "rescue-lan", "label": "救岚"},
        {"id": "hide-chart", "label": "替沈砚藏起航图"},
    ]

    payload = {
        "request_id": "fog-choice-1",
        "expected_revision": 0,
        "player_input": "我冲进潮雾救岚。",
        "choice_id": "rescue-lan",
    }
    chosen = client.post(f"/api/v2/runs/{run_id}/choices", json=payload)
    assert chosen.status_code == 201
    assert chosen.json()["state"]["chapter"]["id"] == "ch2"
    assert chosen.json()["commands"] == [
        {"type": "choose_story_choice", "payload": {"choice_id": "rescue-lan"}},
        {"type": "advance_chapter", "payload": {}},
    ]

    retry = client.post(f"/api/v2/runs/{run_id}/choices", json=payload)
    assert retry.status_code == 200
    assert retry.json()["turn_id"] == chosen.json()["turn_id"]
    unavailable = client.post(
        f"/api/v2/runs/{run_id}/choices",
        json={**payload, "request_id": "fog-choice-invalid", "expected_revision": 1, "choice_id": "rescue-lan"},
    )
    assert unavailable.status_code == 409
    assert "not available" in unavailable.json()["detail"]


def test_fog_harbor_template_is_a_composable_hybrid_world(migrated_client) -> None:
    client, _ = migrated_client
    template = client.get("/api/v2/world-templates/fog-harbor")
    assert template.status_code == 200
    payload = template.json()
    payload["request_id"] = "fog-template"

    composed = client.post("/api/v2/worlds:compose", json=payload)

    assert composed.status_code == 201
    assert composed.json()["state"]["ruleset"]["id"] == "hybrid"
    assert composed.json()["state"]["chapter"]["id"] == "ch1"


def test_relationship_once_event_rejects_the_whole_turn_without_state_write(migrated_client) -> None:
    client, _ = migrated_client
    payload = fog_harbor_payload("fog-once")
    payload["world_definition"]["story"]["chapters"][1]["choices"][0]["effects"].append(
        {"type": "apply_relationship_event", "relationship_event_id": "lan-rescued"}
    )
    composed = client.post("/api/v2/worlds:compose", json=payload).json()
    run_id = composed["run_id"]
    _choose(client, run_id, 0, "fog-once-1", "rescue-lan")

    repeated = client.post(f"/api/v2/runs/{run_id}/choices", json={"request_id": "fog-once-2", "expected_revision": 1, "player_input": "再次要求岚相信我", "choice_id": "lan-testimony"})

    assert repeated.status_code == 409
    assert "once per run" in repeated.json()["detail"]
    state = client.get(f"/api/v2/runs/{run_id}").json()["state"]
    assert state["revision"] == 1
    assert state["chapter"]["id"] == "ch2"
    assert state["relationships"]["lan"]["dimensions"] == {"affection": 45, "trust": 20}
