"""
engine/predicates.py — Structured event trigger predicates for v0.15.

Each predicate is a Pydantic model with a `type` discriminator.
`parse_predicate(data)` parses a dict into a Predicate.
`evaluate(s, session_id, pred)` evaluates the predicate against DB state.

Safe fallback: malformed/unknown predicate → False + logged warning.
"""

from __future__ import annotations

import json
import logging
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.db.models import (
    CharState,
    Character,
    Session as GameSession,
    SessionFactionState,
    SessionNpcState,
)

logger = logging.getLogger(__name__)


# ── Leaf predicate models ─────────────────────────────────────────────────────

class LocationReachedPredicate(BaseModel):
    type: Literal["location_reached"] = "location_reached"
    location_id: int


class NpcStatePredicate(BaseModel):
    type: Literal["npc_state"] = "npc_state"
    npc_template_id: int
    state: str  # "dead" | "is_companion" | "is_revealed"


class StatThresholdPredicate(BaseModel):
    type: Literal["stat_threshold"] = "stat_threshold"
    stat: Literal["hp", "sanity", "stamina", "doom_score"]
    op: Literal["lte", "lt", "gte", "gt", "eq"]
    value: int


class ItemOwnedPredicate(BaseModel):
    type: Literal["item_owned"] = "item_owned"
    item_name: str   # case-sensitive
    min_qty: int = 1


class FactionTensionPredicate(BaseModel):
    type: Literal["faction_tension"] = "faction_tension"
    faction_id: int
    op: Literal["gte", "lte"]
    value: int


class CombinedPredicate(BaseModel):
    type: Literal["all", "any"]
    children: list[dict]


class _UnknownPredicate(BaseModel):
    """Sentinel for unrecognised predicate types — always evaluates False."""
    type: str = "unknown"
    model_config = {"extra": "allow"}


# Union type — discriminated by "type" field
Predicate = (
    LocationReachedPredicate
    | NpcStatePredicate
    | StatThresholdPredicate
    | ItemOwnedPredicate
    | FactionTensionPredicate
    | CombinedPredicate
    | _UnknownPredicate
)

_KNOWN_TYPES = {
    "location_reached": LocationReachedPredicate,
    "npc_state": NpcStatePredicate,
    "stat_threshold": StatThresholdPredicate,
    "item_owned": ItemOwnedPredicate,
    "faction_tension": FactionTensionPredicate,
    "all": CombinedPredicate,
    "any": CombinedPredicate,
}


def parse_predicate(data: dict) -> Predicate:
    """Parse a raw dict into a typed Predicate.

    Returns _UnknownPredicate for unrecognised types (evaluates to False).
    Logs a warning if the type is unknown.
    """
    if not isinstance(data, dict):
        logger.warning("parse_predicate: expected dict, got %s — returning unknown", type(data).__name__)
        return _UnknownPredicate(type="unknown")

    pred_type = data.get("type", "")
    cls = _KNOWN_TYPES.get(pred_type)
    if cls is None:
        logger.warning("parse_predicate: unknown predicate type %r — will evaluate to False", pred_type)
        return _UnknownPredicate(type=pred_type or "unknown")

    try:
        return cls.model_validate(data)
    except Exception as exc:
        logger.warning("parse_predicate: validation failed for type=%r: %s", pred_type, exc)
        return _UnknownPredicate(type=pred_type)


# ── Comparison helpers ────────────────────────────────────────────────────────

def _compare(actual: int, op: str, threshold: int) -> bool:
    if op == "lte":
        return actual <= threshold
    if op == "lt":
        return actual < threshold
    if op == "gte":
        return actual >= threshold
    if op == "gt":
        return actual > threshold
    if op == "eq":
        return actual == threshold
    return False


# ── Evaluator ─────────────────────────────────────────────────────────────────

async def evaluate(s: AsyncSession, session_id: int, pred: Predicate) -> bool:
    """Evaluate a single predicate against current session state.

    Safe fallback: any DB error or unknown predicate → False + logged warning.
    """
    try:
        return await _eval(s, session_id, pred)
    except Exception as exc:
        logger.warning(
            "evaluate: exception evaluating predicate type=%r for session %d: %s",
            getattr(pred, "type", "?"), session_id, exc,
        )
        return False


async def _eval(s: AsyncSession, session_id: int, pred: Predicate) -> bool:
    if isinstance(pred, _UnknownPredicate):
        return False

    if isinstance(pred, LocationReachedPredicate):
        # pc_location_id is stored in Session.settings_json
        sess = await s.get(GameSession, session_id)
        if sess is None:
            return False
        settings = {}
        try:
            settings = json.loads(sess.settings_json or "{}")
        except Exception:
            pass
        pc_loc = settings.get("pc_location_id")
        if pc_loc is None:
            return False
        return int(pc_loc) == pred.location_id

    if isinstance(pred, NpcStatePredicate):
        result = await s.execute(
            select(SessionNpcState).where(
                SessionNpcState.session_id == session_id,
                SessionNpcState.npc_template_id == pred.npc_template_id,
            )
        )
        npc_state = result.scalar_one_or_none()
        if npc_state is None:
            return False
        if pred.state == "dead":
            return not npc_state.is_alive
        if pred.state == "is_companion":
            return npc_state.is_companion
        if pred.state == "is_revealed":
            return npc_state.is_revealed
        logger.warning("evaluate NpcState: unknown state %r", pred.state)
        return False

    if isinstance(pred, StatThresholdPredicate):
        if pred.stat == "doom_score":
            sess = await s.get(GameSession, session_id)
            if sess is None:
                return False
            return _compare(sess.doom_score, pred.op, pred.value)

        cs = await s.get(CharState, session_id)
        if cs is None:
            return False

        if pred.stat == "stamina":
            return _compare(cs.stamina, pred.op, pred.value)

        # hp / sanity from stats_json
        try:
            stats = json.loads(cs.stats_json or "{}")
        except Exception:
            return False
        actual = stats.get(pred.stat)
        if actual is None:
            return False
        return _compare(int(actual), pred.op, pred.value)

    if isinstance(pred, ItemOwnedPredicate):
        # inventory_json lives on Character; need session → character_id
        sess = await s.get(GameSession, session_id)
        if sess is None:
            return False
        char = await s.get(Character, sess.character_id)
        if char is None:
            return False
        try:
            items = json.loads(char.inventory_json or "[]")
        except Exception:
            return False
        for item in items:
            if isinstance(item, dict) and item.get("name") == pred.item_name:
                qty = int(item.get("qty", 1))
                return qty >= pred.min_qty
        return False

    if isinstance(pred, FactionTensionPredicate):
        result = await s.execute(
            select(SessionFactionState).where(
                SessionFactionState.session_id == session_id,
                SessionFactionState.faction_id == pred.faction_id,
            )
        )
        fs = result.scalar_one_or_none()
        if fs is None:
            return False
        return _compare(fs.tension, pred.op, pred.value)

    if isinstance(pred, CombinedPredicate):
        child_results = []
        for child_dict in pred.children:
            child_pred = parse_predicate(child_dict)
            child_result = await _eval(s, session_id, child_pred)
            child_results.append(child_result)
        if pred.type == "all":
            return all(child_results)
        if pred.type == "any":
            return any(child_results)
        return False

    # Fallthrough — should not happen
    logger.warning("evaluate: unhandled predicate type %r", type(pred).__name__)
    return False
