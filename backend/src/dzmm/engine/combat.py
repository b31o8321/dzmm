"""
engine/combat.py — Combat resolution for the v0.15 engine.

Provides:
  get_attack_modifier(stat_block, weapon, *, prof_bonus) -> (int, str)
  get_damage_formula(weapon)                             -> str
  get_armor_class(stat_block, equipped_armor_effects)    -> int
  resolve_attack(s, *, session_id, attacker_id, attacker_kind,
                 target_id, target_kind, weapon_name, rng)  -> AttackResult
  roll_initiative(s, *, session_id, combatants, rng)         -> list[dict]

Design:
  - Single d20 + attack_mod vs target AC.
    Attack mod = STR_mod (melee) or DEX_mod (ranged/weapon override) + prof_bonus.
    AC = 10 + DEX_mod + sum(armor_bonus effects on equipped armor).
  - Hit → roll damage formula (e.g. "1d8+STR"). Apply via apply_vital_delta.
  - Nat-20 always hits; nat-1 always misses.
  - Initiative = d20 + DEX_mod, sorted desc.
  - NPC stats loaded from stat_block_json (sparse; defaults: all attrs 10, max_hp 20).
  - NPC HP stored in stat_block_json["current_hp"]; missing = max_hp.
"""

from __future__ import annotations

import json
import logging
import random
import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.db.models import Character, CharState, NPC
from dzmm.db.models import Session as GameSession
from dzmm.engine.character import apply_vital_delta, load_character_inventory, load_character_stats
from dzmm.engine.dice import DiceResult, get_modifier, roll
from dzmm.engine.schema import Item, ItemEffect, StatBlock, parse_items

log = logging.getLogger(__name__)

# Default proficiency bonus for this batch (Batch 4 will personalise)
_DEFAULT_PROF_BONUS = 2

# Unarmed damage formula
_UNARMED_DAMAGE = "1d4"

# Default NPC StatBlock used when stat_block_json is empty or malformed
_NPC_DEFAULT_STATS = StatBlock(
    strength=10,
    dexterity=10,
    constitution=10,
    intelligence=10,
    wisdom=10,
    charisma=10,
    max_hp=20,
    max_sanity=50,
    max_stamina=20,
)


# ── Result dataclass ──────────────────────────────────────────────────────────

@dataclass
class AttackResult:
    """Fully resolved single-attack outcome."""
    attacker_id: int                  # character_id or npc_id
    target_id: int
    attack_roll: DiceResult           # d20+mod result
    ac: int                           # target's AC at time of attack
    hit: bool
    damage_roll: DiceResult | None    # None if miss
    damage_dealt: int                 # 0 if miss
    target_hp_before: int
    target_hp_after: int
    target_defeated: bool             # True when target_hp_after <= 0


# ── Pure helpers (no DB) ──────────────────────────────────────────────────────

def get_attack_modifier(
    stat_block: StatBlock,
    weapon: Item | None,
    *,
    prof_bonus: int = _DEFAULT_PROF_BONUS,
) -> tuple[int, str]:
    """Return (total_modifier, attribute_name) for an attack roll.

    Reads weapon.effects for an 'attack_attribute' effect with stat='dexterity'
    to decide ranged (DEX) vs melee (STR, default).
    Unarmed (weapon=None) → STR_mod + prof_bonus.
    """
    # Determine whether weapon uses DEX (ranged override)
    use_dex = False
    if weapon is not None:
        for eff in weapon.effects:
            # 'attack_attribute' effect with stat='dexterity' → ranged weapon
            if eff.type == "attack_attribute" and (eff.stat or "").lower() == "dexterity":
                use_dex = True
                break

    if use_dex:
        attr_val = stat_block.dexterity
        attr_name = "dexterity"
    else:
        attr_val = stat_block.strength
        attr_name = "strength"

    return get_modifier(attr_val) + prof_bonus, attr_name


def get_damage_formula(weapon: Item | None) -> str:
    """Return damage formula string, e.g. '1d8+STR'.

    Looks for an ItemEffect with type='damage' and a 'formula' attribute.
    Falls back to _UNARMED_DAMAGE ('1d4') when no weapon or no matching effect.

    Note: the formula may contain a stat placeholder like '+STR' or '+DEX';
    the caller (resolve_attack) substitutes the actual modifier value before
    passing to dice.roll().
    """
    if weapon is None:
        return _UNARMED_DAMAGE

    # Priority 1: damage effect with explicit formula field (e.g. "1d8+STR")
    for eff in weapon.effects:
        if eff.type == "damage" and eff.formula:
            return eff.formula

    # Priority 2: weapon description contains formula pattern (e.g. "1d8+STR")
    desc = weapon.description.strip()
    formula_match = re.search(r"\d+d\d+(?:[+-]\w+)?", desc)
    if formula_match:
        return formula_match.group(0)

    # Priority 3: damage effect with nonzero amount → synthesise formula
    for eff in weapon.effects:
        if eff.type == "damage" and eff.amount > 0:
            return f"1d{max(4, eff.amount)}"

    return _UNARMED_DAMAGE


