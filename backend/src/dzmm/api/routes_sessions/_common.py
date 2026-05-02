"""Shared helpers + DI placeholders for the routes_sessions sub-modules.

main.py overrides `get_session_dep` / `get_session_maker_dep` at startup;
each sub-router imports them from here so they all share the same key.

`build_client` is re-exported here as well: tests monkeypatch
`dzmm.api.routes_sessions.build_client`, and the package __init__ mirrors
those writes down into every sub-module that captures it (currently only
`turn`). Keeping the canonical reference here avoids each sub-module
needing to import from `factory` directly."""
import json

from dzmm.db.models import NPC
from dzmm.models.factory import build_client  # noqa: F401 — re-exported

__all__ = [
    "get_session_dep",
    "get_session_maker_dep",
    "build_client",
    "_to_out",
    "_parse_events_json",
    "_npc_to_dict",
]


def get_session_dep():
    raise RuntimeError("override")


def get_session_maker_dep():
    raise RuntimeError("override")


def _to_out(s):
    from dzmm.api.schemas import SessionOut
    return SessionOut(
        id=s.id, name=s.name,
        screenplay_id=s.screenplay_id,
        world_id=s.world_id, character_id=s.character_id,
        gm_model_config_id=s.gm_model_config_id,
        summarizer_model_config_id=s.summarizer_model_config_id,
        turn_count=s.turn_count,
    )


def _parse_events_json(raw: str | None) -> list[dict]:
    """Best-effort decode of Message.events_json to a list of event dicts.
    Empty/null/malformed values yield []."""
    if not raw:
        return []
    try:
        decoded = json.loads(raw)
    except (TypeError, ValueError):
        return []
    if not isinstance(decoded, list):
        return []
    return [e for e in decoded if isinstance(e, dict)]


def _npc_to_dict(n: NPC) -> dict:
    try:
        affinity = json.loads(n.affinity_json or "{}")
        if not isinstance(affinity, dict):
            affinity = {}
    except (TypeError, ValueError):
        affinity = {}
    try:
        notes = json.loads(n.notes_json or "[]")
        if not isinstance(notes, list):
            notes = []
    except (TypeError, ValueError):
        notes = []
    try:
        emotion = json.loads(n.emotion_json or "{}")
        if not isinstance(emotion, dict):
            emotion = {}
    except (TypeError, ValueError):
        emotion = {}
    # v0.11: progressive reveal map — frontend masks fields not in this dict.
    try:
        revealed = json.loads(n.revealed_json or '{"name": true}')
        if not isinstance(revealed, dict):
            revealed = {"name": True}
    except (TypeError, ValueError):
        revealed = {"name": True}
    revealed["name"] = True  # always

    # v0.2.5: Python-driven threshold reveals (merge on top of LLM-driven stored reveals).
    # Once an NPC has appeared in the story, basic observable fields are auto-revealed.
    # This replaces the unreliable LLM reveal=attribute mechanism for common fields.
    if n.last_seen_turn > 0:
        revealed.setdefault("description", True)
        revealed.setdefault("state", True)
        revealed.setdefault("favor", True)
    # Archetype becomes apparent after meaningful interaction
    if abs(n.favor) >= 20 or (n.last_seen_turn > 0 and (n.archetype or "").strip()):
        revealed.setdefault("archetype", True)
    # Purpose revealed after significant relationship
    if abs(n.favor) >= 30:
        revealed.setdefault("purpose", True)

    return {
        "id": n.id,
        "name": n.name,
        "description": n.description,
        "favor": n.favor,
        "state": n.state,
        "last_seen_turn": n.last_seen_turn,
        "purpose": n.purpose,
        "archetype": n.archetype,
        "affinity": affinity,
        "emotion": emotion,
        "pinned": bool(n.pinned),
        "notes": notes,
        "revealed": revealed,
        "current_location": n.current_location,
        "tts_voice": n.tts_voice or "",
    }
