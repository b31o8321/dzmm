from __future__ import annotations

from pathlib import Path
from uuid import uuid4


def load_host_id(data_dir: Path) -> str:
    """Create one stable, non-secret identity per isolated vNext Host."""
    path = data_dir / "host-id"
    if path.exists():
        value = path.read_text(encoding="utf-8").strip()
        if value:
            return value
    value = str(uuid4())
    path.write_text(f"{value}\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:  # Windows ACLs are managed by the user profile.
        pass
    return value
