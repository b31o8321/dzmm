import asyncio
import sqlite3
from pathlib import Path
from uuid import uuid4

from dzmm.turns import TurnCoordinator, TurnInput


def compose_payload(request_id: str) -> dict:
    return {
        "request_id": request_id,
        "world_definition": {
            "schema_version": 3,
            "name": "Fog Harbor",
            "lorebook": {"entries": []},
            "character_cards": [],
            "locations": [
                {"id": "harbor", "name": "Fog Harbor"},
                {"id": "lighthouse", "name": "Old Lighthouse"},
            ],
            "factions": [],
            "npcs": [],
            "events": [],
            "resources": [{"id": "lantern", "name": "Lantern"}],
            "ruleset": {"id": "trpg", "enabled_capabilities": ["trpg", "resources"]},
            "story": {
                "chapters": [],
                "flags": [],
                "relationships": [],
                "relationship_events": [],
                "routes": [],
                "endings": [],
            },
        },
        "hero": {"name": "Mira", "profile": {"origin": "sailor"}},
    }


def table_counts(database: Path) -> dict[str, int]:
    names = ["worlds", "world_versions", "heroes", "runs", "compose_requests"]
    with sqlite3.connect(database) as connection:
        return {
            name: connection.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0] for name in names
        }


def test_compose_is_atomic_idempotent_and_recovers_run(migrated_client) -> None:
    client, database = migrated_client
    payload = compose_payload("compose-1")

    first = client.post("/api/v2/worlds:compose", json=payload)
    assert first.status_code == 201
    created = first.json()
    assert created["state"] == {
        "schema_version": 3,
        "revision": 0,
        "hero": {
            "id": created["hero_id"],
            "name": "Mira",
            "profile": {"origin": "sailor"},
        },
        "ruleset": {"id": "trpg", "enabled_capabilities": ["trpg", "resources"]},
        "location_id": "harbor",
        "inventory": [],
        "entities": {},
        "events": {},
        "combat": {"participants": {}},
        "location_state": {
            "harbor": {
                "known": True,
                "visited_turns": [0],
                "last_visited_turn": 0,
                "scene_state": {},
            },
            "lighthouse": {
                "known": False,
                "visited_turns": [],
                "last_visited_turn": None,
                "scene_state": {},
            },
        },
        "npc_state": {},
        "faction_state": {},
        "campaign_state": None,
        "active_events": [],
        "plot_threads": [],
        "pending_interactions": [],
        "chapter": None,
        "route": None,
        "flags": {},
        "relationships": {},
        "ending": None,
    }
    assert table_counts(database) == {
        "worlds": 1,
        "world_versions": 1,
        "heroes": 1,
        "runs": 1,
        "compose_requests": 1,
    }

    retry = client.post("/api/v2/worlds:compose", json=payload)
    assert retry.status_code == 200
    assert {
        key: retry.json()[key] for key in ("world_id", "world_version_id", "hero_id", "run_id")
    } == {key: created[key] for key in ("world_id", "world_version_id", "hero_id", "run_id")}
    assert table_counts(database)["runs"] == 1

    recovered = client.get(f"/api/v2/runs/{created['run_id']}")
    assert recovered.status_code == 200
    assert recovered.json()["state"] == created["state"]
    assert recovered.json()["turns"] == []
    assert recovered.json()["story_beats"][0]["kind"] == "opening"


def test_existing_world_can_start_idempotent_new_run_with_persisted_opening(
    migrated_client,
) -> None:
    client, _ = migrated_client
    created = client.post(
        "/api/v2/worlds:compose", json=compose_payload("compose-for-new-run")
    ).json()
    payload = {
        "request_id": "start-second-run",
        "world_version_id": created["world_version_id"],
        "hero": {"name": "Nora", "profile": {"origin": "surveyor"}},
    }

    first = client.post(f"/api/v2/worlds/{created['world_id']}/runs", json=payload)
    replay = client.post(f"/api/v2/worlds/{created['world_id']}/runs", json=payload)

    assert first.status_code == 201
    assert replay.status_code == 200
    assert replay.json()["run_id"] == first.json()["run_id"]
    assert first.json()["run_id"] != created["run_id"]
    assert "Nora" in first.json()["opening"]["narrative"]
    snapshot = client.get(f"/api/v2/runs/{first.json()['run_id']}").json()
    assert snapshot["state"]["revision"] == 0
    assert snapshot["turns"] == []
    assert snapshot["story_beats"][0]["sequence"] == 0
    assert {
        key: value
        for key, value in snapshot["story_beats"][0].items()
        if key not in {"id", "sequence"}
    } == first.json()["opening"]


