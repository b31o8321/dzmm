import json
import sqlite3
import sys
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from jsonschema import ValidationError

from dzmm.config import Settings
from dzmm.contracts import contract_manifest, contract_validator, contracts_dir
from dzmm.main import create_app


def test_contract_manifest_contains_every_vnext_contract() -> None:
    manifest = contract_manifest()
    assert manifest["version"] == "2026-08-17-content-boundary"
    assert manifest["contracts"] == [
        "event_envelope.schema.json",
        "run_state.schema.json",
        "turn_command.schema.json",
        "world_definition.schema.json",
    ]


def test_contracts_use_the_sidecar_bundle_root(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)

    assert contracts_dir() == tmp_path / "contracts"


def test_health_uses_isolated_fresh_data_directory(tmp_path) -> None:
    app = create_app(Settings(data_dir=tmp_path / "dzmm-test"))
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "app": "dzmm",
        "api_version": 2,
        "contract": contract_manifest(),
        "storage": "local",
        "host": "127.0.0.1",
        "foreign_keys": True,
    }


def test_runtime_route_surface_has_no_retired_remote_or_pairing_api(tmp_path) -> None:
    app = create_app(Settings(data_dir=tmp_path / "route-surface"))
    paths = {route.path for route in app.routes}
    assert "/health" in paths
    assert "/api/v2/worlds:compose" in paths
    assert all(
        not any(token in path.lower() for token in ("remote", "pairing", "discovery", "mobile"))
        for path in paths
    )


def test_diagnostics_exports_only_aggregate_support_data(migrated_client) -> None:
    client, _ = migrated_client
    response = client.get("/api/v2/diagnostics")

    assert response.status_code == 200
    payload = response.json()
    assert payload["app"] == "dzmm"
    assert payload["storage"] == "local"
    assert payload["database"] == {
        "aggregate_counts": {
            "worlds": 0,
            "world_versions": 0,
            "heroes": 0,
            "runs": 0,
            "turns": 0,
            "story_beats": 0,
            "model_profiles": 0,
        },
        "integrity": {
            "clean": True,
            "orphans": {
                "world_versions_without_world": 0,
                "runs_without_world_version": 0,
                "runs_without_hero": 0,
                "turns_without_run": 0,
                "story_beats_without_run": 0,
                "compose_requests_without_world": 0,
                "compose_requests_without_run": 0,
                "run_create_requests_without_world": 0,
                "run_create_requests_without_run": 0,
            },
        },
    }
    serialized = json.dumps(payload)
    for forbidden in ("data_dir", "base_url", "token_hash", "narrative", "player_input"):
        assert forbidden not in serialized


def test_local_desktop_origins_can_call_api_but_unrelated_origins_cannot(migrated_client) -> None:
    client, _ = migrated_client
    for origin in (
        "http://127.0.0.1:5175",
        "https://tauri.localhost",
        "http://tauri.localhost",
        "tauri://localhost",
    ):
        allowed = client.options(
            "/api/v2/world-templates/fog-harbor",
            headers={
                "origin": origin,
                "access-control-request-method": "GET",
            },
        )
        assert allowed.status_code == 200
        assert allowed.headers["access-control-allow-origin"] == origin
    denied = client.options(
        "/api/v2/world-templates/fog-harbor",
        headers={
            "origin": "https://untrusted.example",
            "access-control-request-method": "GET",
        },
    )
    assert denied.status_code == 400


def test_model_profile_http_crud_default_and_run_reference_guard(migrated_client) -> None:
    client, _ = migrated_client
    payload = {
        "name": "Ollama",
        "provider_type": "ollama",
        "base_url": "http://127.0.0.1:11434/",
        "model_name": "qwen:7b",
    }
    first = client.post("/api/v2/model-profiles", json=payload).json()
    second = client.post(
        "/api/v2/model-profiles",
        json={
            **payload,
            "name": "Studio",
            "provider_type": "lm_studio",
            "base_url": "http://127.0.0.1:1234/v1",
        },
    ).json()
    assert first["is_default"] is True
    assert second["is_default"] is False

    edited = client.put(
        f"/api/v2/model-profiles/{second['id']}",
        json={
            **payload,
            "name": "Studio 14B",
            "provider_type": "lm_studio",
            "base_url": "http://127.0.0.1:1234/v1",
        },
    )
    assert edited.status_code == 200
    assert edited.json()["name"] == "Studio 14B"
    selected = client.post(f"/api/v2/model-profiles/{second['id']}:default")
    assert selected.status_code == 200
    assert selected.json()["is_default"] is True
    assert client.delete(f"/api/v2/model-profiles/{first['id']}").status_code == 204


def test_contract_validators_reject_incomplete_payloads() -> None:
    world = {
        "schema_version": 3,
        "name": "Fog Harbor",
        "lorebook": {"entries": []},
        "character_cards": [],
        "locations": [],
        "factions": [],
        "npcs": [],
        "events": [],
        "resources": [],
        "ruleset": {"id": "trpg", "enabled_capabilities": ["trpg", "resources"]},
        "story": {
            "chapters": [],
            "flags": [],
            "relationships": [],
            "relationship_events": [],
            "routes": [],
            "endings": [],
        },
    }
    contract_validator("world_definition.schema.json").validate(world)

    legacy_world = {key: value for key, value in world.items() if key != "lorebook"}
    legacy_world["lore"] = []
    with pytest.raises(ValidationError):
        contract_validator("world_definition.schema.json").validate(legacy_world)

    with pytest.raises(ValidationError):
        contract_validator("run_state.schema.json").validate({"schema_version": 3})


def test_fresh_database_migration_records_vnext_baseline(tmp_path, monkeypatch) -> None:
    data_dir = tmp_path / "dzmm-migration"
    monkeypatch.setenv("DZMM_DATA_DIR", str(data_dir))
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))

    command.upgrade(config, "head")

    with sqlite3.connect(data_dir / "dzmm-v3.db") as connection:
        rows = connection.execute("SELECT key, value FROM schema_meta ORDER BY key").fetchall()
    assert rows == [
        ("api_version", "2"),
        ("app", "dzmm"),
        ("contract_version", "2026-08-17-content-boundary"),
    ]
