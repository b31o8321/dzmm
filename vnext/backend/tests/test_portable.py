import sqlite3

from test_world_compose import compose_payload


def test_world_bundle_import_allocates_new_aggregate_ids(migrated_client) -> None:
    client, _ = migrated_client
    created = client.post("/api/v2/worlds:compose", json=compose_payload("portable-source")).json()

    exported = client.get(f"/api/v2/worlds/{created['world_id']}:export")
    assert exported.status_code == 200
    bundle = exported.json()
    assert bundle["kind"] == "world"
    assert bundle["portable_policy"]["new_ids_on_import"] is True

    imported = client.post(
        "/api/v2/worlds:import",
        json={"request_id": "portable-import", "bundle": bundle},
    )
    assert imported.status_code == 201
    assert imported.json()["world_id"] != created["world_id"]
    assert imported.json()["run_id"] != created["run_id"]


def test_run_clone_copies_state_but_never_reuses_run_id(migrated_client) -> None:
    client, _ = migrated_client
    created = client.post("/api/v2/worlds:compose", json=compose_payload("clone-source")).json()
    advanced = client.post(
        f"/api/v2/runs/{created['run_id']}/turns",
        json={
            "request_id": "clone-turn",
            "expected_revision": 0,
            "player_input": "走向灯塔",
            "commands": [{"type": "move", "payload": {"location_id": "lighthouse"}}],
        },
    )
    assert advanced.status_code == 201
    exported = client.get(f"/api/v2/runs/{created['run_id']}:export")
    assert exported.status_code == 200
    bundle = exported.json()
    assert bundle["kind"] == "run"
    assert bundle["run"]["story_beats"][0]["content"]["kind"] == "opening"
    assert bundle["portable_policy"]["new_ids_on_clone"] is True

    cloned = client.post(
        "/api/v2/runs:clone",
        json={"request_id": "run-clone", "bundle": bundle},
    )
    assert cloned.status_code == 201
    result = cloned.json()
    assert result["run_id"] != created["run_id"]
    assert result["world_id"] != created["world_id"]
    assert result["state"] == advanced.json()["state"]
    snapshot = client.get(f"/api/v2/runs/{result['run_id']}").json()
    assert len(snapshot["turns"]) == 1
    assert [
        {key: value for key, value in beat.items() if key not in {"id", "sequence"}}
        for beat in snapshot["story_beats"]
    ] == [beat["content"] for beat in bundle["run"]["story_beats"]]


def test_invalid_run_bundle_is_rejected_before_any_clone_write(migrated_client) -> None:
    client, database = migrated_client
    created = client.post("/api/v2/worlds:compose", json=compose_payload("bad-clone-source")).json()
    bundle = client.get(f"/api/v2/runs/{created['run_id']}:export").json()
    bundle["run"]["turns"] = [{"id": "same", "request_id": "same", "sequence": 0}, {"id": "same", "request_id": "other", "sequence": 0}]

    response = client.post(
        "/api/v2/runs:clone",
        json={"request_id": "bad-clone", "bundle": bundle},
    )
    assert response.status_code == 422
    with database.open("rb") as handle:
        assert handle.read(16).startswith(b"SQLite format 3")
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM worlds").fetchone()[0] == 1
