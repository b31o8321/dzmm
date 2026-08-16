from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from dzmm_vnext.config import Settings
from dzmm_vnext.main import create_app


@pytest.fixture
def migrated_client(tmp_path, monkeypatch):
    data_dir = tmp_path / "dzmm-vnext"
    monkeypatch.setenv("DZMM_NEXT_DATA_DIR", str(data_dir))
    command.upgrade(Config(str(Path(__file__).parents[1] / "alembic.ini")), "head")
    app = create_app(Settings(data_dir=data_dir))
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client, data_dir / "dzmm-next.db"
