import sqlite3
from pathlib import Path

import pytest

from dzmm_vnext import sidecar


def test_sidecar_migrates_a_fresh_isolated_database(tmp_path, monkeypatch) -> None:
    data_dir = tmp_path / "sidecar-data"
    monkeypatch.setenv("DZMM_NEXT_DATA_DIR", str(data_dir))
    monkeypatch.setattr(sidecar, "distribution_root", lambda: Path(__file__).parents[1])

    sidecar.migrate()

    with sqlite3.connect(data_dir / "dzmm-next.db") as connection:
        version = connection.execute("SELECT version_num FROM alembic_version").fetchone()
        tables = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='worlds'"
        ).fetchone()
    assert version == ("0008_lorebook_content_contract",)
    assert tables == ("worlds",)


def test_sidecar_refuses_a_previous_preview_contract_without_migrating_it(tmp_path, monkeypatch) -> None:
    data_dir = tmp_path / "previous-preview"
    monkeypatch.setenv("DZMM_NEXT_DATA_DIR", str(data_dir))
    monkeypatch.setattr(sidecar, "distribution_root", lambda: Path(__file__).parents[1])
    sidecar.migrate()
    with sqlite3.connect(data_dir / "dzmm-next.db") as connection:
        connection.execute(
            "UPDATE schema_meta SET value = '2026-08-17-lorebook' WHERE key = 'contract_version'"
        )

    with pytest.raises(RuntimeError, match="will not open or migrate"):
        sidecar.migrate()


@pytest.mark.parametrize(
    ("value", "message"),
    [("not-a-port", "integer"), ("0", "between 1 and 65535"), ("65536", "between 1 and 65535")],
)
def test_sidecar_rejects_invalid_port(value, message, monkeypatch) -> None:
    monkeypatch.setenv("DZMM_NEXT_PORT", value)

    with pytest.raises(ValueError, match=message):
        sidecar.host_port()
