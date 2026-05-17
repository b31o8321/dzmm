"""
engine/items.py — Item use/add/remove for the v0.15 engine.

Public API:
  resolve_use_item(s, session_id, character_id, item_name) -> dict
  add_item_to_inventory(s, character_id, item)             -> None
  remove_item_from_inventory(s, character_id, item_name, qty=1) -> bool
"""

from __future__ import annotations

import json
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.db.models import Character
from dzmm.engine.character import apply_vital_delta
from dzmm.engine.schema import Item, parse_items

logger = logging.getLogger(__name__)


# ── Internal helpers ──────────────────────────────────────────────────────────

def _load_inventory(char: Character) -> list[Item]:
    return parse_items(char.inventory_json)


async def _save_inventory(s: AsyncSession, char: Character, items: list[Item]) -> None:
    char.inventory_json = json.dumps(
        [i.model_dump() for i in items], ensure_ascii=False
    )
    await s.flush()


# ── Public functions ───────────────────────────────────────────────────────────

async def resolve_use_item(
    s: AsyncSession,
    session_id: int,
    character_id: int,
    item_name: str,
) -> dict:
    """Use an item from the character's inventory.

    Finds the first item matching item_name (case-sensitive).
    Applies heal/damage effects immediately via apply_vital_delta.
    Other effect types (stat_bonus, skill_bonus, consume, unlock) are
    logged only — actual application happens in Batch 2/3 tag handlers.

    Decrements qty by 1. Removes the item entirely when:
      - qty reaches 0, OR
      - item_type == "consumable" and qty was already 1

    Returns:
      {
        "item": Item,
        "applied_effects": [{"type": ..., "amount": ...}, ...],
        "removed_from_inventory": bool,
      }

    Raises ValueError if item not found or qty == 0.
    """
    char = await s.get(Character, character_id)
    if char is None:
        raise ValueError(f"Character {character_id} not found")

    inventory = _load_inventory(char)

    # Find item by name
    idx = next((i for i, it in enumerate(inventory) if it.name == item_name), None)
    if idx is None:
        raise ValueError(f"Item {item_name!r} not found in inventory")

    item = inventory[idx]
    if item.qty <= 0:
        raise ValueError(f"Item {item_name!r} has qty=0; cannot use")

    applied_effects: list[dict] = []

    for effect in item.effects:
        match effect.type:
            case "heal_hp":
                await apply_vital_delta(s, session_id, character_id, hp=effect.amount)
                applied_effects.append({"type": "heal_hp", "amount": effect.amount})
            case "heal_sanity":
                await apply_vital_delta(s, session_id, character_id, sanity=effect.amount)
                applied_effects.append({"type": "heal_sanity", "amount": effect.amount})
            case "heal_stamina":
                await apply_vital_delta(s, session_id, character_id, stamina=effect.amount)
                applied_effects.append({"type": "heal_stamina", "amount": effect.amount})
            case "damage":
                await apply_vital_delta(s, session_id, character_id, hp=-effect.amount)
                applied_effects.append({"type": "damage", "amount": effect.amount})
            case _:
                # stat_bonus / skill_bonus / consume / unlock — log only
                logger.info(
                    "resolve_use_item: deferred effect %s on item %r (Batch 2/3)",
                    effect.type, item_name,
                )
                applied_effects.append({"type": effect.type, "amount": effect.amount})

    # Determine whether to decrement or remove.
    # Non-consumable types (weapon/armor/key/quest) are not depleted on use —
    # they are "activated" but remain in inventory at the same qty.
    # Only consumable items lose qty and are removed when qty reaches 0.
    _CONSUMABLE_ONLY_TYPES = {"consumable"}
    removed = False

    if item.item_type in _CONSUMABLE_ONLY_TYPES:
        new_qty = item.qty - 1
        if new_qty <= 0:
            inventory.pop(idx)
            removed = True
        else:
            inventory[idx] = item.model_copy(update={"qty": new_qty})
    # else: weapon / armor / key / quest — qty unchanged, item stays

    await _save_inventory(s, char, inventory)

    return {
        "item": item,
        "applied_effects": applied_effects,
        "removed_from_inventory": removed,
    }


async def add_item_to_inventory(
    s: AsyncSession,
    character_id: int,
    item: Item,
) -> None:
    """Add an item to inventory, merging qty if the same name+type already exists."""
    char = await s.get(Character, character_id)
    if char is None:
        raise ValueError(f"Character {character_id} not found")

    inventory = _load_inventory(char)

    # Merge if matching name+type exists
    for i, existing in enumerate(inventory):
        if existing.name == item.name and existing.item_type == item.item_type:
            inventory[i] = existing.model_copy(update={"qty": existing.qty + item.qty})
            await _save_inventory(s, char, inventory)
            return

    # Not found — append as new item
    inventory.append(item)
    await _save_inventory(s, char, inventory)


async def remove_item_from_inventory(
    s: AsyncSession,
    character_id: int,
    item_name: str,
    qty: int = 1,
) -> bool:
    """Remove qty units of item_name from inventory.

    Returns True if successful, False if item not found or insufficient qty.
    """
    char = await s.get(Character, character_id)
    if char is None:
        raise ValueError(f"Character {character_id} not found")

    inventory = _load_inventory(char)

    idx = next((i for i, it in enumerate(inventory) if it.name == item_name), None)
    if idx is None:
        return False

    item = inventory[idx]
    if item.qty < qty:
        return False

    new_qty = item.qty - qty
    if new_qty == 0:
        inventory.pop(idx)
    else:
        inventory[idx] = item.model_copy(update={"qty": new_qty})

    await _save_inventory(s, char, inventory)
    return True
