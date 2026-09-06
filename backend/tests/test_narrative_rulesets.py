from __future__ import annotations


def fog_harbor_payload(request_id: str) -> dict:
    return {
        "request_id": request_id,
        "world_definition": {
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
                    {
                        "id": "shen-confessed",
                        "default": False,
                        "writers": ["choice:shen-confession"],
                    },
                    {
                        "id": "tide-gate-opened",
                        "default": False,
                        "writers": ["choice:open-tide-gate"],
                    },
                    {
                        "id": "tide-gate-failed",
                        "default": False,
                        "writers": ["choice:miss-the-tide"],
                    },
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
                                    {
                                        "type": "set_story_flag",
                                        "flag_id": "lan-rescued",
                                        "value": True,
                                    },
                                    {
                                        "type": "set_story_flag",
                                        "flag_id": "chart-recovered",
                                        "value": True,
                                    },
                                    {
                                        "type": "grant_resource",
                                        "resource_id": "fog-lantern",
                                        "quantity": 1,
                                    },
                                    {
                                        "type": "apply_relationship_event",
                                        "relationship_event_id": "lan-rescued",
                                    },
                                ],
                            },
                            {
                                "id": "hide-chart",
                                "label": "替沈砚藏起航图",
                                "effects": [
                                    {
                                        "type": "set_story_flag",
                                        "flag_id": "chart-recovered",
                                        "value": True,
                                    },
                                    {
                                        "type": "grant_resource",
                                        "resource_id": "fog-lantern",
                                        "quantity": 1,
                                    },
                                    {
                                        "type": "apply_relationship_event",
                                        "relationship_event_id": "shen-protected",
                                    },
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
                                    {
                                        "type": "set_story_flag",
                                        "flag_id": "lan-kept-faith",
                                        "value": True,
                                    },
                                    {"type": "set_route", "route_id": "lan-route"},
                                    {
                                        "type": "apply_relationship_event",
                                        "relationship_event_id": "lan-truth",
                                    },
                                ],
                            },
                            {
                                "id": "shen-confession",
                                "label": "帮助沈砚坦白",
                                "effects": [
                                    {
                                        "type": "set_story_flag",
                                        "flag_id": "shen-confessed",
                                        "value": True,
                                    },
                                    {"type": "set_route", "route_id": "shen-route"},
                                    {
                                        "type": "apply_relationship_event",
                                        "relationship_event_id": "shen-confession",
                                    },
                                ],
                            },
                            {
                                "id": "neutral-lead",
                                "label": "独自追查潮门",
                                "effects": [{"type": "set_route", "route_id": "neutral-route"}],
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
                                "effects": [
                                    {
                                        "type": "set_story_flag",
                                        "flag_id": "tide-gate-opened",
                                        "value": True,
                                    }
                                ],
                            },
                            {
                                "id": "miss-the-tide",
                                "label": "错失潮门",
                                "effects": [
                                    {
                                        "type": "set_story_flag",
                                        "flag_id": "tide-gate-failed",
                                        "value": True,
                                    }
                                ],
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
                                {"relationship": "lan", "dimension": "trust", "at_least": 60},
                                {"relationship": "shen_yan", "dimension": "trust", "at_least": 60},
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


def test_choice_stream_shows_narrative_before_committing_the_validated_choice(
    migrated_client,
) -> None:
    client, _ = migrated_client
    composed = client.post("/api/v2/worlds:compose", json=fog_harbor_payload("fog-stream-choice")).json()
    run_id = composed["run_id"]

    streamed = client.post(
        f"/api/v2/runs/{run_id}/choices:stream",
        json={
            "request_id": "fog-stream-choice-1",
            "expected_revision": 0,
            "player_input": "继续雾港故事",
            "choice_id": "rescue-lan",
        },
    )

    assert streamed.status_code == 200, streamed.text
    assert "event: turn_started" in streamed.text
    assert "event: narrative_delta" in streamed.text
    assert "event: turn_completed" in streamed.text
    recovered = client.get(f"/api/v2/runs/{run_id}").json()
    assert recovered["state"]["revision"] == 1
    assert recovered["state"]["flags"]["lan-rescued"] is True


def test_fog_harbor_good_ending_is_audited_and_recoverable(migrated_client) -> None:
    client, _ = migrated_client
    composed = client.post("/api/v2/worlds:compose", json=fog_harbor_payload("fog-good")).json()
    run_id = composed["run_id"]
    assert composed["state"]["chapter"] == {
        "id": "ch1",
        "status": "active",
        "resolved_choice_ids": [],
    }
    assert composed["state"]["relationships"]["lan"]["dimensions"] == {"affection": 40, "trust": 0}

    first = _choose(client, run_id, 0, "fog-1", "rescue-lan")
    assert first["state"]["chapter"]["id"] == "ch2"
    assert first["state"]["flags"]["lan-rescued"] is True
    assert first["state"]["inventory"] == [{"id": "fog-lantern", "quantity": 1}]
    assert first["state"]["relationships"]["lan"]["dimensions"] == {"affection": 45, "trust": 20}
    assert first["state"]["npc_state"]["lan"]["met"] is True
    assert first["state"]["pending_interactions"][0]["npc_name"] == "岚"
    assert "npc_initiative_scheduled" in {outcome["type"] for outcome in first["outcomes"]}
    assert {outcome["type"] for outcome in first["outcomes"]} >= {
        "choose_story_choice",
        "set_story_flag",
        "grant_resource",
        "apply_relationship_event",
        "advance_chapter",
    }

    second = _choose(client, run_id, 1, "fog-2", "lan-testimony")
    assert second["state"]["chapter"]["id"] == "ch3"
    assert second["state"]["route"] == {"id": "lan-route", "status": "locked"}
    assert second["state"]["relationships"]["lan"]["dimensions"]["trust"] == 40

    third = _choose(client, run_id, 2, "fog-3", "open-tide-gate")
    assert third["state"]["ending"] == {
        "id": "lan-dawn",
        "kind": "good",
        "narrative_key": "ending.lan_dawn",
    }
    completed = client.get(f"/api/v2/runs/{run_id}").json()
    assert completed["status"] == "completed"
    assert completed["story_beats"][-1]["kind"] == "ending"
    assert "结局" in completed["story_beats"][-1]["title"]
    locked = client.post(
        f"/api/v2/runs/{run_id}/turns",
        json={
            "request_id": "fog-locked",
            "expected_revision": 3,
            "player_input": "再向前一步",
            "commands": [{"type": "narrate", "payload": {}}],
        },
    )
    assert locked.status_code == 409
    assert "run has ended" in locked.json()["detail"]

    rollback = client.post(
        f"/api/v2/runs/{run_id}/rollbacks",
        json={
            "request_id": "fog-rollback",
            "expected_revision": 3,
            "target_turn_id": first["turn_id"],
        },
    )
    assert rollback.status_code == 201
    restored = rollback.json()["state"]
    assert restored["revision"] == 4
    assert restored["chapter"]["id"] == "ch2"
    assert restored["ending"] is None
    assert (
        restored["relationships"]["lan"]["applied_events"]["lan-rescued"]["reason_key"]
        == "relation.lan.rescued"
    )
    assert client.get(f"/api/v2/runs/{run_id}").json()["status"] == "active"


def test_fog_harbor_rejects_unavailable_or_direct_state_changes_and_locks_bad_ending(
    migrated_client,
) -> None:
    client, _ = migrated_client
    composed = client.post("/api/v2/worlds:compose", json=fog_harbor_payload("fog-bad")).json()
    run_id = composed["run_id"]

    invalid = client.post(
        f"/api/v2/runs/{run_id}/turns",
        json={
            "request_id": "fog-invalid",
            "expected_revision": 0,
            "player_input": "我直接刷好感",
            "commands": [
                {"type": "set_story_flag", "payload": {"flag_id": "lan-rescued", "value": True}}
            ],
        },
    )
    assert invalid.status_code == 409
    assert "choices endpoint" in invalid.json()["detail"]
    assert client.get(f"/api/v2/runs/{run_id}").json()["state"]["revision"] == 0
    streamed = client.post(
        f"/api/v2/runs/{run_id}/turns:stream",
        json={
            "request_id": "fog-stream-invalid",
            "expected_revision": 0,
            "player_input": "我直接刷好感",
            "commands": [
                {"type": "set_story_flag", "payload": {"flag_id": "lan-rescued", "value": True}}
            ],
        },
    )
    assert streamed.status_code == 200
    assert "event: turn_failed" in streamed.text
    assert "choices endpoint" in streamed.text
    assert client.get(f"/api/v2/runs/{run_id}").json()["state"]["revision"] == 0

    _choose(client, run_id, 0, "fog-bad-1", "hide-chart")
    _choose(client, run_id, 1, "fog-bad-2", "neutral-lead")
    final = _choose(client, run_id, 2, "fog-bad-3", "miss-the-tide")
    assert final["state"]["ending"] == {
        "id": "fog-drowned",
        "kind": "bad",
        "narrative_key": "ending.fog_drowned",
    }


def test_choice_world_accepts_free_action_as_a_gm_led_story_turn(migrated_client) -> None:
    client, _ = migrated_client
    composed = client.post("/api/v2/worlds:compose", json=fog_harbor_payload("fog-free-action")).json()
    run_id = composed["run_id"]

    response = client.post(
        f"/api/v2/runs/{run_id}/turns",
        json={
            "request_id": "fog-free-action-1",
            "expected_revision": 0,
            "player_input": "我不选预设选项，先蹲下观察潮水里有没有脚印",
            "commands": [{"type": "narrate", "payload": {}}],
        },
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["state"]["revision"] == 1
    assert body["state"]["narrative_context"]["run_seed"] == run_id
    assert len(body["state"]["narrative_context"]["recent_turns"]) == 1


def test_narrative_definition_rejects_invalid_relationship_dimension(migrated_client) -> None:
    client, _ = migrated_client
    payload = fog_harbor_payload("fog-invalid-definition")
    payload["world_definition"]["story"]["relationship_events"][0]["deltas"] = {"devotion": 20}

    response = client.post("/api/v2/worlds:compose", json=payload)

    assert response.status_code == 422
    assert "undefined dimension" in response.json()["detail"]


def test_narrative_definition_keeps_cards_portable_and_requires_known_relationship(
    migrated_client,
) -> None:
    client, _ = migrated_client
    card_payload = fog_harbor_payload("fog-card-boundary")
    card_payload["world_definition"]["character_cards"][0]["relationship_dimensions"] = {"trust": 0}

    card_response = client.post("/api/v2/worlds:compose", json=card_payload)

    assert card_response.status_code == 422
    assert "relationship_dimensions" in card_response.json()["detail"]

    relationship_payload = fog_harbor_payload("fog-missing-relationship")
    relationship_payload["world_definition"]["story"]["relationship_events"][0][
        "relationship_id"
    ] = "missing"

    relationship_response = client.post("/api/v2/worlds:compose", json=relationship_payload)

    assert relationship_response.status_code == 422
    assert "unknown relationship" in relationship_response.json()["detail"]


def test_same_character_card_can_have_different_relationship_rules_per_world_version(
    migrated_client,
) -> None:
    client, _ = migrated_client
    bounded = fog_harbor_payload("fog-bounded-relationship")
    bounded["world_definition"]["story"]["relationships"][0]["dimensions"]["trust"] = {
        "initial": 10,
        "min": -10,
        "max": 10,
    }
    unbounded = fog_harbor_payload("fog-unbounded-relationship")
    unbounded["world_definition"]["story"]["relationships"][0]["dimensions"]["trust"] = {
        "initial": -20,
        "min": -100,
        "max": 100,
    }

    bounded_run = client.post("/api/v2/worlds:compose", json=bounded).json()
    unbounded_run = client.post("/api/v2/worlds:compose", json=unbounded).json()
    bounded_result = _choose(client, bounded_run["run_id"], 0, "fog-bounded-choice", "rescue-lan")
    unbounded_result = _choose(
        client, unbounded_run["run_id"], 0, "fog-unbounded-choice", "rescue-lan"
    )

    assert bounded_result["state"]["relationships"]["lan"]["dimensions"]["trust"] == 10
    assert unbounded_result["state"]["relationships"]["lan"]["dimensions"]["trust"] == 0


def test_choice_endpoint_only_accepts_a_current_choice_and_is_idempotent(migrated_client) -> None:
    client, _ = migrated_client
    composed = client.post(
        "/api/v2/worlds:compose", json=fog_harbor_payload("fog-choice-endpoint")
    ).json()
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
        json={
            **payload,
            "request_id": "fog-choice-invalid",
            "expected_revision": 1,
            "choice_id": "rescue-lan",
        },
    )
    assert unavailable.status_code == 409
    assert "not available" in unavailable.json()["detail"]


def test_choice_maps_model_narration_failure_without_committing_state(
    migrated_client, monkeypatch
) -> None:
    client, _ = migrated_client

    async def failing_narrate(*_args, **_kwargs):
        from dzmm.model_profiles import NarrationError

        raise NarrationError("model connection failed: timed out")

    monkeypatch.setattr(client.app.state.turn_coordinator._narrator, "narrate", failing_narrate)
    profile = client.post(
        "/api/v2/model-profiles",
        json={
            "name": "failing narrator",
            "provider_type": "ollama",
            "base_url": "http://127.0.0.1:11434",
            "model_name": "test-model",
        },
    )
    payload = fog_harbor_payload("fog-choice-narration-failure")
    payload["model_profile_id"] = profile.json()["id"]
    composed = client.post("/api/v2/worlds:compose", json=payload).json()

    response = client.post(
        f"/api/v2/runs/{composed['run_id']}/choices",
        json={
            "request_id": "fog-choice-narration-failure-turn",
            "expected_revision": 0,
            "player_input": "救岚",
            "choice_id": "rescue-lan",
        },
    )

    assert response.status_code == 502
    assert response.json()["detail"] == "model connection failed: timed out"
    assert client.get(f"/api/v2/runs/{composed['run_id']}").json()["state"]["revision"] == 0


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


def test_fog_harbor_template_can_reach_its_hidden_ending(migrated_client) -> None:
    client, _ = migrated_client
    template = client.get("/api/v2/world-templates/fog-harbor").json()
    template["request_id"] = "fog-template-hidden"
    composed = client.post("/api/v2/worlds:compose", json=template).json()
    run_id = composed["run_id"]

    first = _choose(client, run_id, 0, "fog-hidden-1", "rescue-lan")
    second = _choose(client, run_id, 1, "fog-hidden-2", "unite-witnesses")
    final = _choose(client, run_id, 2, "fog-hidden-3", "open-tide-gate")

    assert second["state"]["flags"]["heard-the-bell"] is True
    assert second["state"]["route"] == {"id": "neutral-route", "status": "locked"}
    assert second["state"]["relationships"]["lan"]["dimensions"]["trust"] == 60
    assert second["state"]["relationships"]["shen_yan"]["dimensions"]["trust"] == 60
    assert final["state"]["ending"] == {
        "id": "bell-beyond-fog",
        "kind": "hidden",
        "narrative_key": "ending.bell",
    }
    assert first["state"]["ending"] is None


def test_fog_harbor_template_reaches_route_and_fallback_endings(migrated_client) -> None:
    client, _ = migrated_client
    template = client.get("/api/v2/world-templates/fog-harbor").json()

    lan = client.post(
        "/api/v2/worlds:compose", json={**template, "request_id": "fog-template-lan"}
    ).json()
    _choose(client, lan["run_id"], 0, "fog-lan-1", "rescue-lan")
    _choose(client, lan["run_id"], 1, "fog-lan-2", "lan-testimony")
    lan_final = _choose(client, lan["run_id"], 2, "fog-lan-3", "open-tide-gate")

    shen = client.post(
        "/api/v2/worlds:compose", json={**template, "request_id": "fog-template-shen"}
    ).json()
    _choose(client, shen["run_id"], 0, "fog-shen-1", "hide-chart")
    _choose(client, shen["run_id"], 1, "fog-shen-2", "shen-confession")
    shen_final = _choose(client, shen["run_id"], 2, "fog-shen-3", "open-tide-gate")

    neutral = client.post(
        "/api/v2/worlds:compose", json={**template, "request_id": "fog-template-neutral"}
    ).json()
    _choose(client, neutral["run_id"], 0, "fog-neutral-1", "hide-chart")
    _choose(client, neutral["run_id"], 1, "fog-neutral-2", "neutral-lead")
    neutral_final = _choose(client, neutral["run_id"], 2, "fog-neutral-3", "open-tide-gate")

    bad = client.post(
        "/api/v2/worlds:compose", json={**template, "request_id": "fog-template-bad"}
    ).json()
    _choose(client, bad["run_id"], 0, "fog-bad-template-1", "hide-chart")
    _choose(client, bad["run_id"], 1, "fog-bad-template-2", "neutral-lead")
    bad_final = _choose(client, bad["run_id"], 2, "fog-bad-template-3", "miss-the-tide")

    assert lan_final["state"]["ending"]["id"] == "lan-dawn"
    assert shen_final["state"]["ending"]["id"] == "shen-low-tide"
    assert neutral_final["state"]["ending"]["id"] == "neutral-harbor"
    assert bad_final["state"]["ending"]["id"] == "fog-drowned"


def test_relationship_once_event_rejects_the_whole_turn_without_state_write(
    migrated_client,
) -> None:
    client, _ = migrated_client
    payload = fog_harbor_payload("fog-once")
    payload["world_definition"]["story"]["chapters"][1]["choices"][0]["effects"].append(
        {"type": "apply_relationship_event", "relationship_event_id": "lan-rescued"}
    )
    composed = client.post("/api/v2/worlds:compose", json=payload).json()
    run_id = composed["run_id"]
    _choose(client, run_id, 0, "fog-once-1", "rescue-lan")

    repeated = client.post(
        f"/api/v2/runs/{run_id}/choices",
        json={
            "request_id": "fog-once-2",
            "expected_revision": 1,
            "player_input": "再次要求岚相信我",
            "choice_id": "lan-testimony",
        },
    )

    assert repeated.status_code == 409
    assert "once per run" in repeated.json()["detail"]
    state = client.get(f"/api/v2/runs/{run_id}").json()["state"]
    assert state["revision"] == 1
    assert state["chapter"]["id"] == "ch2"
    assert state["relationships"]["lan"]["dimensions"] == {"affection": 45, "trust": 20}


def test_relationship_cooldown_rejects_the_whole_turn_without_state_write(migrated_client) -> None:
    client, _ = migrated_client
    payload = fog_harbor_payload("fog-cooldown")
    events = payload["world_definition"]["story"]["relationship_events"]
    events[0]["once_scope"] = "none"
    events[0]["cooldown_turns"] = 2
    payload["world_definition"]["story"]["chapters"][1]["choices"][0]["effects"].append(
        {"type": "apply_relationship_event", "relationship_event_id": "lan-rescued"}
    )
    composed = client.post("/api/v2/worlds:compose", json=payload).json()
    run_id = composed["run_id"]
    _choose(client, run_id, 0, "fog-cooldown-1", "rescue-lan")

    cooling = client.post(
        f"/api/v2/runs/{run_id}/choices",
        json={
            "request_id": "fog-cooldown-2",
            "expected_revision": 1,
            "player_input": "再要求岚相信我",
            "choice_id": "lan-testimony",
        },
    )

    assert cooling.status_code == 409
    assert "cooling down" in cooling.json()["detail"]
    state = client.get(f"/api/v2/runs/{run_id}").json()["state"]
    assert state["revision"] == 1
    assert state["chapter"]["id"] == "ch2"
