from __future__ import annotations

from copy import deepcopy
from typing import Any

from .world_templates import fog_harbor_template


def extend_story_for_long_run(
    definition: dict[str, Any],
    world_name: str,
    locations: list[str],
    character_names: list[str],
    skeleton: dict[str, Any] | None = None,
) -> bool:
    """Extend the compact three-chapter AI skeleton into a playable campaign."""

    story = definition.get("story")
    chapters = story.get("chapters") if isinstance(story, dict) else None
    if (
        not isinstance(chapters, list)
        or len(chapters) != 3
        or len(locations) < 2
        or not character_names
    ):
        return False
    from .genre_presets import DEFAULT_SKELETON

    labels = skeleton or DEFAULT_SKELETON
    terminal = deepcopy(chapters.pop())
    terminal["id"] = "ch10"
    terminal["order"] = 10
    terminal["next_chapter_id"] = None
    terminal["title"] = labels["terminal_title"].format(location=locations[1])
    terminal["choices"][0]["label"] = labels["terminal_choices"][0].format(
        location=locations[1]
    )
    terminal["choices"][1]["label"] = labels["terminal_choices"][1]
    for order in range(3, 10):
        location = locations[(order - 1) % len(locations)]
        character = character_names[(order - 3) % len(character_names)]
        chapters.append(
            {
                "id": f"ch{order}",
                "title": labels["longrun_title"].format(world=world_name, n=order - 2),
                "order": order,
                "next_chapter_id": f"ch{order + 1}",
                "choices": [
                    {
                        "id": f"investigate-{order}",
                        "label": labels["longrun_choices"][0].format(
                            location=location, character=character
                        ),
                        "effects": [],
                    },
                    {
                        "id": f"ask-{order}",
                        "label": labels["longrun_choices"][1].format(
                            location=location, character=character
                        ),
                        "effects": [],
                    },
                ],
            }
        )
    chapters.append(terminal)
    return True


def repair_generated_definition(definition: Any) -> tuple[dict[str, Any], list[str]]:
    """Fill only chapter/link metadata derivable from the model's own draft."""

    if not isinstance(definition, dict):
        return {}, []
    repaired = deepcopy(definition)
    story = repaired.get("story")
    chapters = story.get("chapters") if isinstance(story, dict) else None
    if (
        not isinstance(chapters, list)
        or not chapters
        or not all(isinstance(item, dict) for item in chapters)
    ):
        return repaired, []
    repairs: list[str] = []
    for index, chapter in enumerate(chapters, start=1):
        if "order" not in chapter:
            chapter["order"] = index
            repairs.append(f"story.chapters[{index - 1}].order 已按章节顺序补齐")
    for index, chapter in enumerate(chapters):
        if "next_chapter_id" not in chapter:
            chapter["next_chapter_id"] = (
                chapters[index + 1].get("id") if index + 1 < len(chapters) else None
            )
            repairs.append(f"story.chapters[{index}].next_chapter_id 已按章节顺序补齐")
    relationships = story.get("relationships") if isinstance(story, dict) else None
    cards = repaired.get("character_cards")
    card_ids = (
        {
            item.get("id")
            for item in cards
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        }
        if isinstance(cards, list)
        else set()
    )
    if isinstance(relationships, list):
        for index, relationship in enumerate(relationships):
            if not isinstance(relationship, dict) or "character_card_id" in relationship:
                continue
            relationship_id = relationship.get("id")
            if relationship_id in card_ids:
                relationship["character_card_id"] = relationship_id
                repairs.append(f"story.relationships[{index}].character_card_id 已按同名角色卡补齐")
    return repaired, repairs