def get_armor_class(
    stat_block: StatBlock,
    equipped_armor_effects: list[ItemEffect],
) -> int:
    """Return AC = 10 + DEX_mod + sum of armor_bonus effects.

    'armor_bonus' effects are ItemEffects with type='stat_bonus' and
    stat='armor_bonus'.
    """
    dex_mod = get_modifier(stat_block.dexterity)
    # Accept both the new 'armor_bonus' type and legacy 'stat_bonus' with stat='armor_bonus'
    armor_bonus = sum(
        eff.amount
        for eff in equipped_armor_effects
        if eff.type == "armor_bonus"
        or (eff.type == "stat_bonus" and (eff.stat or "").lower() == "armor_bonus")
    )
    return 10 + dex_mod + armor_bonus


# ── NPC stat helpers ──────────────────────────────────────────────────────────

def _parse_npc_stat_block(npc: NPC) -> StatBlock:
    """Parse NPC.stat_block_json into a StatBlock, using defaults for missing keys."""
    try:
        raw = json.loads(npc.stat_block_json or "{}")
        if not isinstance(raw, dict):
            raw = {}
    except (TypeError, ValueError):
        raw = {}

    return StatBlock(
        strength=int(raw.get("strength", 10)),
        dexterity=int(raw.get("dexterity", 10)),
        constitution=int(raw.get("constitution", 10)),
        intelligence=int(raw.get("intelligence", 10)),
        wisdom=int(raw.get("wisdom", 10)),
        charisma=int(raw.get("charisma", 10)),
        max_hp=int(raw.get("max_hp", 20)),
        max_sanity=int(raw.get("max_sanity", 50)),
        max_stamina=int(raw.get("max_stamina", 20)),
    )


def _get_npc_current_hp(npc: NPC) -> int:
    """Read current HP from stat_block_json['current_hp']; default to max_hp."""
    try:
        raw = json.loads(npc.stat_block_json or "{}")
        if not isinstance(raw, dict):
            raw = {}
    except (TypeError, ValueError):
        raw = {}

    stat_block = _parse_npc_stat_block(npc)
    return int(raw.get("current_hp", stat_block.max_hp))


def _set_npc_current_hp(npc: NPC, new_hp: int) -> None:
    """Write current_hp back to stat_block_json and update state if defeated."""
    try:
        raw = json.loads(npc.stat_block_json or "{}")
        if not isinstance(raw, dict):
            raw = {}
    except (TypeError, ValueError):
        raw = {}

    raw["current_hp"] = max(0, new_hp)
    npc.stat_block_json = json.dumps(raw, ensure_ascii=False)


def _resolve_damage_formula(formula: str, stat_block: StatBlock) -> str:
    """Substitute STR/DEX/CON/INT/WIS/CHA in formula with actual modifier values.

    Example: "1d8+STR" with STR=16 → "1d8+3"
             "1d6-DEX" with DEX=8  → "1d6+-1" (parser handles this)
    """
    stat_map = {
        "STR": get_modifier(stat_block.strength),
        "DEX": get_modifier(stat_block.dexterity),
        "CON": get_modifier(stat_block.constitution),
        "INT": get_modifier(stat_block.intelligence),
        "WIS": get_modifier(stat_block.wisdom),
        "CHA": get_modifier(stat_block.charisma),
    }
    result = formula
    for abbrev, mod_val in stat_map.items():
        if abbrev in result:
            # Replace +STR with +N or -N
            result = result.replace(f"+{abbrev}", f"+{mod_val}" if mod_val >= 0 else str(mod_val))
            result = result.replace(f"-{abbrev}", f"-{-mod_val}" if mod_val > 0 else f"+{-mod_val}")
            result = result.replace(abbrev, str(mod_val))  # bare stat (no sign)

    # Clean up double signs: "+-N" → "-N", "+N" stays
    result = re.sub(r"\+(-\d+)", r"\1", result)
    return result


# ── Async DB helpers ──────────────────────────────────────────────────────────

async def _load_pc_stat_block_and_inventory(
    s: AsyncSession, character_id: int
) -> tuple[StatBlock, list[Item]]:
    stat_block = await load_character_stats(s, character_id)
    inventory = await load_character_inventory(s, character_id)
    return stat_block, inventory


