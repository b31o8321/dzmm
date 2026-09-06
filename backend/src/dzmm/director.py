"""Director long-line pacing (ADR-012).

Every DIRECTOR_INTERVAL committed turns, a background call asks the run's model
for a strict-JSON pacing note (`tension`/`hook`).  The note is stored out of
band and injected into later GM requests as advisory context only; any failure
degrades silently to the deterministic per-turn variation.
"""

from __future__ import annotations

import json
from typing import Any

DIRECTOR_INTERVAL = 6
DIRECTOR_FRESHNESS_TURNS = DIRECTOR_INTERVAL * 2
_NOTE_MAX_CHARS = 120
_NOTE_KEYS = ("tension", "hook")


def should_run_director(revision: int, interval: int = DIRECTOR_INTERVAL) -> bool:
    """Director runs after every Nth committed turn (never on the opening)."""

    return revision > 0 and revision % interval == 0


def build_director_prompt(state: dict[str, Any], definition: dict[str, Any]) -> dict[str, Any]:
    recent = (state.get("narrative_context") or {}).get("recent_turns") or []
    turns = [
        {
            "turn": item.get("turn"),
            "player_input": str(item.get("player_input") or "")[:200],
            "narrative": str(item.get("narrative") or "")[:400],
        }
        for item in recent[-6:]
        if isinstance(item, dict)
    ]
    return {
        "system": (
            "你是 DZMM 的长线节奏导演。只输出一个 JSON 对象：{\"tension\": str, \"hook\": str}。"
            "tension 用一句话概括最近几回合积累的主要张力；hook 给出未来几回合值得推进的"
            "一个开放钩子（不解决、不完结）。均不超过 60 个汉字，不得出现状态、命令、"
            "规则或正文叙述。"
        ),
        "world": definition.get("name") or "",
        "hero": (state.get("hero") or {}).get("name") or "",
        "chapter": (state.get("chapter") or {}).get("title") or "",
        "plot_threads": [
            {"description": item.get("description"), "status": item.get("status")}
            for item in (state.get("plot_threads") or [])[-4:]
            if isinstance(item, dict)
        ],
        "recent_turns": turns,
    }


def parse_director_note(content: str | None) -> dict[str, str] | None:
    """Parse the strict-JSON note; any deviation returns None (silent degrade)."""

    if not isinstance(content, str) or not content.strip():
        return None
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text.removeprefix("json")
    try:
        payload = json.loads(text.strip())
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    note: dict[str, str] = {}
    for key in _NOTE_KEYS:
        value = payload.get(key)
        if not isinstance(value, str) or not value.strip():
            return None
        note[key] = value.strip()[:_NOTE_MAX_CHARS]
    return note


def is_note_fresh(note_turn: int | None, current_turn: int) -> bool:
    """A note injected into the GM context must come from a recent cycle."""

    if note_turn is None or note_turn <= 0:
        return False
    return current_turn - note_turn <= DIRECTOR_FRESHNESS_TURNS
