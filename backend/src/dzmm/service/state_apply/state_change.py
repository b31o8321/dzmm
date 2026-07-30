"""<state_change> handler — mutate CharState stats / inventory.

v0.54: negative HP deltas are now **rejected** — they silently bypassed the
Python combat engine (<attack> / <dice_request>) and let models skip the
proper resolution path. Rejection records are stored in
Session.mechanic_warnings_json so that _build_key_facts can surface them
as a ⚠️ warning block for the GM next turn.

Negative sanity / stamina deltas are still allowed (narrative decay is
acceptable and not combat-driven).
"""

import json
import logging
from datetime import datetime, UTC

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.db.models import Character, CharState, Session as GameSession
from dzmm.engine.schema import Item, parse_items
from dzmm.parsing.repair import parse_loose_json

log = logging.getLogger(__name__)

# Vital stats — these represent "life/mind/stamina" and clamp at 0 on the
# low side. Letting them drop arbitrarily negative (e.g. HP=-250) hides
# game-over conditions: the GM kept narrating combat / torment but the
# panel just kept incrementing damage. A 0 floor surfaces the dead-or-down
# state cleanly, and game.py injects a bad-ending hint when the floor is
# hit (see _critical_vitals_hint).
_VITAL_STATS = frozenset({"hp", "sanity", "stamina"})

# Per-emit absolute delta cap for vital stats. PC base values run ~15-30,
# so a single state_change should also stay around that scale. Without a
# cap, GMs (especially under doom_score pressure) escalate compoundly:
# observed real-world session showed -30 → -50 → -70 → -100 → -150 → -200
# over consecutive turns, each emit doubling the previous. Cap at ±25 per
# emit makes runaway impossible while still allowing dramatic single-turn
# hits.
_VITAL_DELTA_MAX = 25


async def _record_mechanic_warning(
    session: AsyncSession,
    session_id: int,
    record: dict,
) -> None:
    """Append a warning record to Session.mechanic_warnings_json (max 20 stored)."""
    sess = await session.get(GameSession, session_id)
    if sess is None:
        return
    try:
        existing: list = json.loads(getattr(sess, "mechanic_warnings_json", None) or "[]")
        if not isinstance(existing, list):
            existing = []
    except (TypeError, ValueError):
        existing = []
    existing.append(record)
    # Keep a reasonable cap to prevent unbounded growth
    sess.mechanic_warnings_json = json.dumps(existing[-20:], ensure_ascii=False)


async def _apply_state_change(
    session: AsyncSession, session_id: int, raw: str, current_turn: int = 0
) -> bool:
    payload = parse_loose_json(raw)
    if not payload:
        return False

    cs = (
        await session.execute(
            select(CharState).where(CharState.session_id == session_id)
        )
    ).scalar_one_or_none()
    if cs is None:
        cs = CharState(session_id=session_id, stats_json="{}", inventory_json="[]")
        session.add(cs)

    stats = json.loads(cs.stats_json or "{}")
    inventory = json.loads(cs.inventory_json or "[]")
    sess = await session.get(GameSession, session_id)
    character = (
        await session.get(Character, sess.character_id)
        if sess is not None
        else None
    )
    canonical_inventory = (
        parse_items(character.inventory_json or "[]")
        if character is not None
        else []
    )
    canonical_inventory_changed = False
    applied = False

    for key, val in payload.items():
        if key == "inventory_add" and isinstance(val, list):
            inventory.extend(str(x) for x in val)
            for raw_item in val:
                try:
                    if isinstance(raw_item, dict):
                        item_data = {**raw_item}
                        item_data.setdefault("item_type", "quest")
                        item = Item.model_validate(item_data)
                    else:
                        item = Item(
                            name=str(raw_item), qty=1, item_type="quest",
                        )
                except Exception:
                    continue
                existing = next(
                    (
                        current for current in canonical_inventory
                        if current.name == item.name
                        and current.item_type == item.item_type
                    ),
                    None,
                )
                if existing is None:
                    canonical_inventory.append(item)
                else:
                    existing.qty += item.qty
                canonical_inventory_changed = True
            applied = True
        elif key == "inventory_remove" and isinstance(val, list):
            for item in val:
                if item in inventory:
                    inventory.remove(item)
                item_name = (
                    str(item.get("name", ""))
                    if isinstance(item, dict)
                    else str(item)
                )
                idx = next(
                    (
                        i for i, current in enumerate(canonical_inventory)
                        if current.name == item_name
                    ),
                    None,
                )
                if idx is not None:
                    current = canonical_inventory[idx]
                    if current.qty <= 1:
                        canonical_inventory.pop(idx)
                    else:
                        canonical_inventory[idx] = current.model_copy(
                            update={"qty": current.qty - 1},
                        )
                    canonical_inventory_changed = True
            applied = True
        elif isinstance(val, (int, float)):
            delta = val

            # v0.54: Reject negative HP deltas — combat damage must go through
            # <attack> or <dice_request>, not <state_change hp="-N"/>.
            if key == "hp" and delta < 0:
                log.warning(
                    "state_change: rejected negative HP delta %s for session %d "
                    "(use <attack> or <dice_request> for combat damage)",
                    delta, session_id,
                )
                await _record_mechanic_warning(session, session_id, {
                    "turn": current_turn,
                    "kind": "rejected_damage",
                    "tag": "state_change",
                    "attempted": {"hp": delta},
                    "reason": "战斗伤害走 <attack> 或 <dice_request>，<state_change hp=-N> 已禁用",
                })
                continue  # skip applying this delta

            # Narrative sanity / stamina decay is acceptable — allow but log.
            if key in ("sanity", "stamina") and delta < 0:
                log.info(
                    "state_change: narrative %s decay %s for session %d (allowed)",
                    key, delta, session_id,
                )

            if key in _VITAL_STATS and abs(delta) > _VITAL_DELTA_MAX:
                # Preserve sign, cap magnitude. The GM narrative still
                # describes "巨大伤害"; we just refuse to let the number
                # spiral.
                delta = _VITAL_DELTA_MAX if delta > 0 else -_VITAL_DELTA_MAX
            new_val = stats.get(key, 0) + delta
            if key in _VITAL_STATS and new_val < 0:
                new_val = 0
            stats[key] = new_val
            applied = True

    cs.stats_json = json.dumps(stats, ensure_ascii=False)
    cs.inventory_json = json.dumps(inventory, ensure_ascii=False)
    if character is not None and canonical_inventory_changed:
        character.inventory_json = json.dumps(
            [item.model_dump() for item in canonical_inventory],
            ensure_ascii=False,
        )
    cs.updated_at = datetime.now(UTC).replace(tzinfo=None)
    return applied
