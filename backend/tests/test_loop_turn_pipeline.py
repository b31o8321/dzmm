"""v1.4.0 integration: time cost, anchor rewind and death trigger in the turn pipeline."""

from __future__ import annotations


def time_world_payload(request_id: str) -> dict:
    # hybrid 规则集要求 chapters/choices/endings；无 loop_config 即纯时间世界
    payload = loop_world_payload(request_id, trigger=None)
    payload["world_definition"]["name"] = "黯星余烬"
    payload["world_definition"]["ruleset"]["enabled_capabilities"] = [
        "trpg",
        "resources",
        "time",
        "chapters",
        "choices",
        "endings",
    ]
    payload["hero"] = {"name": "林浩", "profile": {}}
    return payload


def loop_world_payload(
    request_id: str,
    *,
    trigger: list[str] | None = None,
    max_loops: int = 3,
    loop_at_minutes: int | None = 390,
) -> dict:
    definition = {
        "schema_version": 3,
        "name": "时之沙漏·永夜回廊",
        "lorebook": {"entries": []},
        "character_cards": [],
        "locations": [{"id": "corridor", "name": "永夜回廊"}, {"id": "clocktower", "name": "倒钟楼"}],
        "factions": [],
        "npcs": [],
        "events": [],
        "resources": [],
        "ruleset": {
            "id": "hybrid",
            "enabled_capabilities": [
                "trpg",
                "resources",
                "combat",
                "time",
                "loop",
                "chapters",
                "choices",
                "endings",
            ],
        },
        "time_system": {
            "start_minutes": 360,
            "per_turn_max": 240,
            "unit": "分钟",
        },
        "story": {
            "chapters": [
                {
                    "id": "ch1",
                    "title": "第 1 次循环",
                    "order": 1,
                    "next_chapter_id": None,
                    "choices": [
                        {
                            "id": "escape-loop",
                            "label": "打破循环",
                            "effects": [
                                {"type": "set_story_flag", "flag_id": "escaped", "value": True}
                            ],
                        },
                        {
                            "id": "give-up",
                            "label": "放弃挣扎",
                            "effects": [
                                {"type": "set_story_flag", "flag_id": "gave-up", "value": True}
                            ],
                        },
                    ],
                }
            ],
            "flags": [
                {"id": "escaped", "default": False, "writers": ["choice:escape-loop"]},
                {"id": "gave-up", "default": False, "writers": ["choice:give-up"]},
            ],
            "relationships": [],
            "relationship_events": [],
            "routes": [],
            "endings": [
                {
                    "id": "escape",
                    "kind": "good",
                    "priority": 100,
                    "narrative_key": "ending.loop_escape",
                    "title": "循环破晓",
                    "epitaph": "时间终于向前走了。",
                    "when": {"flag": "escaped", "equals": True},
                },
                {
                    "id": "stuck",
                    "kind": "bad",
                    "priority": 50,
                    "narrative_key": "ending.stuck",
                    "title": "永劫回归",
                    "epitaph": "闹钟再次响起。",
                    "when": {"flag": "gave-up", "equals": True},
                },
            ],
        },
    }
    if loop_at_minutes is not None:
        definition["time_system"]["loop_at_minutes"] = loop_at_minutes
    if trigger is not None:
        definition["loop_config"] = {"max_loops": max_loops, "trigger": trigger}
    return {
        "request_id": request_id,
        "world_definition": definition,
        "hero": {"name": "循环者", "profile": {}},
    }