async def _get_pc_current_hp(s: AsyncSession, session_id: int, character_id: int) -> int:
    """Read current HP from CharState.stats_json for a PC."""
    char = await s.get(Character, character_id)
    state = await s.get(CharState, session_id)
    if char is None or state is None:
        return 30  # fallback
    try:
        stats = json.loads(state.stats_json)
    except Exception:
        stats = {}
    return int(stats.get("hp", char.max_hp))


def _get_equipped_weapon(inventory: list[Item], weapon_name: str | None) -> Item | None:
    """Find the equipped weapon by name, or find first weapon in inventory."""
    if weapon_name:
        for item in inventory:
            if item.name == weapon_name and item.item_type == "weapon":
                return item
        # Try fuzzy match
        for item in inventory:
            if item.item_type == "weapon" and weapon_name.lower() in item.name.lower():
                return item
        return None
    # No name given: return first weapon found
    for item in inventory:
        if item.item_type == "weapon":
            return item
    return None


def _get_equipped_armor_effects(inventory: list[Item]) -> list[ItemEffect]:
    """Collect all effects from equipped armor items."""
    effects: list[ItemEffect] = []
    for item in inventory:
        if item.item_type == "armor":
            effects.extend(item.effects)
    return effects


# ── Main async functions ──────────────────────────────────────────────────────

async def resolve_attack(
    s: AsyncSession,
    *,
    session_id: int,
    attacker_id: int,
    attacker_kind: str,               # "pc" | "npc"
    target_id: int,
    target_kind: str,                 # "pc" | "npc"
    weapon_name: str | None = None,
    rng: random.Random | None = None,
) -> AttackResult:
    """Full attack pipeline:

    1. Load attacker's stat block + find weapon (by name or first in inventory).
    2. Load target's AC (10 + DEX_mod + armor bonuses).
    3. Roll d20 + attack_mod. Hit if total >= AC. Nat-20 always hits; nat-1 always misses.
    4. If hit: roll damage formula, substitute stat placeholders, apply damage.
    5. Build & return AttackResult.

    NPC HP is tracked in stat_block_json["current_hp"].
    PC HP is tracked in CharState.stats_json["hp"].
    Defeated NPC gets state = "dead".
    """
    # ── Load attacker ────────────────────────────────────────────────────────
    if attacker_kind == "pc":
        attacker_stat_block, attacker_inventory = await _load_pc_stat_block_and_inventory(
            s, attacker_id
        )
        weapon = _get_equipped_weapon(attacker_inventory, weapon_name)
        armor_effects_attacker: list[ItemEffect] = []  # not needed for attacker
    else:
        npc_attacker = await s.get(NPC, attacker_id)
        if npc_attacker is None:
            raise ValueError(f"NPC attacker {attacker_id} not found")
        attacker_stat_block = _parse_npc_stat_block(npc_attacker)
        # NPCs carry weapon info in stat_block_json["weapon_formula"] optionally
        weapon = None  # NPC weapons handled via damage formula below

    attack_mod, attr_name = get_attack_modifier(
        attacker_stat_block, weapon, prof_bonus=_DEFAULT_PROF_BONUS
    )

    # Damage formula
    damage_formula_raw = get_damage_formula(weapon)
    # For NPCs, also check stat_block_json for a weapon_formula override
    if attacker_kind == "npc":
        npc_atk = await s.get(NPC, attacker_id)
        if npc_atk is not None:
            try:
                sb_raw = json.loads(npc_atk.stat_block_json or "{}")
                wf = sb_raw.get("weapon_formula")
                if wf:
                    damage_formula_raw = str(wf)
            except (TypeError, ValueError):
                pass

    damage_formula = _resolve_damage_formula(damage_formula_raw, attacker_stat_block)

    # ── Load target ──────────────────────────────────────────────────────────
    if target_kind == "pc":
        target_stat_block, target_inventory = await _load_pc_stat_block_and_inventory(
            s, target_id
        )
        target_armor_effects = _get_equipped_armor_effects(target_inventory)
        target_hp_before = await _get_pc_current_hp(s, session_id, target_id)
    else:
        npc_target = await s.get(NPC, target_id)
        if npc_target is None:
            raise ValueError(f"NPC target {target_id} not found")
        target_stat_block = _parse_npc_stat_block(npc_target)
        target_armor_effects = []  # NPC has no separate inventory; use stat_block AC directly
        # Check if NPC stat_block has an explicit AC override
        try:
            sb_raw = json.loads(npc_target.stat_block_json or "{}")
            explicit_ac = sb_raw.get("ac")
        except (TypeError, ValueError):
            explicit_ac = None
        target_hp_before = _get_npc_current_hp(npc_target)

    target_ac = get_armor_class(target_stat_block, target_armor_effects)
    # Apply explicit AC override for NPCs if provided
    if target_kind == "npc":
        npc_t = await s.get(NPC, target_id)
        if npc_t is not None:
            try:
                sb_raw = json.loads(npc_t.stat_block_json or "{}")
                explicit_ac = sb_raw.get("ac")
                if explicit_ac is not None:
                    target_ac = int(explicit_ac)
            except (TypeError, ValueError):
                pass

    # ── Attack roll ──────────────────────────────────────────────────────────
    # Build d20 roll formula with modifier
    mod_str = (f"+{attack_mod}" if attack_mod >= 0 else str(attack_mod))
    attack_formula = f"d20{mod_str}" if attack_mod != 0 else "d20"
    d20_result = roll("d20", rng=rng)
    raw_d20 = d20_result.rolls[0]

    # Compute total
    attack_total = raw_d20 + attack_mod

    # Build a full DiceResult for the attack roll
    attack_roll_result = DiceResult(
        rolls=d20_result.rolls,
        modifier=attack_mod,
        total=attack_total,
        formula=attack_formula,
        critical_success=d20_result.critical_success,
        critical_failure=d20_result.critical_failure,
    )

    # Determine hit: nat-20 always hits, nat-1 always misses, else total >= AC
    if d20_result.critical_success:
        hit = True
    elif d20_result.critical_failure:
        hit = False
    else:
        hit = attack_total >= target_ac

    # ── Damage ───────────────────────────────────────────────────────────────
    damage_roll_result: DiceResult | None = None
    damage_dealt = 0
    target_hp_after = target_hp_before

    if hit:
        try:
            damage_roll_result = roll(damage_formula, rng=rng)
            damage_dealt = max(0, damage_roll_result.total)
        except ValueError as exc:
            log.warning("resolve_attack: bad damage formula %r — %s", damage_formula, exc)
            damage_dealt = 0

        new_hp = max(0, target_hp_before - damage_dealt)
        target_hp_after = new_hp

        # Apply HP delta
        if target_kind == "pc":
            await apply_vital_delta(s, session_id, target_id, hp=-damage_dealt)
        else:
            npc_t = await s.get(NPC, target_id)
            if npc_t is not None:
                _set_npc_current_hp(npc_t, new_hp)
                if new_hp <= 0:
                    npc_t.state = "dead"
                    log.info("resolve_attack: NPC %d defeated", target_id)

    target_defeated = target_hp_after <= 0

    return AttackResult(
        attacker_id=attacker_id,
        target_id=target_id,
        attack_roll=attack_roll_result,
        ac=target_ac,
        hit=hit,
        damage_roll=damage_roll_result,
        damage_dealt=damage_dealt,
        target_hp_before=target_hp_before,
        target_hp_after=target_hp_after,
        target_defeated=target_defeated,
    )


