import sqlite3
from pathlib import Path
from uuid import uuid4


def compose_payload(request_id: str) -> dict:
    return {
        "request_id": request_id,
        "world_definition": {
            "schema_version": 1,
            "name": "Fog Harbor",
            "lore": [],
            "locations": [
                {"id": "harbor", "name": "Fog Harbor"},
                {"id": "lighthouse", "name": "Old Lighthouse"},
            ],
            "factions": [],
            "npcs": [],
            "events": [],
            "ruleset": {"id": "core"},
        },
        "hero": {"name": "Mira", "profile": {"origin": "sailor"}},
    }


def table_counts(database: Path) -> dict[str, int]:
    names = ["worlds", "world_versions", "heroes", "runs", "compose_requests"]
    with sqlite3.connect(database) as connection:
        return {name: connection.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0] for name in names}


def test_compose_is_atomic_idempotent_and_recovers_run(migrated_client) -> None:
    client, database = migrated_client
    payload = compose_payload("compose-1")

    first = client.post("/api/v2/worlds:compose", json=payload)
    assert first.status_code == 201
    created = first.json()
    assert created["state"] == {
        "schema_version": 1,
        "revision": 0,
        "hero": {
            "id": created["hero_id"],
            "name": "Mira",
            "profile": {"origin": "sailor"},
        },
        "location_id": "harbor",
        "inventory": [],
        "entities": {},
        "events": {},
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
    assert {key: retry.json()[key] for key in ("world_id", "world_version_id", "hero_id", "run_id")} == {
        key: created[key] for key in ("world_id", "world_version_id", "hero_id", "run_id")
    }
    assert table_counts(database)["runs"] == 1

    recovered = client.get(f"/api/v2/runs/{created['run_id']}")
    assert recovered.status_code == 200
    assert recovered.json()["state"] == created["state"]
    assert recovered.json()["turns"] == []


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
