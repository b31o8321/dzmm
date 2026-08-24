import asyncio
import sqlite3
from pathlib import Path

import pytest

from dzmm_vnext import sidecar


class _FakeServer:
    should_exit = False


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
    assert version == ("0012_model_credentials",)
    assert tables == ("worlds",)


def test_sidecar_refuses_a_previous_preview_contract_without_migrating_it(
    tmp_path, monkeypatch
) -> None:
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


def test_sidecar_stops_when_its_desktop_parent_disappears(monkeypatch) -> None:
    parent_ids = iter([8123, 1])
    monkeypatch.setattr(sidecar.os, "getppid", lambda: next(parent_ids))
    server = _FakeServer()

    asyncio.run(sidecar.watch_parent(server, 8123, interval_seconds=0))

    assert server.should_exit is True


@pytest.mark.parametrize(
    ("value", "message"),
    [("not-a-pid", "integer"), ("0", "positive"), ("-1", "positive")],
)
def test_sidecar_rejects_invalid_parent_pid(value, message, monkeypatch) -> None:
    monkeypatch.setenv("DZMM_NEXT_PARENT_PID", value)

    with pytest.raises(ValueError, match=message):
        sidecar.parent_pid()
