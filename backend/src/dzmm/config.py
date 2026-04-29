from pathlib import Path

APP_DIR = Path.home() / ".dzmm"
APP_DIR.mkdir(exist_ok=True)
DEFAULT_DB_PATH = APP_DIR / "dzmm.db"
DEFAULT_DB_URL = f"sqlite+aiosqlite:///{DEFAULT_DB_PATH}"
SCHEMA_VERSION = 1