async def roll_initiative(
    s: AsyncSession,
    *,
    session_id: int,
    combatants: list[tuple[str, int]],  # [("pc", char_id), ("npc", npc_id), ...]
    rng: random.Random | None = None,
) -> list[dict]:
    """Roll initiative for all combatants.

    Returns a list sorted descending by initiative_total:
        [{"kind": "pc"|"npc", "id": int, "name": str, "initiative_total": int}, ...]
    """
    results: list[dict] = []

    for kind, entity_id in combatants:
        if kind == "pc":
            try:
                stat_block = await load_character_stats(s, entity_id)
                char = await s.get(Character, entity_id)
                name = char.name if char else f"PC({entity_id})"
            except ValueError:
                log.warning("roll_initiative: PC %d not found, using defaults", entity_id)
                stat_block = StatBlock()
                name = f"PC({entity_id})"
        else:
            npc = await s.get(NPC, entity_id)
            if npc is None:
                log.warning("roll_initiative: NPC %d not found, using defaults", entity_id)
                stat_block = StatBlock()
                name = f"NPC({entity_id})"
            else:
                stat_block = _parse_npc_stat_block(npc)
                name = npc.name

        dex_mod = get_modifier(stat_block.dexterity)
        d20_result = roll("d20", rng=rng)
        initiative_total = d20_result.rolls[0] + dex_mod

        results.append({
            "kind": kind,
            "id": entity_id,
            "name": name,
            "d20": d20_result.rolls[0],
            "dex_mod": dex_mod,
            "initiative_total": initiative_total,
        })

    # Sort descending by initiative_total; tie-break by dex_mod desc
    results.sort(key=lambda x: (x["initiative_total"], x["dex_mod"]), reverse=True)
    return results
