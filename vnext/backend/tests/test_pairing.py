def test_mobile_pairing_is_approved_once_and_revocable(migrated_client) -> None:
    client, _ = migrated_client

    capabilities = client.get("/api/v2/host/capabilities")
    assert capabilities.status_code == 200
    assert capabilities.json()["mobile"] == {
        "pairing": "pin_approval",
        "capabilities": ["gameplay"],
    }

    created = client.post(
        "/api/v2/mobile/pairing-requests", json={"device_name": "Norman's Android"}
    )
    assert created.status_code == 200
    request = created.json()
    assert set(request) == {"request_id", "device_id", "approval_code", "expires_at"}

    pending = client.get("/api/v2/host/pairing-requests")
    assert pending.status_code == 200
    assert pending.json() == [
        {
            "request_id": request["request_id"],
            "device_id": request["device_id"],
            "device_name": "Norman's Android",
            "expires_at": request["expires_at"],
        }
    ]

    assert (
        client.post(f"/api/v2/host/pairing-requests/{request['request_id']}:approve").json()
        == {"request_id": request["request_id"], "status": "approved"}
    )
    completed = client.post(
        f"/api/v2/mobile/pairing-requests/{request['request_id']}:complete",
        json={"approval_code": request["approval_code"]},
    )
    assert completed.status_code == 200
    credential = completed.json()
    assert credential["device_id"] == request["device_id"]
    assert credential["capabilities"] == ["gameplay"]
    assert "access_token" in credential

    session = client.get(
        "/api/v2/mobile/session", headers={"authorization": f"Bearer {credential['access_token']}"}
    )
    assert session.status_code == 200
    assert session.json() == {
        "id": request["device_id"],
        "name": "Norman's Android",
        "status": "active",
        "capabilities": ["gameplay"],
    }

    composed = client.post(
        "/api/v2/worlds:compose",
        json={
            "request_id": "mobile-playable-run",
            "world_definition": {
                "schema_version": 2,
                "name": "Mobile Run",
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
        },
    ).json()
    headers = {"authorization": f"Bearer {credential['access_token']}"}
    assert client.get(f"/api/v2/mobile/runs/{composed['run_id']}", headers=headers).status_code == 200
    stream = client.post(
        f"/api/v2/mobile/runs/{composed['run_id']}/turns:stream",
        headers=headers,
        json={
            "request_id": "mobile-turn-1",
            "expected_revision": 0,
            "player_input": "I go to the lighthouse.",
            "commands": [{"type": "move", "payload": {"location_id": "lighthouse"}}],
        },
    )
    assert stream.status_code == 200
    assert "event: turn_completed" in stream.text

    revoked = client.post(f"/api/v2/host/mobile-devices/{request['device_id']}:revoke")
    assert revoked.status_code == 200
    assert client.get(
        "/api/v2/mobile/session", headers={"authorization": f"Bearer {credential['access_token']}"}
    ).status_code == 401
    assert client.get(f"/api/v2/mobile/runs/{composed['run_id']}", headers=headers).status_code == 401
    assert client.post(
        f"/api/v2/mobile/pairing-requests/{request['request_id']}:complete",
        json={"approval_code": request["approval_code"]},
    ).status_code == 409


def test_mobile_pairing_rejects_missing_or_wrong_bearer_token(migrated_client) -> None:
    client, _ = migrated_client

    assert client.get("/api/v2/mobile/session").status_code == 401
    assert client.get(
        "/api/v2/mobile/session", headers={"authorization": "Bearer incorrect"}
    ).status_code == 401
