"""Transport-neutral TurnCommand application.

The engine knows only WorldDefinition/RunState and injected validation/error
hooks. FastAPI, Flutter and model adapters cannot bypass this function when a
RunState mutation is requested.
"""

from __future__ import annotations

from collections.abc import Callable
from secrets import randbelow
from typing import Any

from ..loop_memory import discover_knowledge
from ..narrative import (
    BASE_SKILLS,
    NarrativeRuleError,
    advance_chapter,
    choose_story_choice,
    evaluate_endings,
)
from .combat import apply_attack, apply_heal


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
        if state["ending"] is not None and command_type not in {"narrate", "offer_choices"}:
            # 同一回合内锁定结局后的收尾 narrate 合法（如指证后的场景收束）；
            # 其余命令在结局锁定后一律只读
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
        elif command_type == "adjust_clock":
            capabilities = set((state.get("ruleset") or {}).get("enabled_capabilities") or [])
            if not capabilities & {"countdown", "time"}:
                raise error_type("adjust_clock requires a time or countdown run")
            clock = state.get("clock")
            if not isinstance(clock, dict):
                raise error_type("adjust_clock requires a clock-enabled run")
            delta = payload.get("delta")
            if isinstance(delta, bool) or not isinstance(delta, int):
                raise error_type("adjust_clock requires an integer delta")
            ceiling = int(clock.get("start_minutes") or 0) or (int(clock.get("now_minutes") or 0) + 1440)
            loop_at = int(clock.get("loop_at_minutes") or 0)
            ceiling = max(ceiling, loop_at)
            now = max(0, min(ceiling, int(clock.get("now_minutes") or 0) + delta))
            clock["now_minutes"] = now
            outcomes.append({"type": "clock_adjusted", "delta": delta, "now_minutes": now})
        elif command_type == "discover":
            _require_capability(state, "loop", error_type)
            memory = state.get("loop_memory")
            if not isinstance(memory, dict):
                raise error_type("discover requires a loop-enabled run")
            entry, notes = discover_knowledge(
                memory,
                payload.get("id"),
                payload.get("text"),
                int(state.get("revision") or 0),
            )
            for note in notes:
                outcomes.append({"type": "discover_rejected", "reason": note})
            if entry is not None:
                outcomes.append({"type": "knowledge_discovered", "id": entry["id"], "text": entry["text"]})
        elif command_type == "collect_clue":
            _require_capability(state, "deduction", error_type)
            block = state.get("deduction")
            if not isinstance(block, dict):
                raise error_type("collect_clue requires a deduction-enabled run")
            clue_id = str(payload.get("id") or "").strip()
            text = str(payload.get("text") or "").strip()[:200]
            if not clue_id or not text:
                raise error_type("collect_clue requires id and text")
            clues = block.setdefault("clues", [])
            existing = next((item for item in clues if item["id"] == clue_id), None)
            if existing is not None:
                existing["text"] = text
                outcomes.append({"type": "clue_updated", "id": clue_id})
            elif len(clues) >= 24:
                raise error_type("collect_clue reached the 24-clue cap")
            else:
                clues.append({"id": clue_id, "text": text, "turn": int(state.get("revision") or 0)})
                outcomes.append({"type": "clue_collected", "id": clue_id, "text": text})
        elif command_type == "accuse":
            _require_capability(state, "deduction", error_type)
            block = state.get("deduction")
            if not isinstance(block, dict):
                raise error_type("accuse requires a deduction-enabled run")
            mystery = definition.get("mystery") or {}
            if not mystery.get("culprit_id"):
                raise error_type("accuse requires a mystery block with culprit_id")
            suspect_id = str(payload.get("suspect_id") or "").strip()
            if not suspect_id:
                raise error_type("accuse requires suspect_id")
            accusations = block.setdefault("accusations", [])
            max_accusations = max(1, min(10, int(mystery.get("max_accusations") or 1)))
            if len(accusations) >= max_accusations:
                raise error_type("accuse reached the configured accusation cap")
            correct = suspect_id == str(mystery["culprit_id"])
            accusations.append(
                {"suspect_id": suspect_id, "correct": correct, "turn": int(state.get("revision") or 0)}
            )
            if correct:
                outcomes.append({"type": "accusation_correct", "suspect_id": suspect_id})
                state["ending"] = {
                    "id": "case-closed",
                    "kind": "good",
                    "narrative_key": "ending.case_closed",
                }
            else:
                outcomes.append({"type": "accusation_wrong", "suspect_id": suspect_id})
                if len(accusations) >= max_accusations:
                    wrong_ending_id = str(mystery.get("wrong_accusation_ending_id") or "").strip()
                    state["ending"] = {
                        "id": wrong_ending_id or "wrong-accusation",
                        "kind": "bad",
                        "narrative_key": "ending.wrong_accusation",
                    }
        elif command_type == "skill_check":
            _require_capability(state, "trpg", error_type)
            skill = str(payload.get("skill") or "").strip()
            if not skill:
                raise error_type("skill_check requires skill")
            hero = state.get("hero") or {}
            skills = hero.get("skills") or []
            # 技能目录：引擎基础集 ∪ 世界声明 ∪ 已习得；目录外一律拒绝
            known_skills = BASE_SKILLS | set(definition.get("skills") or []) | set(skills)
            if skill not in known_skills:
                raise error_type(f"skill_check references an unknown skill: {skill}")
            trained = skill in skills
            dc = payload.get("dc")
            if isinstance(dc, bool) or not isinstance(dc, int) or not 5 <= dc <= 25:
                raise error_type("skill_check requires dc from 5 to 25")
            roll = randbelow(20) + 1
            modifier = 3 if trained else 0
            total = roll + modifier
            success = total >= dc
            if roll == 20:
                degree = "critical_success"
                success = True
            elif roll == 1:
                degree = "critical_failure"
                success = False
            else:
                degree = "success" if success else "failure"
            outcomes.append({
                "type": "skill_check_result",
                "skill": skill,
                "trained": trained,
                "roll": roll,
                "modifier": modifier,
                "dc": dc,
                "total": total,
                "degree": degree,
                "success": success,
            })
        elif command_type == "use_item":
            _require_capability(state, "resources", error_type)
            item_id = str(payload.get("item_id") or "").strip()
            if not item_id:
                raise error_type("use_item requires item_id")
            if item_id not in known_resources:
                raise error_type("use_item references an unknown resource")
            held = sum(i["quantity"] for i in state.get("inventory") or [] if i["id"] == item_id)
            if held <= 0:
                raise error_type("use_item requires the item in inventory")
            resource = next(r for r in definition["resources"] if r.get("id") == item_id)
            on_use = resource.get("on_use")
            if not isinstance(on_use, dict) or not on_use:
                raise error_type(f"item has no usable effect: {item_id}")
            effect: dict[str, Any] = {"item_id": item_id}
            heal = on_use.get("heal")
            if isinstance(heal, bool) or not isinstance(heal, int) or not 1 <= heal <= 50:
                heal = None
            flag_id = str(on_use.get("flag_id") or "").strip()
            known_flags = {f["id"] for f in (definition.get("story") or {}).get("flags") or []}
            if flag_id and flag_id not in known_flags:
                raise error_type("use_item flag effect references an unknown story flag")
            if heal is None and not flag_id:
                raise error_type("item on_use must declare heal or flag_id")
            if heal is not None:
                effect.update(apply_heal(state, definition, "hero", heal))
            if flag_id:
                state.setdefault("flags", {})[flag_id] = True
                effect["flag_id"] = flag_id
            _change_inventory(state["inventory"], item_id, -1, error_type)
            effect["type"] = "item_used"
            outcomes.append(effect)
        elif command_type == "attack":
            _require_capability(state, "combat", error_type)
            try:
                outcomes.append(apply_attack(state, definition, payload))
            except NarrativeRuleError as error:
                raise error_type(str(error)) from error
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
