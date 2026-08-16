from __future__ import annotations

import os
import sys
from pathlib import Path

import uvicorn
from alembic import command
from alembic.config import Config

from .config import Settings
from .main import create_app


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


def migrate() -> None:
    Settings.from_env().ensure_layout()
    command.upgrade(migration_config(), "head")


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


def main() -> None:
    migrate()
    host, port = host_port()
    uvicorn.run(create_app(), host=host, port=port, log_level="info")
