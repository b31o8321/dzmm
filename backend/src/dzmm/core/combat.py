"""Deterministic d20-style combat for the ``combat`` capability.

The Python engine decides hit/miss and damage; the model only narrates the
outcome.  Numeric defaults live here and a ruleset may override them through
``ruleset["combat_rules"]``; unknown override keys are ignored so a definition
typo cannot invent new mechanics.
"""

from __future__ import annotations

from secrets import randbelow
from typing import Any

from ..narrative import NarrativeRuleError

DEFAULT_COMBAT_RULES: dict[str, dict[str, Any]] = {
    "hero": {
        "max_hp": 20,
        "ac": 12,
        "attack_bonus": 3,
        "damage": {"count": 1, "sides": 8, "bonus": 1},
    },
    "npc": {
        "max_hp": 10,
        "ac": 11,
        "attack_bonus": 2,
        "damage": {"count": 1, "sides": 6, "bonus": 0},
    },
}

_COMBAT_STAT_KEYS = {"max_hp", "ac", "attack_bonus"}


def combat_rules(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Merge ``ruleset["combat_rules"]`` overrides on top of the defaults."""

    overrides = state["ruleset"].get("combat_rules")
    merged: dict[str, dict[str, Any]] = {}
    for role, defaults in DEFAULT_COMBAT_RULES.items():
        role_rules = dict(defaults)
        role_overrides = overrides.get(role) if isinstance(overrides, dict) else None
        if isinstance(role_overrides, dict):
            for key, value in role_overrides.items():
                if key == "damage" and isinstance(value, dict):
                    role_rules["damage"] = {**role_rules["damage"], **value}
                elif key in _COMBAT_STAT_KEYS:
                    role_rules[key] = value
        merged[role] = role_rules
    return merged


def apply_attack(
    state: dict[str, Any], definition: dict[str, Any], payload: Any
) -> dict[str, Any]:
    """Resolve one attack roll, mutate participant HP and return the outcome."""

    if not isinstance(payload, dict):
        raise NarrativeRuleError("attack requires an object payload")
    attacker_id = payload.get("attacker_id") or "hero"
    target_id = payload.get("target_id")
    if not isinstance(attacker_id, str) or not attacker_id:
        raise NarrativeRuleError("attack attacker_id must be a non-empty string")
    if not isinstance(target_id, str) or not target_id:
        raise NarrativeRuleError("attack requires target_id")
    if attacker_id == target_id:
        raise NarrativeRuleError("attack attacker and target must differ")

    rules = combat_rules(state)
    attacker = _participant(state, definition, attacker_id, rules)
    target = _participant(state, definition, target_id, rules)
    if target["defeated"]:
        raise NarrativeRuleError(f"{target_id} is already defeated")

    roll = randbelow(20) + 1
    if roll == 20:
        hit = True
    elif roll == 1:
        hit = False
    else:
        hit = roll + attacker["attack_bonus"] >= target["ac"]

    damage = 0
    if hit:
        damage = _damage_roll(attacker["damage"], double=roll == 20)
        target["hp"] = max(0, target["hp"] - damage)
        if target["hp"] == 0:
            target["defeated"] = True
    return {
        "type": "attack",
        "attacker_id": attacker_id,
        "target_id": target_id,
        "roll": roll,
        "hit": hit,
        "damage": damage,
        "target_hp": target["hp"],
        "defeated": target["defeated"],
    }


def _participant(
    state: dict[str, Any],
    definition: dict[str, Any],
    participant_id: str,
    rules: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Return the persisted combat stats for one participant, creating them."""

    participants = state.setdefault("combat", {}).setdefault("participants", {})
    existing = participants.get(participant_id)
    if existing is not None:
        return existing

    if participant_id == "hero":
        role, overrides = "hero", state["hero"].get("combat")
    else:
        npc = _find_npc(definition, participant_id)
        if npc is None:
            raise NarrativeRuleError(f"unknown combat participant: {participant_id}")
        role, overrides = "npc", npc.get("combat")
    overrides = overrides if isinstance(overrides, dict) else {}
    base = rules[role]

    stats = {
        "role": role,
        "max_hp": _bounded(overrides.get("max_hp"), 1, 1000, base["max_hp"]),
        "hp": 0,
        "ac": _bounded(overrides.get("ac"), 0, 40, base["ac"]),
        "attack_bonus": _bounded(
            overrides.get("attack_bonus"), -10, 50, base["attack_bonus"]
        ),
        "damage": _damage(overrides.get("damage"), base["damage"]),
        "defeated": False,
    }
    stats["hp"] = stats["max_hp"]
    participants[participant_id] = stats
    return stats


def _find_npc(definition: dict[str, Any], participant_id: str) -> dict[str, Any] | None:
    for npc in [*(definition.get("npcs") or []), *(definition.get("character_cards") or [])]:
        if npc.get("id") == participant_id:
            return npc
    return None


def _damage(value: Any, base: dict[str, int]) -> dict[str, int]:
    source = value if isinstance(value, dict) else {}
    return {
        "count": _bounded(source.get("count"), 1, 10, base["count"]),
        "sides": _bounded(source.get("sides"), 2, 100, base["sides"]),
        "bonus": _bounded(source.get("bonus"), -10, 50, base["bonus"]),
    }


def _damage_roll(damage: dict[str, int], *, double: bool) -> int:
    count = damage["count"] * (2 if double else 1)
    return max(0, sum(randbelow(damage["sides"]) + 1 for _ in range(count)) + damage["bonus"])


def _bounded(value: Any, low: int, high: int, default: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, number))