def map_to_safe_story_skeleton(
    definition: Any, hero: Any
) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    """Keep model-authored names while replacing untrusted mechanics with the vetted template."""

    if not isinstance(definition, dict) or not isinstance(definition.get("story"), dict):
        return {}, {}, []
    definition = deepcopy(definition)
    story = definition["story"]
    compact_story_repaired = False
    if not isinstance(story.get("chapters"), list):
        compact_chapters = [
            {"id": key, "title": str(value)[:120], "choices": []}
            for key, value in sorted(story.items())
            if key.startswith("chapter_") and isinstance(value, str) and value.strip()
        ]
        if compact_chapters:
            story["chapters"] = compact_chapters
            compact_story_repaired = True
    chapters = definition["story"].get("chapters")
    if not isinstance(chapters, list) or len(chapters) < 1:
        return {}, {}, []
    model_name = definition.get("name")
    if not isinstance(model_name, str) or not model_name.strip():
        return {}, {}, []
    model_cards = definition.get("character_cards")
    model_locations = definition.get("locations")
    if not _has_named_items(model_cards, minimum=2) or not _has_named_items(model_locations, minimum=2):
        # A safe mechanics skeleton is not useful if the model did not provide
        # enough player-facing material to identify the world and its cast.
        return {}, {}, []
    template = fog_harbor_template()
    safe_definition = deepcopy(template["world_definition"])
    safe_hero = deepcopy(template["hero"])
    repairs = [
        "模型 mechanics 未通过 canonical schema，已使用受控 hybrid 规则骨架",
        "模型输出仅映射世界名称与可安全识别的角色/地点名称",
    ]
    if compact_story_repaired:
        repairs.append("模型 compact story 已转换为可审阅章节素材")
    safe_definition["name"] = model_name.strip()[:120]
    for index, card in enumerate(model_cards[: len(safe_definition["character_cards"])]):
        if not isinstance(card, dict) or not isinstance(card.get("name"), str):
            continue
        safe_definition["character_cards"][index]["name"] = card["name"].strip()[:120]
        repairs.append(f"character_cards[{index}].name 已安全映射")
    for index, location in enumerate(model_locations[: len(safe_definition["locations"])]):
        if not isinstance(location, dict) or not isinstance(location.get("name"), str):
            continue
        safe_definition["locations"][index]["name"] = location["name"].strip()[:120]
        repairs.append(f"locations[{index}].name 已安全映射")
    for index, location in enumerate(model_locations[len(safe_definition["locations"]):], start=3):
        if not isinstance(location, dict) or not isinstance(location.get("name"), str):
            continue
        safe_definition["locations"].append(
            {"id": f"location-{index}", "name": location["name"].strip()[:120]}
        )
        repairs.append(f"locations[{index - 1}].name 已安全追加")
    _replace_template_lorebook(safe_definition, definition)
    _replace_template_resources(safe_definition)
    _preserve_runtime_material(safe_definition, definition)
    if _rename_story_surface(safe_definition):
        repairs.append("story surface 已按生成角色与地点名称重写")
    if isinstance(hero, dict) and isinstance(hero.get("name"), str) and hero["name"].strip():
        safe_hero["name"] = hero["name"].strip()[:120]
        repairs.append("hero.name 已安全映射")
    return safe_definition, safe_hero, repairs


