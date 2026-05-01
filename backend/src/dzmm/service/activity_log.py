"""Per-session activity log (v0.1.7).

Lightweight structured logger that appends one JSON event per line to
`~/.dzmm/activity.jsonl`. Complements `~/.dzmm/dzmm.log` (free-form text from
Python logging) with a machine-parseable activity stream the UI can render.

Events captured:
- ``turn_start`` / ``turn_end`` (with duration_ms, tokens_in/out, narrative
  chars, num tags, num parser errors)
- ``llm_error`` / ``parser_error`` / ``state_apply_error``
- ``screenplay_generate_start`` / ``screenplay_generate_end``
- ``ner_fallback_created`` (NPC auto-created via NER heuristic)

Used by:
- ``service/game.run_turn`` (turn timing + LLM result)
- ``service/screenplay.generate_screenplay`` (outliner timing)
- ``api/routes_sessions.activity`` (GET endpoint exposes recent events)

Format (one event per line):
  {"ts":"2026-05-01T12:34:56.789","session_id":7,"kind":"turn_end",
   "duration_ms":3421,"tokens_in":7800,"tokens_out":420,"narrative_chars":380,
   "num_tags":4}

Rotation: caps file at ~5MB; on rotation moves to ``activity.jsonl.1``.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, UTC
from pathlib import Path
from typing import Any

from dzmm.config import APP_DIR

log = logging.getLogger(__name__)

_ACTIVITY_PATH = Path(APP_DIR) / "activity.jsonl"
_MAX_BYTES = 5 * 1024 * 1024  # 5 MB before rotation


def _ensure_dir() -> None:
    try:
        _ACTIVITY_PATH.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass


def _maybe_rotate() -> None:
    try:
        if _ACTIVITY_PATH.exists() and _ACTIVITY_PATH.stat().st_size > _MAX_BYTES:
            old = _ACTIVITY_PATH.with_suffix(".jsonl.1")
            if old.exists():
                old.unlink()
            os.rename(_ACTIVITY_PATH, old)
    except OSError as e:
        log.warning("activity log rotation failed: %s", e)


def log_event(session_id: int | None, kind: str, **payload: Any) -> None:
    """Append a structured event. Best-effort — failure to write is logged
    but never raises (don't let logging break gameplay)."""
    _ensure_dir()
    _maybe_rotate()
    record = {
        "ts": datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="milliseconds"),
        "session_id": session_id,
        "kind": kind,
        **payload,
    }
    try:
        with _ACTIVITY_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as e:
        log.warning("activity log write failed: %s", e)


def read_recent(session_id: int | None = None, limit: int = 200) -> list[dict]:
    """Tail the activity file. If ``session_id`` is given, filter to that
    session. Returns most-recent-first."""
    if not _ACTIVITY_PATH.exists():
        return []
    out: list[dict] = []
    try:
        # Read whole file — small enough at 5MB to slurp; we filter / limit in
        # memory rather than keeping a per-session index.
        with _ACTIVITY_PATH.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if session_id is not None and rec.get("session_id") != session_id:
                    continue
                out.append(rec)
    except OSError as e:
        log.warning("activity log read failed: %s", e)
        return []
    out.reverse()
    return out[:limit]