def test_new_run_rejects_archived_world_without_partial_write(migrated_client) -> None:
    client, database = migrated_client
    created = client.post(
        "/api/v2/worlds:compose", json=compose_payload("compose-before-archive")
    ).json()
    client.post(f"/api/v2/worlds/{created['world_id']}:archive")

    response = client.post(
        f"/api/v2/worlds/{created['world_id']}/runs",
        json={
            "request_id": "blocked-new-run",
            "hero": {"name": "Never Created", "profile": {}},
        },
    )

    assert response.status_code == 422
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM run_create_requests").fetchone()[0] == 0


def test_compose_rejects_reused_request_id_with_different_input(migrated_client) -> None:
    client, database = migrated_client
    payload = compose_payload("compose-conflict")
    assert client.post("/api/v2/worlds:compose", json=payload).status_code == 201

    conflicting = compose_payload("compose-conflict")
    conflicting["hero"]["name"] = "Not Mira"
    response = client.post("/api/v2/worlds:compose", json=conflicting)

    assert response.status_code == 409
    assert table_counts(database)["runs"] == 1


def test_compose_rejects_unknown_model_profile(migrated_client) -> None:
    client, database = migrated_client
    payload = compose_payload("missing-model-profile")
    payload["model_profile_id"] = "missing"

    response = client.post("/api/v2/worlds:compose", json=payload)

    assert response.status_code == 422
    assert table_counts(database)["runs"] == 0


def test_twenty_database_failures_leave_no_partial_aggregate(migrated_client) -> None:
    client, database = migrated_client
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TRIGGER fail_hero BEFORE INSERT ON heroes "
            "BEGIN SELECT RAISE(ABORT, 'injected failure'); END;"
        )

    for _ in range(20):
        response = client.post("/api/v2/worlds:compose", json=compose_payload(str(uuid4())))
        assert response.status_code == 500

    assert table_counts(database) == {
        "worlds": 0,
        "world_versions": 0,
        "heroes": 0,
        "runs": 0,
        "compose_requests": 0,
    }


def test_three_turns_recover_after_refresh_and_sse_replays_events(migrated_client) -> None:
    client, _ = migrated_client
    created = client.post("/api/v2/worlds:compose", json=compose_payload("turn-world")).json()
    run_id = created["run_id"]
    first = client.post(
        f"/api/v2/runs/{run_id}/turns",
        json={
            "request_id": "turn-1",
            "expected_revision": 0,
            "player_input": "I walk to the lighthouse.",
            "commands": [{"type": "move", "payload": {"location_id": "lighthouse"}}],
        },
    )
    assert first.status_code == 201
    assert first.json()["after_revision"] == 1
    assert first.json()["state"]["location_id"] == "lighthouse"

    second = client.post(
        f"/api/v2/runs/{run_id}/turns",
        json={
            "request_id": "turn-2",
            "expected_revision": 1,
            "player_input": "I take a lantern.",
            "commands": [
                {"type": "inventory_change", "payload": {"item_id": "lantern", "delta": 1}}
            ],
        },
    )
    assert second.status_code == 201
    stream = client.post(
        f"/api/v2/runs/{run_id}/turns:stream",
        json={
            "request_id": "turn-3",
            "expected_revision": 2,
            "player_input": "I search the light room.",
            "commands": [
                {"type": "roll_dice", "payload": {"sides": 20}},
                {"type": "narrate", "payload": {}},
            ],
        },
    )
    assert stream.status_code == 200
    assert stream.headers["content-type"].startswith("text/event-stream")
    assert "event: turn_started" in stream.text
    assert "event: narrative_delta" in stream.text
    assert "event: command_applied" in stream.text
    assert "event: turn_completed" in stream.text

    recovered = client.get(f"/api/v2/runs/{run_id}")
    assert recovered.status_code == 200
    assert recovered.json()["state"]["revision"] == 3
    assert recovered.json()["state"]["location_id"] == "lighthouse"
    assert recovered.json()["state"]["inventory"] == [{"id": "lantern", "quantity": 1}]
    assert [turn["sequence"] for turn in recovered.json()["turns"]] == [1, 2, 3]

    retry = client.post(
        f"/api/v2/runs/{run_id}/turns",
        json={
            "request_id": "turn-1",
            "expected_revision": 0,
            "player_input": "I walk to the lighthouse.",
            "commands": [{"type": "move", "payload": {"location_id": "lighthouse"}}],
        },
    )
    assert retry.status_code == 200
    assert retry.json()["state"]["revision"] == 1


