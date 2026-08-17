from pathlib import Path

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from dzmm_vnext.config import Settings
from dzmm_vnext.main import create_app


def test_mobile_pairing_is_approved_once_and_revocable(migrated_client) -> None:
    client, _ = migrated_client

    capabilities = client.get("/api/v2/host/capabilities")
    assert capabilities.status_code == 200
    assert capabilities.json()["mobile"] == {
        "pairing": "pin_approval",
        "capabilities": ["gameplay"],
        "lan_gameplay_enabled": False,
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

    story_payload = client.get("/api/v2/world-templates/fog-harbor").json()
    story_payload["request_id"] = "mobile-fog-harbor"
    story_run = client.post("/api/v2/worlds:compose", json=story_payload).json()
    blocked_story_stream = client.post(
        f"/api/v2/mobile/runs/{story_run['run_id']}/turns:stream",
        headers=headers,
        json={
            "request_id": "mobile-story-raw",
            "expected_revision": 0,
            "player_input": "我直接改变剧情",
            "commands": [{"type": "set_story_flag", "payload": {"flag_id": "lan-rescued", "value": True}}],
        },
    )
    assert "choices endpoint" in blocked_story_stream.text
    story_choice = client.post(
        f"/api/v2/mobile/runs/{story_run['run_id']}/choices",
        headers=headers,
        json={
            "request_id": "mobile-story-choice",
            "expected_revision": 0,
            "player_input": "救岚",
            "choice_id": "rescue-lan",
        },
    )
    assert story_choice.status_code == 201
    assert story_choice.json()["state"]["chapter"]["id"] == "ch2"

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


def test_lan_host_only_exposes_mobile_gameplay_to_remote_clients(tmp_path, monkeypatch) -> None:
    data_dir = tmp_path / "dzmm-vnext"
    monkeypatch.setenv("DZMM_NEXT_DATA_DIR", str(data_dir))
    command.upgrade(Config(str(Path(__file__).parents[1] / "alembic.ini")), "head")
    settings = Settings(data_dir=data_dir, allow_lan_gameplay=True)

    with TestClient(create_app(settings), client=("192.168.31.20", 50000)) as remote:
        assert remote.post("/api/v2/worlds:compose", json={}).status_code == 403
        assert remote.get("/api/v2/host/pairing-requests").status_code == 403
        assert remote.post("/api/v2/model-profiles", json={}).status_code == 403
        assert remote.get("/api/v2/host/capabilities").status_code == 403
        request = remote.post(
            "/api/v2/mobile/pairing-requests", json={"device_name": "Norman's Android"}
        )
        assert request.status_code == 200
        pairing = request.json()

    with TestClient(create_app(settings)) as host:
        capabilities = host.get("/api/v2/host/capabilities")
        assert capabilities.status_code == 200
        assert capabilities.json()["mobile"]["lan_gameplay_enabled"] is True
        assert host.get("/api/v2/host/pairing-requests").status_code == 200
        assert host.post(
            f"/api/v2/host/pairing-requests/{pairing['request_id']}:approve"
        ).status_code == 200
        composed = host.post(
            "/api/v2/worlds:compose",
            json={**host.get("/api/v2/world-templates/fog-harbor").json(), "request_id": "lan-run"},
        )
        assert composed.status_code == 201
        run_id = composed.json()["run_id"]

    with TestClient(create_app(settings), client=("192.168.31.20", 50000)) as remote:
        completed = remote.post(
            f"/api/v2/mobile/pairing-requests/{pairing['request_id']}:complete",
            json={"approval_code": pairing["approval_code"]},
        )
        assert completed.status_code == 200
        headers = {"authorization": f"Bearer {completed.json()['access_token']}"}
        assert remote.get("/api/v2/mobile/session", headers=headers).status_code == 200
        assert remote.get(f"/api/v2/mobile/runs/{run_id}", headers=headers).status_code == 200
        chosen = remote.post(
            f"/api/v2/mobile/runs/{run_id}/choices",
            headers=headers,
            json={
                "request_id": "lan-choice",
                "expected_revision": 0,
                "player_input": "救岚",
                "choice_id": "rescue-lan",
            },
        )
        assert chosen.status_code == 201
        assert chosen.json()["state"]["chapter"]["id"] == "ch2"
