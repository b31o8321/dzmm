import shutil
from pathlib import Path

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from dzmm.config import Settings
from dzmm.main import create_app


def _compose_payload() -> dict[str, object]:
    return {
        "request_id": "restore-rehearsal-1",
        "world_definition": {
            "schema_version": 3,
            "name": "回滚演练世界",
            "lorebook": {"entries": []},
            "character_cards": [],
            "locations": [
                {"id": "square", "name": "中央广场"},
                {"id": "archive", "name": "旧档案馆"},
            ],
            "factions": [],
            "npcs": [],
            "events": [],
            "resources": [],
            "ruleset": {"id": "trpg", "enabled_capabilities": ["trpg"]},
            "story": {
                "chapters": [],
                "flags": [],
                "relationships": [],
                "relationship_events": [],
                "routes": [],
                "endings": [],
            },
        },
        "hero": {"name": "演练者", "profile": {}},
    }


def test_runtime_database_backup_restore_reopens_world(tmp_path: Path, monkeypatch) -> None:
    data_dir = tmp_path / "runtime-data"
    monkeypatch.setenv("DZMM_DATA_DIR", str(data_dir))
    command.upgrade(Config(str(Path(__file__).parents[1] / "alembic.ini")), "head")
    settings = Settings(data_dir=data_dir)
    database = settings.database_path

    with TestClient(create_app(settings)) as client:
        response = client.post("/api/v2/worlds:compose", json=_compose_payload())
        assert response.status_code == 201, response.text
        world_id = response.json()["world_id"]
        backup = tmp_path / "dzmm-v3.db.backup"
        shutil.copy2(database, backup)

    restored_dir = tmp_path / "restored-data"
    restored_dir.mkdir()
    restored_database = restored_dir / database.name
    shutil.copy2(backup, restored_database)
    restored_settings = Settings(data_dir=restored_dir)

    with TestClient(create_app(restored_settings)) as restored_client:
        worlds = restored_client.get("/api/v2/worlds")
        assert worlds.status_code == 200
        assert any(world["id"] == world_id for world in worlds.json())
