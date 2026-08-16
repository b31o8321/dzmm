from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel


class ImportReport(BaseModel):
    source_format: str
    supported_fields: list[str]
    preserved_fields: list[str]
    ignored_fields: list[str]
    warnings: list[str]


class ImportedContent(BaseModel):
    suggested_hero: dict[str, Any] | None
    lorebook: dict[str, list[dict[str, Any]]]
    character_cards: list[dict[str, Any]]
    report: ImportReport


def import_sillytavern(payload: dict[str, Any]) -> ImportedContent:
    if payload.get("spec") == "chara_card_v3" and isinstance(payload.get("data"), dict):
        return _import_v3_card(payload)
    if isinstance(payload.get("entries"), (dict, list)):
        return _import_world_info(payload)
    raise ValueError("unsupported SillyTavern content: expected V3 card or World Info entries")


def _import_v3_card(payload: dict[str, Any]) -> ImportedContent:
    data = payload["data"]
    name = _string(data.get("name")) or "Imported character"
    book = data.get("character_book") if isinstance(data.get("character_book"), dict) else {}
    entries = book.get("entries", [])
    lorebook_entries, warnings = _entries_to_lorebook_entries(entries, "card")
    profile = {
        key: data[key]
        for key in ("description", "personality", "scenario", "first_mes", "mes_example")
        if _string(data.get(key))
    }
    return ImportedContent(
        suggested_hero={"name": name, "profile": profile},
        lorebook={"entries": lorebook_entries},
        character_cards=[
            {
                "id": _card_id(name),
                "name": name,
                "format": "sillytavern_v3",
                "relationship_dimensions": {},
                "mapped": {
                    **profile,
                    "character_book_entry_ids": [entry["id"] for entry in lorebook_entries],
                },
                "source_payload": payload,
            }
        ],
        report=ImportReport(
            source_format="sillytavern_v3_character_card",
            supported_fields=["data.name", "data.character_book.entries"],
            preserved_fields=["data.description", "data.personality", "data.scenario", "entry raw fields"],
            ignored_fields=["extensions", "alternate_greetings", "creator_notes"],
            warnings=warnings,
        ),
    )


def _import_world_info(payload: dict[str, Any]) -> ImportedContent:
    lorebook_entries, warnings = _entries_to_lorebook_entries(payload["entries"], "world-info")
    return ImportedContent(
        suggested_hero=None,
        lorebook={"entries": lorebook_entries},
        character_cards=[],
        report=ImportReport(
            source_format="sillytavern_world_info",
            supported_fields=["entries.keys", "entries.content", "entries.constant", "entries.order"],
            preserved_fields=["entry raw fields"],
            ignored_fields=[],
            warnings=warnings,
        ),
    )


def _entries_to_lorebook_entries(
    entries: Any, prefix: str
) -> tuple[list[dict[str, Any]], list[str]]:
    source_entries = entries.values() if isinstance(entries, dict) else entries
    if not isinstance(source_entries, list) and not hasattr(source_entries, "__iter__"):
        return [], ["entries is not iterable"]
    lorebook_entries: list[dict[str, Any]] = []
    warnings: list[str] = []
    used_ids: set[str] = set()
    for index, raw in enumerate(source_entries):
        if not isinstance(raw, dict):
            warnings.append(f"entry {index} is not an object and was ignored")
            continue
        body = _string(raw.get("content"))
        if not body:
            warnings.append(f"entry {index} has no content and was ignored")
            continue
        keys = _keywords(raw.get("keys", raw.get("key", [])))
        activation = "always" if raw.get("constant") or raw.get("always") or not keys else "keyword"
        entry_id = _unique_id(f"{prefix}-{raw.get('id', index)}", used_ids)
        used_ids.add(entry_id)
        lorebook_entries.append(
            {
                "id": entry_id,
                "title": _string(raw.get("comment")) or (keys[0] if keys else f"Imported lore {index + 1}"),
                "body": body,
                "activation": activation,
                "keywords": keys,
                "priority": _priority(raw),
                "source": {"sillytavern": raw},
            }
        )
    return lorebook_entries, warnings


def _keywords(value: Any) -> list[str]:
    values = value if isinstance(value, list) else [value]
    return [item.strip() for item in values if isinstance(item, str) and item.strip()]


def _priority(raw: dict[str, Any]) -> int:
    value = raw.get("insertion_order", raw.get("order", 0))
    return max(0, min(100, value if isinstance(value, int) else 0))


def _string(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _unique_id(raw: str, used_ids: set[str]) -> str:
    base = re.sub(r"[^a-z0-9_-]+", "-", raw.casefold()).strip("-") or "entry"
    if not base[0].isalpha():
        base = f"entry-{base}"
    base = base[:64]
    candidate, suffix = base, 2
    while candidate in used_ids:
        candidate = f"{base[:60]}-{suffix}"
        suffix += 1
    return candidate


def _card_id(name: str) -> str:
    return _unique_id(f"card-{name}", set())
