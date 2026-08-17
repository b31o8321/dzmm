from __future__ import annotations

from copy import deepcopy
from typing import Any


class NarrativeRuleError(ValueError):
    pass


_CAPABILITIES_BY_RULESET = {
    "trpg": {"trpg", "resources"},
    "story_adventure": {"chapters", "choices", "relationships", "routes", "endings", "resources"},
    "relationship_drama": {"chapters", "choices", "relationships", "routes", "endings", "resources"},
    "hybrid": {"trpg", "chapters", "choices", "relationships", "routes", "endings", "resources"},
}


def validate_definition(definition: dict[str, Any]) -> None:
    ruleset = definition["ruleset"]
    ruleset_id = ruleset["id"]
    capabilities = set(ruleset["enabled_capabilities"])
    if not capabilities <= _CAPABILITIES_BY_RULESET[ruleset_id]:
        raise NarrativeRuleError(f"ruleset {ruleset_id} contains unsupported capability")
    if ruleset_id == "trpg" and "trpg" not in capabilities:
        raise NarrativeRuleError("trpg ruleset requires trpg capability")
    if ruleset_id != "trpg" and not {"chapters", "choices", "endings"} <= capabilities:
        raise NarrativeRuleError(f"ruleset {ruleset_id} requires chapters, choices and endings")

    story = definition["story"]
    _require_unique(story["chapters"], "chapter")
    _require_unique(story["flags"], "story flag")
    _require_unique(story["relationships"], "relationship")
    _require_unique(story["relationship_events"], "relationship event")
    _require_unique(story["routes"], "route")
    _require_unique(story["endings"], "ending")
    _require_unique(definition["character_cards"], "character card")
    _require_unique(definition["resources"], "resource")

    chapter_ids = {item["id"] for item in story["chapters"]}
    if bool(story["chapters"]) != ("chapters" in capabilities):
        raise NarrativeRuleError("chapters must exist exactly when chapters capability is enabled")
    if story["chapters"]:
        orders = [chapter["order"] for chapter in story["chapters"]]
        if sorted(orders) != list(range(1, len(orders) + 1)):
            raise NarrativeRuleError("chapter order must be contiguous from 1")
        for chapter in story["chapters"]:
            if chapter["next_chapter_id"] is not None and chapter["next_chapter_id"] not in chapter_ids:
                raise NarrativeRuleError("chapter references an unknown next chapter")
        if sum(chapter["next_chapter_id"] is None for chapter in story["chapters"]) != 1:
            raise NarrativeRuleError("story needs exactly one terminal chapter")

    card_ids = {item["id"] for item in definition["character_cards"]}
    relationships = {item["id"]: item for item in story["relationships"]}
    for relationship in relationships.values():
        if relationship["character_card_id"] not in card_ids:
            raise NarrativeRuleError("relationship references an unknown character card")
        for dimension in relationship["dimensions"].values():
            if not dimension["min"] <= dimension["initial"] <= dimension["max"]:
                raise NarrativeRuleError("relationship dimension initial value is outside its bounds")
    for event in story["relationship_events"]:
        relationship = relationships.get(event["relationship_id"])
        if relationship is None:
            raise NarrativeRuleError("relationship event references an unknown relationship")
        dimensions = relationship["dimensions"]
        if not set(event["deltas"]) <= set(dimensions):
            raise NarrativeRuleError("relationship event changes an undefined dimension")
    if (story["relationships"] or story["relationship_events"]) and "relationships" not in capabilities:
        raise NarrativeRuleError("relationships require relationships capability")
    if story["routes"] and "routes" not in capabilities:
        raise NarrativeRuleError("routes require routes capability")
    if story["endings"] and "endings" not in capabilities:
        raise NarrativeRuleError("endings require endings capability")

    flag_ids = {item["id"] for item in story["flags"]}
    relationship_event_ids = {item["id"] for item in story["relationship_events"]}
    route_ids = {item["id"] for item in story["routes"]}
    resource_ids = {item["id"] for item in definition["resources"]}
    seen_choices: set[str] = set()
    for chapter in story["chapters"]:
        for choice in chapter["choices"]:
            if choice["id"] in seen_choices:
                raise NarrativeRuleError("choice ids must be globally unique")
            seen_choices.add(choice["id"])
            for effect in choice["effects"]:
                _validate_effect(effect, choice["id"], flag_ids, relationship_event_ids, route_ids, resource_ids)
    for flag in story["flags"]:
        if not set(flag["writers"]) <= {f"choice:{choice_id}" for choice_id in seen_choices}:
            raise NarrativeRuleError("story flag declares an unknown writer")


