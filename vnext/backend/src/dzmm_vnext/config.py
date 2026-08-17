from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_DATA_DIR = Path.home() / ".dzmm-vnext-v3"


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    allow_lan_gameplay: bool = False
    host: str = "127.0.0.1"
    port: int = 8765
    advertise_lan_host: bool = True

    @property
    def database_path(self) -> Path:
        return self.data_dir / "dzmm-next.db"

    @property
    def database_url(self) -> str:
        return f"sqlite+aiosqlite:///{self.database_path}"

    @property
    def sync_database_url(self) -> str:
        return f"sqlite:///{self.database_path}"

    @classmethod
    def from_env(cls) -> Settings:
        value = os.environ.get("DZMM_NEXT_DATA_DIR")
        host = os.environ.get("DZMM_NEXT_HOST", "127.0.0.1")
        port = int(os.environ.get("DZMM_NEXT_PORT", "8765"))
        return cls(
            data_dir=Path(value).expanduser() if value else DEFAULT_DATA_DIR,
            allow_lan_gameplay=os.environ.get("DZMM_NEXT_LAN_GAMEPLAY") == "1",
            host=host,
            port=port,
        )

    def ensure_layout(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
