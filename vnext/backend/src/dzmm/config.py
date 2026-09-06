from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_DATA_DIR = Path.home() / ".dzmm"


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    port: int = 8765

    @property
    def database_path(self) -> Path:
        return self.data_dir / "dzmm-v3.db"

    @property
    def database_url(self) -> str:
        return f"sqlite+aiosqlite:///{self.database_path}"

    @property
    def sync_database_url(self) -> str:
        return f"sqlite:///{self.database_path}"

    @classmethod
    def from_env(cls) -> Settings:
        value = os.environ.get("DZMM_DATA_DIR")
        port = int(os.environ.get("DZMM_PORT", "8765"))
        return cls(
            data_dir=Path(value).expanduser() if value else DEFAULT_DATA_DIR,
            port=port,
        )

    def ensure_layout(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
