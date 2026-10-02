from __future__ import annotations

from typing import Any


def build_run_presentation(definition: dict[str, Any]) -> dict[str, Any]:
    """Project validated World content into player-facing Run labels."""
    from .narrative import BASE_SKILLS

    cards = {item["id"]: item["name"] for item in definition["character_cards"]}
    relationship_names = {
        relationship["id"]: cards[relationship["character_card_id"]]
        for relationship in definition["story"]["relationships"]
    }
    return {
        "world_name": definition["name"],
        "locations": {item["id"]: item["name"] for item in definition["locations"]},
        "resources": {item["id"]: item["name"] for item in definition["resources"]},
        "relationships": relationship_names,
        "chapters": {item["id"]: item["title"] for item in definition["story"]["chapters"]},
        "routes": {item["id"]: item["name"] for item in definition["story"]["routes"]},
        "skills": {
            "base": sorted(BASE_SKILLS),
            "world": sorted(definition.get("skills") or []),
        },
        "quests": {
            quest["id"]: quest.get("title") or quest["id"]
            for quest in definition["story"].get("quests") or []
        },
        "resource_effects": {
            item["id"]: item["on_use"]
            for item in definition.get("resources") or []
            if item.get("on_use")
        },
    }