def initial_state(definition: dict[str, Any], hero: dict[str, Any]) -> dict[str, Any]:
    story = definition["story"]
    chapters = sorted(story["chapters"], key=lambda chapter: chapter["order"])
    return {
        "schema_version": 3,
        "revision": 0,
        "hero": hero,
        "ruleset": deepcopy(definition["ruleset"]),
        "location_id": definition["locations"][0]["id"],
        "inventory": [],
        "entities": {},
        "events": {},
        "chapter": (
            {"id": chapters[0]["id"], "status": "active", "resolved_choice_ids": []}
            if chapters
            else None
        ),
        "route": None,
        "flags": {flag["id"]: flag["default"] for flag in story["flags"]},
        "relationships": {
            relationship["id"]: {
                "dimensions": {
                    name: dimension["initial"]
                    for name, dimension in relationship["dimensions"].items()
                },
                "applied_events": {},
            }
            for relationship in story["relationships"]
        },
        "ending": None,
    }


def choose_story_choice(
    state: dict[str, Any], definition: dict[str, Any], choice_id: object
) -> list[dict[str, Any]]:
    _require_capability(state, "choices")
    if not isinstance(choice_id, str):
        raise NarrativeRuleError("choose_story_choice requires choice_id")
    chapter_state = state["chapter"]
    if chapter_state is None or chapter_state["status"] != "active":
        raise NarrativeRuleError("there is no active chapter")
    chapter = _chapter(definition, chapter_state["id"])
    choice = next((item for item in chapter["choices"] if item["id"] == choice_id), None)
    if choice is None:
        raise NarrativeRuleError("choice is not available in the active chapter")
    if choice_id in chapter_state["resolved_choice_ids"]:
        raise NarrativeRuleError("choice was already resolved")
    chapter_state["resolved_choice_ids"].append(choice_id)
    outcomes = [{"type": "choose_story_choice", "chapter_id": chapter["id"], "choice_id": choice_id}]
    for effect in choice["effects"]:
        outcomes.extend(_apply_effect(state, definition, effect, cause=f"choice:{choice_id}"))
    return outcomes


def advance_chapter(state: dict[str, Any], definition: dict[str, Any]) -> dict[str, Any]:
    _require_capability(state, "chapters")
    chapter_state = state["chapter"]
    if chapter_state is None or chapter_state["status"] != "active":
        raise NarrativeRuleError("there is no active chapter to advance")
    if not chapter_state["resolved_choice_ids"]:
        raise NarrativeRuleError("chapter cannot advance before resolving a choice")
    current = _chapter(definition, chapter_state["id"])
    if current["next_chapter_id"] is None:
        chapter_state["status"] = "completed"
        return {"type": "advance_chapter", "chapter_id": current["id"], "status": "completed"}
    state["chapter"] = {
        "id": current["next_chapter_id"],
        "status": "active",
        "resolved_choice_ids": [],
    }
    return {
        "type": "advance_chapter",
        "chapter_id": current["id"],
        "next_chapter_id": current["next_chapter_id"],
    }


