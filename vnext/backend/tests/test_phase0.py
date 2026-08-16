import sqlite3
import sys
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from jsonschema import ValidationError

from dzmm_vnext.config import Settings
from dzmm_vnext.contracts import contract_manifest, contract_validator, contracts_dir
from dzmm_vnext.main import create_app


def test_contract_manifest_contains_every_vnext_contract() -> None:
    manifest = contract_manifest()
    assert manifest["version"] == "2026-08-17"
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
    app = create_app(Settings(data_dir=tmp_path / "dzmm-vnext-test"))
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "app": "dzmm-next",
        "api_version": 2,
        "contract": contract_manifest(),
        "storage": "isolated",
        "foreign_keys": True,
    }


def test_local_desktop_origins_can_call_api_but_unrelated_origins_cannot(migrated_client) -> None:
    client, _ = migrated_client
    allowed = client.options(
        "/api/v2/world-templates/fog-harbor",
        headers={
            "origin": "http://127.0.0.1:5175",
            "access-control-request-method": "GET",
        },
    )
    denied = client.options(
        "/api/v2/world-templates/fog-harbor",
        headers={
            "origin": "https://untrusted.example",
            "access-control-request-method": "GET",
        },
    )

    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == "http://127.0.0.1:5175"
    assert denied.status_code == 400


def test_contract_validators_reject_incomplete_payloads() -> None:
    world = {
        "schema_version": 2,
        "name": "Fog Harbor",
        "lore": [],
        "character_cards": [],
        "locations": [],
        "factions": [],
        "npcs": [],
        "events": [],
        "resources": [],
        "ruleset": {"id": "trpg", "enabled_capabilities": ["trpg", "resources"]},
        "story": {"chapters": [], "flags": [], "relationship_events": [], "routes": [], "endings": []},
    }
    contract_validator("world_definition.schema.json").validate(world)

    with pytest.raises(ValidationError):
        contract_validator("run_state.schema.json").validate({"schema_version": 2})


def test_fresh_database_migration_records_vnext_baseline(tmp_path, monkeypatch) -> None:
    data_dir = tmp_path / "dzmm-vnext-migration"
    monkeypatch.setenv("DZMM_NEXT_DATA_DIR", str(data_dir))
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))

    command.upgrade(config, "head")

    with sqlite3.connect(data_dir / "dzmm-next.db") as connection:
        rows = connection.execute("SELECT key, value FROM schema_meta ORDER BY key").fetchall()
    assert rows == [
        ("api_version", "2"),
        ("app", "dzmm-next"),
        ("contract_version", "2026-08-17"),
    ]
