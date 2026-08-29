from __future__ import annotations

import asyncio
import os
import sqlite3
import sys
from contextlib import suppress
from pathlib import Path
from typing import Protocol

import uvicorn
from alembic import command
from alembic.config import Config

from . import CONTRACT_VERSION
from .config import Settings
from .main import create_app

PARENT_CHECK_INTERVAL_SECONDS = 0.5
LEGACY_LIFECYCLE_REVISION = "0011_lifecycle_audit_events"
LIFECYCLE_REVISION = "0009_lifecycle_audit_events"


class _StoppableServer(Protocol):
    should_exit: bool


def distribution_root() -> Path:
    """Return the directory that contains Alembic files for this executable."""
    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root:
        return Path(bundle_root)
    return Path(__file__).resolve().parents[2]


def migration_config(root: Path | None = None) -> Config:
    resolved_root = root or distribution_root()
    config = Config(str(resolved_root / "alembic.ini"))
    config.set_main_option("script_location", str(resolved_root / "migrations"))
    return config


def repair_legacy_migration_revision(database_path: Path) -> None:
    """Re-anchor a preview database whose lifecycle revision was renamed later."""

    if not database_path.exists():
        return
    with sqlite3.connect(database_path) as connection:
        version_row = connection.execute(
            "SELECT version_num FROM alembic_version LIMIT 1"
        ).fetchone()
        if version_row != (LEGACY_LIFECYCLE_REVISION,):
            return
        lifecycle_table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'lifecycle_audit_events'"
        ).fetchone()
        if lifecycle_table:
            connection.execute(
                "UPDATE alembic_version SET version_num = ?",
                (LIFECYCLE_REVISION,),
            )


def migrate() -> None:
    settings = Settings.from_env()
    settings.ensure_layout()
    repair_legacy_migration_revision(settings.database_path)
    command.upgrade(migration_config(), "head")
    with sqlite3.connect(settings.database_path) as connection:
        contract_version = connection.execute(
            "SELECT value FROM schema_meta WHERE key = 'contract_version'"
        ).fetchone()
    if contract_version != (CONTRACT_VERSION,):
        raise RuntimeError(
            "this DZMM schema v3 sidecar will not open or migrate a previous preview data directory"
        )


def host_port() -> tuple[str, int]:
    host = os.environ.get("DZMM_NEXT_HOST", "127.0.0.1")
    value = os.environ.get("DZMM_NEXT_PORT", "8765")
    try:
        port = int(value)
    except ValueError as error:
        raise ValueError("DZMM_NEXT_PORT must be an integer") from error
    if not 1 <= port <= 65535:
        raise ValueError("DZMM_NEXT_PORT must be between 1 and 65535")
    return host, port


def parent_pid() -> int | None:
    value = os.environ.get("DZMM_NEXT_PARENT_PID")
    if value is None:
        return None
    try:
        pid = int(value)
    except ValueError as error:
        raise ValueError("DZMM_NEXT_PARENT_PID must be an integer") from error
    if pid <= 0:
        raise ValueError("DZMM_NEXT_PARENT_PID must be positive")
    return pid


async def watch_parent(
    server: _StoppableServer,
    expected_parent_pid: int,
    *,
    interval_seconds: float = PARENT_CHECK_INTERVAL_SECONDS,
) -> None:
    """Stop the Local Host after its desktop owner exits unexpectedly."""

    while not server.should_exit:
        if os.getppid() != expected_parent_pid:
            server.should_exit = True
            return
        await asyncio.sleep(interval_seconds)


async def serve() -> None:
    host, port = host_port()
    server = uvicorn.Server(uvicorn.Config(create_app(), host=host, port=port, log_level="info"))
    expected_parent_pid = parent_pid()
    watcher = (
        asyncio.create_task(watch_parent(server, expected_parent_pid))
        if expected_parent_pid is not None
        else None
    )
    try:
        await server.serve()
    finally:
        if watcher is not None:
            watcher.cancel()
            with suppress(asyncio.CancelledError):
                await watcher


def main() -> None:
    migrate()
    asyncio.run(serve())