def test_rollback_creates_a_new_audit_turn_without_rewriting_history(migrated_client) -> None:
    client, _ = migrated_client
    created = client.post("/api/v2/worlds:compose", json=compose_payload("rollback-world")).json()
    run_id = created["run_id"]
    first = client.post(
        f"/api/v2/runs/{run_id}/turns",
        json={
            "request_id": "rollback-turn-1",
            "expected_revision": 0,
            "player_input": "I walk to the lighthouse.",
            "commands": [{"type": "move", "payload": {"location_id": "lighthouse"}}],
        },
    ).json()
    assert first["kind"] == "turn"
    second = client.post(
        f"/api/v2/runs/{run_id}/turns",
        json={
            "request_id": "rollback-turn-2",
            "expected_revision": 1,
            "player_input": "I take a lantern.",
            "commands": [
                {"type": "inventory_change", "payload": {"item_id": "lantern", "delta": 1}}
            ],
        },
    )
    assert second.status_code == 201

    rollback_payload = {
        "request_id": "rollback-1",
        "expected_revision": 2,
        "target_turn_id": first["turn_id"],
    }
    rollback = client.post(f"/api/v2/runs/{run_id}/rollbacks", json=rollback_payload)
    assert rollback.status_code == 201
    assert rollback.json()["kind"] == "rollback"
    assert rollback.json()["rollback_target_id"] == first["turn_id"]
    assert rollback.json()["state"]["revision"] == 3
    assert rollback.json()["state"]["location_id"] == "lighthouse"
    assert rollback.json()["state"]["inventory"] == []

    retry = client.post(f"/api/v2/runs/{run_id}/rollbacks", json=rollback_payload)
    assert retry.status_code == 200
    assert retry.json()["turn_id"] == rollback.json()["turn_id"]

    recovered = client.get(f"/api/v2/runs/{run_id}").json()
    assert recovered["state"] == rollback.json()["state"]
    assert [(turn["sequence"], turn["kind"]) for turn in recovered["turns"]] == [
        (1, "turn"),
        (2, "turn"),
        (3, "rollback"),
    ]
    assert recovered["turns"][1]["outcomes"] == [
        {"type": "inventory_change", "item_id": "lantern", "delta": 1}
    ]


def test_stream_failure_or_client_cancellation_does_not_commit_a_turn(migrated_client) -> None:
    client, _ = migrated_client
    profile = client.post(
        "/api/v2/model-profiles",
        json={
            "name": "stream test profile",
            "provider_type": "lm_studio",
            "base_url": "http://desktop.local:1234/v1",
            "model_name": "stream-test",
        },
    ).json()
    payload = compose_payload("stream-atomic-world")
    payload["model_profile_id"] = profile["id"]
    run_id = client.post("/api/v2/worlds:compose", json=payload).json()["run_id"]

    class EmptyNarrator:
        async def stream(self, *_args):
            if False:
                yield ""

    class SlowNarrator:
        async def stream(self, *_args):
            yield "灯塔"
            await asyncio.Future()

    class BufferedNarrator:
        async def stream(self, *_args):
            yield "### 场景\n\n灯塔亮起。"

    async def collect(coordinator, request_id: str):
        payload = TurnInput(
            request_id=request_id,
            expected_revision=0,
            player_input="I inspect the lighthouse.",
            commands=[{"type": "narrate", "payload": {}}],
        )
        return [event async for event in coordinator.stream(run_id, payload)]

    empty = TurnCoordinator(client.app.state.sessions, narrator=EmptyNarrator())
    events = asyncio.run(collect(empty, "stream-empty"))
    assert events[-1] == (
        "turn_failed",
        {"category": "model", "detail": "model returned no valid narrative content"},
    )
    assert client.get(f"/api/v2/runs/{run_id}").json()["state"]["revision"] == 0
    assert client.get(f"/api/v2/runs/{run_id}").json()["turns"] == []

    async def cancel() -> None:
        coordinator = TurnCoordinator(client.app.state.sessions, narrator=SlowNarrator())
        payload = TurnInput(
            request_id="stream-cancel",
            expected_revision=0,
            player_input="I inspect the lighthouse.",
            commands=[{"type": "narrate", "payload": {}}],
        )
        events = coordinator.stream(run_id, payload)
        assert (await anext(events))[0] == "turn_started"
        assert await anext(events) == ("narrative_delta", {"text": "灯塔"})
        await events.aclose()

    asyncio.run(cancel())
    assert client.get(f"/api/v2/runs/{run_id}").json()["state"]["revision"] == 0
    assert client.get(f"/api/v2/runs/{run_id}").json()["turns"] == []

    buffered = TurnCoordinator(client.app.state.sessions, narrator=BufferedNarrator())
    buffered_events = asyncio.run(collect(buffered, "stream-buffered"))
    assert ("narrative_delta", {"text": "场景\n\n灯塔亮起。"}) in buffered_events
    assert buffered_events[-1][0] == "turn_completed"