def evaluate_endings(state: dict[str, Any], definition: dict[str, Any]) -> dict[str, Any]:
    _require_capability(state, "endings")
    if state["ending"] is not None:
        raise NarrativeRuleError("ending is already locked")
    chapter = state["chapter"]
    if chapter is None or chapter["status"] != "completed":
        raise NarrativeRuleError("ending can only be evaluated after the final chapter")
    matched = [ending for ending in definition["story"]["endings"] if _matches(ending["when"], state)]
    if not matched:
        raise NarrativeRuleError("no ending matches the completed state")
    ending = min(matched, key=lambda item: (-item["priority"], item["id"]))
    state["ending"] = {
        "id": ending["id"],
        "kind": ending["kind"],
        "narrative_key": ending["narrative_key"],
    }
    return {"type": "lock_ending", **state["ending"]}


def available_choices(state: dict[str, Any], definition: dict[str, Any]) -> list[dict[str, str]]:
    chapter_state = state["chapter"]
    if state["ending"] is not None or chapter_state is None or chapter_state["status"] != "active":
        return []
    if "choices" not in state["ruleset"]["enabled_capabilities"]:
        return []
    chapter = _chapter(definition, chapter_state["id"])
    resolved = set(chapter_state["resolved_choice_ids"])
    return [
        {"id": choice["id"], "label": choice["label"]}
        for choice in chapter["choices"]
        if choice["id"] not in resolved
    ]


def planned_choice_commands(
    state: dict[str, Any], definition: dict[str, Any], choice_id: str
) -> list[dict[str, Any]]:
    if choice_id not in {choice["id"] for choice in available_choices(state, definition)}:
        raise NarrativeRuleError("choice is not available in the active chapter")
    chapter = _chapter(definition, state["chapter"]["id"])
    commands: list[dict[str, Any]] = [
        {"type": "choose_story_choice", "payload": {"choice_id": choice_id}},
        {"type": "advance_chapter", "payload": {}},
    ]
    if chapter["next_chapter_id"] is None:
        commands.append({"type": "evaluate_endings", "payload": {}})
    return commands


def _apply_effect(
    state: dict[str, Any], definition: dict[str, Any], effect: dict[str, Any], cause: str
) -> list[dict[str, Any]]:
    effect_type = effect["type"]
    if effect_type == "set_story_flag":
        flag = next(item for item in definition["story"]["flags"] if item["id"] == effect["flag_id"])
        if cause not in flag["writers"]:
            raise NarrativeRuleError("story flag cannot be written by this choice")
        state["flags"][flag["id"]] = effect["value"]
        return [{"type": "set_story_flag", "flag_id": flag["id"], "value": effect["value"], "cause": cause}]
    if effect_type == "apply_relationship_event":
        return [_apply_relationship_event(state, definition, effect["relationship_event_id"], cause)]
    if effect_type == "grant_resource":
        _change_inventory(state["inventory"], effect["resource_id"], effect["quantity"])
        return [{"type": "grant_resource", "resource_id": effect["resource_id"], "quantity": effect["quantity"], "cause": cause}]
    if effect_type == "set_route":
        if state["route"] is not None:
            raise NarrativeRuleError("route is already locked")
        state["route"] = {"id": effect["route_id"], "status": "locked"}
        return [{"type": "lock_route", "route_id": effect["route_id"], "cause": cause}]
    raise NarrativeRuleError("unsupported story effect")