def _rename_story_surface(definition: dict[str, Any]) -> bool:
    """Keep vetted mechanics while avoiding template names in player-facing copy."""

    story = definition.get("story")
    cards = definition.get("character_cards")
    locations = definition.get("locations")
    if not isinstance(story, dict) or not isinstance(cards, list) or not isinstance(locations, list):
        return False
    character_names = [
        item.get("name")
        for item in cards[:2]
        if isinstance(item, dict) and isinstance(item.get("name"), str) and item["name"].strip()
    ]
    location_names = [
        item.get("name")
        for item in locations[:2]
        if isinstance(item, dict) and isinstance(item.get("name"), str) and item["name"].strip()
    ]
    if not character_names or not location_names:
        return False
    first_character = character_names[0]
    second_character = character_names[1] if len(character_names) > 1 else first_character
    first_location = location_names[0]
    second_location = location_names[1] if len(location_names) > 1 else first_location
    changed = False

    routes = story.get("routes")
    if isinstance(routes, list):
        route_names = [f"{first_character}路线", f"{second_character}路线"]
        for index, name in enumerate(route_names):
            if index >= len(routes) or not isinstance(routes[index], dict):
                continue
            if routes[index].get("name") != name:
                routes[index]["name"] = name
                changed = True

    chapters = story.get("chapters")
    if not isinstance(chapters, list):
        return changed
    if chapters and isinstance(chapters[0], dict):
        if chapters[0].get("title") != f"抵达{first_location}":
            chapters[0]["title"] = f"抵达{first_location}"
            changed = True
        choices = chapters[0].get("choices")
        if isinstance(choices, list):
            labels = [f"援手{first_character}", f"替{second_character}保守秘密"]
            for index, label in enumerate(labels):
                if index >= len(choices) or not isinstance(choices[index], dict):
                    continue
                if choices[index].get("label") != label:
                    choices[index]["label"] = label
                    changed = True
    if len(chapters) > 1 and isinstance(chapters[1], dict):
        if chapters[1].get("title") != f"{first_location}的证词":
            chapters[1]["title"] = f"{first_location}的证词"
            changed = True
        choices = chapters[1].get("choices")
        if isinstance(choices, list):
            labels = [
                f"把证词交给{first_character}",
                f"帮助{second_character}坦白",
                f"独自追查{first_location}的线索",
                f"让{first_character}与{second_character}共同作证",
            ]
            for index, label in enumerate(labels):
                if index >= len(choices) or not isinstance(choices[index], dict):
                    continue
                if choices[index].get("label") != label:
                    choices[index]["label"] = label
                    changed = True
    if (
        len(chapters) > 2
        and isinstance(chapters[2], dict)
        and chapters[2].get("title") != f"{second_location}的决断"
    ):
        chapters[2]["title"] = f"{second_location}的决断"
        changed = True
    if len(chapters) > 2 and isinstance(chapters[2], dict):
        choices = chapters[2].get("choices")
        if isinstance(choices, list):
            labels = [f"在{second_location}完成关键行动", "暂缓行动"]
            for index, label in enumerate(labels):
                if index >= len(choices) or not isinstance(choices[index], dict):
                    continue
                if choices[index].get("label") != label:
                    choices[index]["label"] = label
                    changed = True
    if extend_story_for_long_run(
        definition,
        str(definition.get("name", "世界")),
        location_names,
        character_names,
    ):
        changed = True
    return changed


def _has_named_items(value: object, *, minimum: int) -> bool:
    if not isinstance(value, list):
        return False
    names = {
        str(item.get("name") or "").strip()
        for item in value
        if isinstance(item, dict) and str(item.get("name") or "").strip()
    }
    return len(names) >= minimum


def _replace_template_lorebook(
    safe_definition: dict[str, Any], model_definition: dict[str, Any]
) -> None:
    """Never carry the fog-harbor lore into a generated world."""

    model_lorebook = model_definition.get("lorebook")
    model_entries = model_lorebook.get("entries") if isinstance(model_lorebook, dict) else None
    entries: list[dict[str, Any]] = []
    if isinstance(model_entries, list):
        for index, entry in enumerate(model_entries[:4], start=1):
            if not isinstance(entry, dict):
                continue
            title = str(entry.get("title") or "").strip()
            body = str(entry.get("body") or "").strip()
            if not title or not body:
                continue
            entries.append(
                {
                    "id": f"lore-{index}",
                    "title": title[:120],
                    "body": body[:4000],
                    "activation": "always" if index == 1 else "keyword",
                    "keywords": [] if index == 1 else [safe_definition["name"]],
                    "priority": max(10, 100 - index * 10),
                }
            )
    safe_definition["lorebook"] = {"entries": entries}


def _replace_template_resources(safe_definition: dict[str, Any]) -> None:
    """Keep the vetted resource effect but remove its template-facing name."""

    resources = safe_definition.get("resources")
    if isinstance(resources, list) and resources:
        resources[0]["name"] = "关键线索"


