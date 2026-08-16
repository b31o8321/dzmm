def payload(request_id: str) -> dict:
    return {
        "request_id": request_id,
        "world_definition": {
            "schema_version": 2,
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
            "resources": [],
            "ruleset": {"id": "trpg", "enabled_capabilities": ["trpg", "resources"]},
            "story": {"chapters": [], "flags": [], "relationship_events": [], "routes": [], "endings": []},
        },
        "hero": {"name": "Mira", "profile": {}},
    }


def test_archive_manifest_purge_and_integrity_scan(migrated_client) -> None:
    client, _ = migrated_client
    created = client.post("/api/v2/worlds:compose", json=payload("lifecycle-compose")).json()
    world_id, run_id = created["world_id"], created["run_id"]
    turn = client.post(
        f"/api/v2/runs/{run_id}/turns",
        json={
            "request_id": "lifecycle-turn",
            "expected_revision": 0,
            "player_input": "I walk to the lighthouse.",
            "commands": [{"type": "move", "payload": {"location_id": "lighthouse"}}],
        },
    )
    assert turn.status_code == 201

    archived = client.post(f"/api/v2/worlds/{world_id}:archive")
    assert archived.status_code == 200
    assert archived.json()["status"] == "archived"
    assert client.post(f"/api/v2/worlds/{world_id}:archive").json()["status"] == "archived"

    blocked_turn = client.post(
        f"/api/v2/runs/{run_id}/turns",
        json={
            "request_id": "blocked-after-archive",
            "expected_revision": 1,
            "player_input": "I return.",
            "commands": [{"type": "move", "payload": {"location_id": "harbor"}}],
        },
    )
    assert blocked_turn.status_code == 409

    manifest = client.get(f"/api/v2/worlds/{world_id}/purge-manifest")
    assert manifest.status_code == 200
    assert manifest.json()["tables"] == {
        "worlds": 1,
        "world_versions": 1,
        "runs": 1,
        "turns": 1,
        "heroes": 1,
        "compose_requests": 1,
    }
    assert manifest.json()["file_paths"] == []
    assert manifest.json()["derived_indexes"] == []

    stale = client.request(
        "DELETE",
        f"/api/v2/worlds/{world_id}",
        json={"confirmation_token": "0" * 64},
    )
    assert stale.status_code == 409
    purged = client.request(
        "DELETE",
        f"/api/v2/worlds/{world_id}",
        json={"confirmation_token": manifest.json()["confirmation_token"]},
    )
    assert purged.status_code == 200
    assert client.get(f"/api/v2/runs/{run_id}").status_code == 404
    assert client.get("/api/v2/integrity").json() == {
        "clean": True,
        "orphans": {
            "world_versions_without_world": 0,
            "runs_without_world_version": 0,
            "runs_without_hero": 0,
            "turns_without_run": 0,
            "compose_requests_without_world": 0,
            "compose_requests_without_run": 0,
        },
    }
