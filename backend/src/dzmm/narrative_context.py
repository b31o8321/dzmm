"""Canonical world entities and descriptive material shared by model adapters."""

from __future__ import annotations

from typing import Any


def narrative_entity_names(definition: dict[str, Any]) -> dict[str, list[str]]:
    def names(key: str) -> list[str]:
        values: list[str] = []
        for item in definition.get(key) or []:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or item.get("title") or "").strip()
            if name and name not in values:
                values.append(name)
        return values

    return {
        "characters": names("character_cards"),
        "npcs": names("npcs"),
        "locations": names("locations"),
        "factions": names("factions"),
        "events": names("events"),
    }


def narrative_world_material(definition: dict[str, Any]) -> dict[str, list[dict[str, str]]]:
    """Give narrators descriptive generated material, not only entity names."""

    def material(key: str, fields: tuple[str, ...]) -> list[dict[str, str]]:
        values: list[dict[str, str]] = []
        for item in definition.get(key) or []:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or item.get("title") or "").strip()
            if not name:
                continue
            details = "；".join(
                f"{field}：{str(item.get(field)).strip()}"
                for field in fields
                if str(item.get(field) or "").strip()
            )
            values.append({"name": name, "details": details})
        return values

    return {
        "characters": material("character_cards", ("role", "description")),
        "npcs": material("npcs", ("role", "description", "motivation")),
        "locations": material("locations", ("description",)),
        "factions": material("factions", ("description",)),
        "events": material("events", ("summary",)),
    }