def _preserve_runtime_material(safe_definition: dict[str, Any], model_definition: dict[str, Any]) -> None:
    """Keep descriptive NPC/event material while discarding model mechanics."""

    location_ids = [item["id"] for item in safe_definition.get("locations") or []]
    location_names = {
        str(item.get("name")): item["id"]
        for item in safe_definition.get("locations") or []
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    }

    def location_id(value: object, fallback: int = 0) -> str:
        if isinstance(value, str) and value in location_ids:
            return value
        if isinstance(value, str) and value in location_names:
            return location_names[value]
        return location_ids[fallback % len(location_ids)]

    cards = model_definition.get("character_cards")
    runtime_npcs: list[dict[str, Any]] = []
    if isinstance(cards, list):
        for index, card in enumerate(cards[:2]):
            if not isinstance(card, dict) or not isinstance(card.get("name"), str):
                continue
            mapped = card.get("mapped") if isinstance(card.get("mapped"), dict) else {}
            runtime_npcs.append(
                {
                    "id": ("lan", "shen_yan")[index],
                    "name": card["name"].strip()[:120],
                    "role": str(mapped.get("personality") or card.get("role") or "")[:160],
                    "description": str(
                        mapped.get("description") or card.get("description") or ""
                    )[:1200],
                    "motivation": "",
                    "location_id": location_ids[index % len(location_ids)],
                    "contact_cooldown_turns": 4,
                }
            )
    model_npcs = model_definition.get("npcs")
    if isinstance(model_npcs, list):
        for index, npc in enumerate(model_npcs[:4], start=1):
            if not isinstance(npc, dict) or not isinstance(npc.get("name"), str):
                continue
            runtime_npcs.append(
                {
                    "id": f"npc-{index}",
                    "name": npc["name"].strip()[:120],
                    "role": str(npc.get("role") or "")[:160],
                    "description": str(npc.get("description") or "")[:1200],
                    "motivation": str(npc.get("motivation") or "")[:600],
                    "location_id": location_id(npc.get("location_id") or npc.get("location"), index),
                    "contact_cooldown_turns": _bounded_int(npc.get("contact_cooldown_turns"), 4, 1, 40),
                    "faction_id": npc.get("faction_id") if isinstance(npc.get("faction_id"), str) else None,
                    "reputation": _bounded_int(npc.get("reputation"), 0, -100, 100),
                }
            )
    safe_definition["npcs"] = _unique_named_entities(runtime_npcs)

    runtime_factions: list[dict[str, Any]] = []
    model_factions = model_definition.get("factions")
    if isinstance(model_factions, list):
        for index, faction in enumerate(model_factions[:3], start=1):
            if not isinstance(faction, dict) or not isinstance(faction.get("name"), str):
                continue
            runtime_factions.append(
                {
                    "id": f"faction-{index}",
                    "name": faction["name"].strip()[:120],
                    "description": str(faction.get("description") or "")[:1200],
                    "initial_tension": _bounded_int(faction.get("initial_tension"), 0, 0, 100),
                    "tension_rules": {
                        "passive_gain_per_turn": _bounded_int(faction.get("passive_gain_per_turn"), 0, 0, 10),
                        "threshold_conflict": _bounded_int(faction.get("threshold_conflict"), 80, 1, 100),
                    },
                }
            )
    safe_definition["factions"] = _unique_named_entities(runtime_factions)

    runtime_events: list[dict[str, Any]] = []
    model_events = model_definition.get("events")
    if isinstance(model_events, list):
        for index, event in enumerate(model_events[:4], start=1):
            if not isinstance(event, dict) or not isinstance(event.get("name"), str):
                continue
            runtime_events.append(
                {
                    "id": f"event-{index}",
                    "name": event["name"].strip()[:120],
                    "summary": str(event.get("summary") or event.get("description") or "")[:1200],
                    "scope_ref": location_id(event.get("scope_ref") or event.get("location"), index),
                    "importance": _bounded_int(event.get("importance"), 2, 1, 5),
                    "trigger_turn": _bounded_int(event.get("trigger_turn"), None, 1, 40),
                    "initial_active": bool(event.get("initial_active")),
                    "trigger_conditions": event.get("trigger_conditions")
                    if isinstance(event.get("trigger_conditions"), dict)
                    else event.get("trigger")
                    if isinstance(event.get("trigger"), dict)
                    else {},
                    "completion_conditions": event.get("completion_conditions")
                    if isinstance(event.get("completion_conditions"), dict)
                    else event.get("completion")
                    if isinstance(event.get("completion"), dict)
                    else {},
                    "campaign_phase_id": event.get("campaign_phase_id")
                    if isinstance(event.get("campaign_phase_id"), str)
                    else None,
                }
            )
    safe_definition["events"] = _unique_named_entities(runtime_events)


def _bounded_int(value: object, default: int | None, minimum: int, maximum: int) -> int | None:
    try:
        if value is None:
            return default
        return max(minimum, min(maximum, int(value)))
    except (TypeError, ValueError):
        return default


def _unique_named_entities(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for item in items:
        name = str(item.get("name") or "")
        if not name or name in seen:
            continue
        seen.add(name)
        result.append(item)
    return result
