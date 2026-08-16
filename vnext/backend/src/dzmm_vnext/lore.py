from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class LoreSelection:
    entries: list[dict[str, Any]]
    included_ids: list[str]
    excluded_ids: list[str]
    used_characters: int


def select_lore(
    definition: dict[str, Any], player_input: str, character_budget: int
) -> LoreSelection:
    if character_budget < 1:
        raise ValueError("character_budget must be positive")
    normalized_input = player_input.casefold()
    candidates = [
        (index, entry)
        for index, entry in enumerate(definition.get("lore", []))
        if _is_active(entry, normalized_input)
    ]
    candidates.sort(key=lambda item: (-item[1]["priority"], item[0]))
    entries: list[dict[str, Any]] = []
    excluded_ids: list[str] = []
    used_characters = 0
    for _, entry in candidates:
        body = entry["body"]
        if used_characters + len(body) > character_budget:
            excluded_ids.append(entry["id"])
            continue
        entries.append(entry)
        used_characters += len(body)
    return LoreSelection(
        entries=entries,
        included_ids=[entry["id"] for entry in entries],
        excluded_ids=excluded_ids,
        used_characters=used_characters,
    )


def _is_active(entry: dict[str, Any], normalized_input: str) -> bool:
    if entry["activation"] == "always":
        return True
    return any(keyword.casefold() in normalized_input for keyword in entry.get("keywords", []))
