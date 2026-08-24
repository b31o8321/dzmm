"""Transport-neutral TurnCommand application.

The engine knows only WorldDefinition/RunState and injected validation/error
hooks. FastAPI, Flutter and model adapters cannot bypass this function when a
RunState mutation is requested.
"""

from __future__ import annotations

from collections.abc import Callable
from secrets import randbelow
from typing import Any

from ..narrative import (
    NarrativeRuleError,
    advance_chapter,
    choose_story_choice,
    evaluate_endings,
)


def apply_commands(
    state: dict[str, Any],
    definition: dict[str, Any],
    commands: list[dict[str, Any]],
    *,
    validate_command: Callable[[dict[str, Any]], None],
    error_type: type[Exception],
) -> list[dict[str, Any]]:
    """Apply only the allowlisted commands and return an audit outcome list."""

    known_locations = {location["id"] for location in definition["locations"]}
    known_entities = {
        entity["id"]
        for group in ("locations", "factions", "npcs")
        for entity in definition[group]
    }
    known_events = {event["id"] for event in definition["events"]}
    known_resources = {resource["id"] for resource in definition["resources"]}
    outcomes: list[dict[str, Any]] = []
    for command in commands:
        validate_command(command)
        command_type = command["type"]
        if state["ending"] is not None:
            raise error_type("ending is locked; this run is read-only")
        payload = command.get("payload", {})
        if command_type == "narrate":
            outcomes.append({"type": "narrate", "accepted": True})
        elif command_type == "offer_choices":
            _require_capability(state, "choices", error_type)
            choices = payload.get("choices")
            if not isinstance(choices, list) or not all(isinstance(choice, str) for choice in choices):
                raise error_type("offer_choices requires a list of string choices")
            outcomes.append({"type": "offer_choices", "choices": choices})
        elif command_type == "roll_dice":
            _require_capability(state, "trpg", error_type)
            sides = payload.get("sides")
            if not isinstance(sides, int) or not 2 <= sides <= 100:
                raise error_type("roll_dice requires sides from 2 to 100")
            outcomes.append({"type": "roll_dice", "sides": sides, "result": randbelow(sides) + 1})
        elif command_type == "move":
            _require_capability(state, "trpg", error_type)
            location_id = payload.get("location_id")
            if location_id not in known_locations:
                raise error_type("move references an unknown location")
            state["location_id"] = location_id
            outcomes.append({"type": "move", "location_id": location_id})
        elif command_type == "set_entity_state":
            _require_capability(state, "trpg", error_type)
            entity_id = payload.get("entity_id")
            if entity_id not in known_entities:
                raise error_type("set_entity_state references an unknown entity")
            state["entities"][entity_id] = payload.get("value")
            outcomes.append({"type": "set_entity_state", "entity_id": entity_id})
        elif command_type == "set_event_state":
            _require_capability(state, "trpg", error_type)
            event_id = payload.get("event_id")
            if event_id not in known_events:
                raise error_type("set_event_state references an unknown event")
            state["events"][event_id] = payload.get("value")
            outcomes.append({"type": "set_event_state", "event_id": event_id})
        elif command_type == "inventory_change":
            _require_capability(state, "trpg", error_type)
            item_id, delta = payload.get("item_id"), payload.get("delta")
            if not isinstance(item_id, str) or not item_id or not isinstance(delta, int) or delta == 0:
                raise error_type("inventory_change requires item_id and non-zero integer delta")
            if item_id not in known_resources:
                raise error_type("inventory_change references an unknown resource")
            _change_inventory(state["inventory"], item_id, delta, error_type)
            outcomes.append({"type": "inventory_change", "item_id": item_id, "delta": delta})
        elif command_type == "choose_story_choice":
            try:
                outcomes.extend(choose_story_choice(state, definition, payload.get("choice_id")))
            except NarrativeRuleError as error:
                raise error_type(str(error)) from error
        elif command_type == "advance_chapter":
            if payload:
                raise error_type("advance_chapter does not accept a payload")
            try:
                outcomes.append(advance_chapter(state, definition))
            except NarrativeRuleError as error:
                raise error_type(str(error)) from error
        elif command_type == "evaluate_endings":
            if payload:
                raise error_type("evaluate_endings does not accept a payload")
            try:
                outcomes.append(evaluate_endings(state, definition))
            except NarrativeRuleError as error:
                raise error_type(str(error)) from error
    return outcomes


def _require_capability(state: dict[str, Any], capability: str, error_type: type[Exception]) -> None:
    if capability not in state["ruleset"]["enabled_capabilities"]:
        raise error_type(f"ruleset does not enable {capability}")


def _change_inventory(
    inventory: list[dict[str, Any]], item_id: str, delta: int, error_type: type[Exception]
) -> None:
    current = next((item for item in inventory if item.get("id") == item_id), None)
    quantity = (current.get("quantity", 0) if current else 0) + delta
    if quantity < 0:
        raise error_type("inventory cannot become negative")
    if current is None:
        inventory.append({"id": item_id, "quantity": quantity})
    elif quantity == 0:
        inventory.remove(current)
    else:
        current["quantity"] = quantity