def _turn(client, run_id: str, request_id: str, revision: int, commands: list[dict]) -> dict:
    response = client.post(
        f"/api/v2/runs/{run_id}/turns",
        json={
            "request_id": request_id,
            "expected_revision": revision,
            "player_input": "我在回廊中辨认昨日的裂痕。",
            "commands": commands,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_time_capability_advances_clock_each_turn(migrated_client) -> None:
    client, _ = migrated_client
    created = client.post("/api/v2/worlds:compose", json=time_world_payload("time-world"))
    assert created.status_code == 201, created.text
    run_id = created.json()["run_id"]

    result = _turn(client, run_id, "t1", 0, [{"type": "narrate", "payload": {}}])
    state = result["state"]
    assert state["clock"]["now_minutes"] == 390
    assert state["clock"]["day"] == 1
    assert {"type": "time_advanced", "minutes": 30, "now_minutes": 390, "day": 1} in result[
        "outcomes"
    ]


def test_time_loop_rewinds_at_boundary_preserving_knowledge(migrated_client) -> None:
    client, _ = migrated_client
    created = client.post(
        "/api/v2/worlds:compose", json=loop_world_payload("loop-world", trigger=["time"])
    )
    assert created.status_code == 201, created.text
    run_id = created.json()["run_id"]

    # Turn 1 reaches the loop boundary (360 + 30 = 390) and rewrites the anchor.
    result = _turn(
        client,
        run_id,
        "t1",
        0,
        [
            {"type": "discover", "payload": {"id": "watchmaker-secret", "text": "三座钟的齿轮"}},
            {"type": "narrate", "payload": {}},
        ],
    )
    state = result["state"]
    assert state["loop"]["count"] == 2
    assert state["clock"]["now_minutes"] == 360
    assert state["clock"]["day"] == 1
    knowledge = state["loop_memory"]["knowledge"]
    assert [item["id"] for item in knowledge] == ["watchmaker-secret"]
    assert len(state["loop_memory"]["summaries"]) == 1
    assert state["narrative_context"]["recent_turns"] == []
    rewind_outcomes = [item for item in result["outcomes"] if item["type"] == "loop_rewound"]
    assert rewind_outcomes == [
        {
            "type": "loop_rewound",
            "trigger": "time",
            "loop_count": 2,
            "notes": ["跨循环记忆保留：1 条"],
        }
    ]
    assert state["ending"] is None

    # The anchor survives the rewind so a second boundary can rewind again.
    result = _turn(client, run_id, "t2", 1, [{"type": "narrate", "payload": {}}])
    state = result["state"]
    assert state["loop"]["count"] == 3
    assert [item["id"] for item in state["loop_memory"]["knowledge"]] == ["watchmaker-secret"]
    assert len(state["loop_memory"]["summaries"]) == 2


def test_max_loops_reached_stops_rewinding(migrated_client) -> None:
    client, _ = migrated_client
    created = client.post(
        "/api/v2/worlds:compose",
        json=loop_world_payload("loop-max", trigger=["time"], max_loops=2),
    )
    assert created.status_code == 201, created.text
    run_id = created.json()["run_id"]

    _turn(client, run_id, "t1", 0, [{"type": "narrate", "payload": {}}])
    # count == max_loops: the boundary passes without another rewind.
    result = _turn(client, run_id, "t2", 1, [{"type": "narrate", "payload": {}}])
    state = result["state"]
    assert state["loop"]["count"] == 2
    assert state["clock"]["now_minutes"] == 390
    assert not [item for item in result["outcomes"] if item["type"] == "loop_rewound"]


def test_death_trigger_rewinds_bad_ending(migrated_client) -> None:
    client, _ = migrated_client
    created = client.post(
        "/api/v2/worlds:compose",
        json=loop_world_payload(
            "loop-death", trigger=["death"], max_loops=2, loop_at_minutes=None
        ),
    )
    assert created.status_code == 201, created.text
    run_id = created.json()["run_id"]

    _turn(client, run_id, "t1", 0, [{"type": "narrate", "payload": {}}])
    choice = client.post(
        f"/api/v2/runs/{run_id}/choices",
        json={
            "request_id": "t2",
            "expected_revision": 1,
            "choice_id": "give-up",
            "player_input": "我放弃了挣扎。",
        },
    )
    assert choice.status_code == 201, choice.text
    state = choice.json()["state"]
    assert state["loop"]["count"] == 2
    assert state["ending"] is None
    assert state["flags"]["gave-up"] is False
    rewind_outcomes = [item for item in choice.json()["outcomes"] if item["type"] == "loop_rewound"]
    assert [item["trigger"] for item in rewind_outcomes] == ["death"]

    recovered = client.get(f"/api/v2/runs/{run_id}")
    assert recovered.status_code == 200
    assert recovered.json()["status"] == "active"
    assert recovered.json()["state"]["loop"]["count"] == 2


def test_final_bad_ending_locks_when_loops_exhausted(migrated_client) -> None:
    client, _ = migrated_client
    created = client.post(
        "/api/v2/worlds:compose",
        json=loop_world_payload(
            "loop-final", trigger=["death"], max_loops=1, loop_at_minutes=None
        ),
    )
    assert created.status_code == 201, created.text
    run_id = created.json()["run_id"]

    choice = client.post(
        f"/api/v2/runs/{run_id}/choices",
        json={
            "request_id": "t1",
            "expected_revision": 0,
            "choice_id": "give-up",
            "player_input": "我放弃了挣扎。",
        },
    )
    assert choice.status_code == 201, choice.text
    state = choice.json()["state"]
    assert state["ending"] is not None
    assert state["ending"]["kind"] == "bad"
    assert not [item for item in choice.json()["outcomes"] if item["type"] == "loop_rewound"]

    recovered = client.get(f"/api/v2/runs/{run_id}")
    assert recovered.json()["status"] == "completed"
