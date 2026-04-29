"""File-rotating logger for dzmm.

Importing and calling setup_logging() once during app startup wires both the
stdlib root logger and uvicorn's access/error loggers to:
- a rotating file at ~/.dzmm/dzmm.log (5MB x 3)
- the existing stderr (so console output unchanged)
"""
import logging
import logging.handlers
from pathlib import Path

from dzmm.config import APP_DIR

_LOG_PATH = APP_DIR / "dzmm.log"
_INITIALIZED = False


def setup_logging(level: str = "INFO") -> None:
    global _INITIALIZED
    if _INITIALIZED:
        return
    _INITIALIZED = True

    fmt = "%(asctime)s %(levelname)-7s %(name)s :: %(message)s"
    formatter = logging.Formatter(fmt)

    file_handler = logging.handlers.RotatingFileHandler(
        _LOG_PATH, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(level.upper())
    root.addHandler(file_handler)

    # Also attach to uvicorn's named loggers so SSE / request logs land in the file.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "fastapi"):
        log = logging.getLogger(name)
        log.addHandler(file_handler)
        log.propagate = True