def _apply_relationship_event(
    state: dict[str, Any], definition: dict[str, Any], event_id: str, cause: str
) -> dict[str, Any]:
    _require_capability(state, "relationships")
    event = next(item for item in definition["story"]["relationship_events"] if item["id"] == event_id)
    relationship_definition = next(
        item for item in definition["story"]["relationships"] if item["id"] == event["relationship_id"]
    )
    relationship = state["relationships"].get(event["relationship_id"])
    if relationship is None:
        raise NarrativeRuleError("relationship state is unavailable for this character")
    previous = relationship["applied_events"].get(event_id)
    chapter_id = state["chapter"]["id"] if state["chapter"] else None
    if previous is not None:
        if event["once_scope"] == "run":
            raise NarrativeRuleError("relationship event is once per run")
        if event["once_scope"] == "chapter" and previous["chapter_id"] == chapter_id:
            raise NarrativeRuleError("relationship event is once per chapter")
        if previous["cooldown_until_revision"] is not None and state["revision"] < previous["cooldown_until_revision"]:
            raise NarrativeRuleError("relationship event is cooling down")
    for dimension, delta in event["deltas"].items():
        bounds = relationship_definition["dimensions"][dimension]
        relationship["dimensions"][dimension] = max(
            bounds["min"], min(bounds["max"], relationship["dimensions"][dimension] + delta)
        )
    relationship["applied_events"][event_id] = {
        "turn_revision": state["revision"] + 1,
        "reason_key": event["reason_key"],
        "chapter_id": chapter_id,
        "cooldown_until_revision": state["revision"] + event["cooldown_turns"] + 1 if event["cooldown_turns"] else None,
    }
    return {"type": "apply_relationship_event", "relationship_event_id": event_id, "relationship_id": event["relationship_id"], "character_card_id": relationship_definition["character_card_id"], "deltas": event["deltas"], "reason_key": event["reason_key"], "cause": cause}


def _matches(condition: object, state: dict[str, Any]) -> bool:
    if not isinstance(condition, dict):
        raise NarrativeRuleError("ending condition must be an object")
    if "all" in condition:
        return isinstance(condition["all"], list) and all(_matches(item, state) for item in condition["all"])
    if "any" in condition:
        return isinstance(condition["any"], list) and any(_matches(item, state) for item in condition["any"])
    if "not" in condition:
        return not _matches(condition["not"], state)
    if set(condition) == {"flag", "equals"}:
        return state["flags"].get(condition["flag"]) is condition["equals"]
    if set(condition) == {"route"}:
        return state["route"] is not None and state["route"]["id"] == condition["route"]
    if set(condition) == {"relationship", "dimension", "at_least"}:
        relation = state["relationships"].get(condition["relationship"])
        return relation is not None and relation["dimensions"].get(condition["dimension"], -101) >= condition["at_least"]
    raise NarrativeRuleError("unsupported ending condition")


def _chapter(definition: dict[str, Any], chapter_id: str) -> dict[str, Any]:
    return next(chapter for chapter in definition["story"]["chapters"] if chapter["id"] == chapter_id)


def _require_capability(state: dict[str, Any], capability: str) -> None:
    if capability not in state["ruleset"]["enabled_capabilities"]:
        raise NarrativeRuleError(f"ruleset does not enable {capability}")


def _require_unique(items: list[dict[str, Any]], name: str) -> None:
    ids = [item["id"] for item in items]
    if len(ids) != len(set(ids)):
        raise NarrativeRuleError(f"{name} ids must be unique")


def _validate_effect(effect: dict[str, Any], choice_id: str, flag_ids: set[str], relationship_event_ids: set[str], route_ids: set[str], resource_ids: set[str]) -> None:
    effect_type = effect["type"]
    if effect_type == "set_story_flag" and effect.get("flag_id") in flag_ids and isinstance(effect.get("value"), bool):
        return
    if effect_type == "apply_relationship_event" and effect.get("relationship_event_id") in relationship_event_ids:
        return
    if effect_type == "grant_resource" and effect.get("resource_id") in resource_ids and isinstance(effect.get("quantity"), int):
        return
    if effect_type == "set_route" and effect.get("route_id") in route_ids:
        return
    raise NarrativeRuleError(f"choice {choice_id} has an invalid {effect_type} effect")


def _change_inventory(inventory: list[dict[str, Any]], item_id: str, delta: int) -> None:
    current = next((item for item in inventory if item["id"] == item_id), None)
    if current is None:
        inventory.append({"id": item_id, "quantity": delta})
    else:
        current["quantity"] += delta
