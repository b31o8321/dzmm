"""v0.15 Batch 2+3: mechanics tag handlers.

Handlers that wire LLM-emitted intent tags to the Python engine:

  _apply_dice_request        — GM asks Python to roll & resolve
  _apply_skill_request       — GM asks Python to perform skill check
  _apply_item_use            — GM signals player consumed/used an item
  _apply_attack              — GM triggers a single combat attack resolution
  _apply_initiative_request  — GM triggers initiative rolling for combatants

All append a record to Session.pending_resolutions_json so the next
turn's _build_key_facts can surface the results as "上回合机械结算".

Record shape:
    {
        "turn": <int>,
        "kind": "dice" | "skill" | "item" | "attack" | "initiative",
        "input": <attrs dict>,
        "result": { ... resolved ... }
    }

Capped at 100 entries to avoid unbounded growth.
"""

from __future__ import annotations

import json
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.db.models import NPC, Session as GameSession
from dzmm.engine.character import get_skill_check_modifiers
from dzmm.engine.dice import CheckResult, DiceResult, roll, skill_check

log = logging.getLogger(__name__)

# Maximum number of pending_resolutions entries to keep. Older entries are
# dropped from the front to keep the column bounded.
_MAX_PENDING_RESOLUTIONS = 100


# ── Internal helpers ──────────────────────────────────────────────────────────

async def _load_session(s: AsyncSession, session_id: int) -> GameSession | None:
    return await s.get(GameSession, session_id)


def _load_resolutions(sess: GameSession) -> list[dict]:
    try:
        raw = json.loads(sess.pending_resolutions_json or "[]")
        if not isinstance(raw, list):
            return []
        return raw
    except (TypeError, ValueError):
        return []


def _save_resolutions(sess: GameSession, records: list[dict]) -> None:
    # Cap at _MAX_PENDING_RESOLUTIONS; drop oldest entries from the front
    if len(records) > _MAX_PENDING_RESOLUTIONS:
        records = records[-_MAX_PENDING_RESOLUTIONS:]
    sess.pending_resolutions_json = json.dumps(records, ensure_ascii=False)


def _append_resolution(sess: GameSession, record: dict) -> None:
    records = _load_resolutions(sess)
    records.append(record)
    _save_resolutions(sess, records)


# ── Public handlers ───────────────────────────────────────────────────────────

async def _apply_dice_request(
    session: AsyncSession,
    session_id: int,
    attrs: dict[str, str],
    current_turn: int,
) -> dict | None:
    """Handle <dice_request formula="2d6+3" purpose="伤害" target_id="42"/>.

    Python rolls the formula and appends a record to pending_resolutions_json.
    Returns the resolved DiceResult as a dict for SSE consumption,
    or None if the formula is missing/malformed.
    """
    formula = (attrs.get("formula") or "").strip()
    purpose = (attrs.get("purpose") or "骰点").strip()

    if not formula:
        log.warning("_apply_dice_request: missing formula attr, skipping")
        return None

    try:
        result: DiceResult = roll(formula)
    except ValueError as exc:
        log.warning("_apply_dice_request: bad formula %r — %s", formula, exc)
        return None

    result_dict = {
        "formula": result.formula,
        "rolls": result.rolls,
        "modifier": result.modifier,
        "total": result.total,
        "critical_success": result.critical_success,
        "critical_failure": result.critical_failure,
        "purpose": purpose,
    }

    sess = await _load_session(session, session_id)
    if sess is None:
        log.warning("_apply_dice_request: session %d not found", session_id)
        return result_dict

    _append_resolution(sess, {
        "turn": current_turn,
        "kind": "dice",
        "input": dict(attrs),
        "result": result_dict,
    })
    return result_dict


async def _apply_skill_request(
    session: AsyncSession,
    session_id: int,
    attrs: dict[str, str],
    current_turn: int,
) -> dict | None:
    """Handle <skill_request skill="潜行" attribute="dexterity" dc="14" actor="PC"/>.

    Resolves via dice.skill_check using character stats. Appends to
    pending_resolutions_json. Returns CheckResult dict.
    Silently skips (with warning) if attribute is unknown.
    """
    skill_name = (attrs.get("skill") or "").strip()
    attribute_name = (attrs.get("attribute") or "").strip().lower()
    dc_raw = (attrs.get("dc") or "12").strip()

    if not skill_name:
        log.warning("_apply_skill_request: missing skill attr, skipping")
        return None

    # Validate DC
    try:
        dc = int(dc_raw)
    except (TypeError, ValueError):
        log.warning(
            "_apply_skill_request: invalid dc %r, defaulting to 12", dc_raw
        )
        dc = 12

    # Load session to get character_id
    sess = await _load_session(session, session_id)
    if sess is None:
        log.warning("_apply_skill_request: session %d not found", session_id)
        return None

    character_id: int = sess.character_id

    # Validate attribute name and load character stats
    _VALID_ATTRS = {
        "strength", "dexterity", "constitution",
        "intelligence", "wisdom", "charisma",
    }
    if attribute_name not in _VALID_ATTRS:
        log.warning(
            "_apply_skill_request: unknown attribute %r — skipping silently",
            attribute_name,
        )
        # Record a warning in pending_resolutions so GM sees it next turn
        _append_resolution(sess, {
            "turn": current_turn,
            "kind": "skill",
            "input": dict(attrs),
            "result": {
                "error": f"未知属性 {attribute_name!r}，跳过检定",
                "skill": skill_name,
            },
        })
        return None

    # Load attribute value and skill level; fall back gracefully
    try:
        attribute_value, skill_level = await get_skill_check_modifiers(
            session, character_id, skill_name, attribute_name
        )
    except ValueError as exc:
        log.warning("_apply_skill_request: could not load modifiers — %s", exc)
        attribute_value = 10  # default
        skill_level = 0

    result: CheckResult = skill_check(
        attribute_value=attribute_value,
        skill_level=skill_level,
        dc=dc,
    )

    result_dict = {
        "skill": skill_name,
        "attribute": attribute_name,
        "attribute_value": attribute_value,
        "skill_level": skill_level,
        "dc": dc,
        "d20": result.roll.rolls[0] if result.roll.rolls else 0,
        "modifier": result.roll.modifier,
        "total": result.roll.total,
        "succeeded": result.succeeded,
        "crit": result.crit,
        "margin": result.margin,
    }

    _append_resolution(sess, {
        "turn": current_turn,
        "kind": "skill",
        "input": dict(attrs),
        "result": result_dict,
    })
    return result_dict


async def _apply_item_use(
    session: AsyncSession,
    session_id: int,
    attrs: dict[str, str],
    current_turn: int,
) -> dict | None:
    """Handle <item_use item_name="治疗药水" actor="PC"/>.

    Calls engine.items.resolve_use_item. If item not in inventory, appends a
    "missing" warning record so next turn's key_facts can inform the GM.
    Returns the resolved dict or None.
    """
    item_name = (attrs.get("item_name") or "").strip()
    if not item_name:
        log.warning("_apply_item_use: missing item_name attr, skipping")
        return None

    sess = await _load_session(session, session_id)
    if sess is None:
        log.warning("_apply_item_use: session %d not found", session_id)
        return None

    character_id: int = sess.character_id

    # Import here to avoid circular imports at module level
    from dzmm.engine.items import resolve_use_item

    try:
        use_result = await resolve_use_item(
            session, session_id, character_id, item_name
        )
    except ValueError:
        # Item not in inventory — record warning, no-op
        log.warning(
            "_apply_item_use: item %r not found in inventory for session %d",
            item_name,
            session_id,
        )
        _append_resolution(sess, {
            "turn": current_turn,
            "kind": "item",
            "input": dict(attrs),
            "result": {
                "missing": True,
                "item_name": item_name,
                "warning": f"玩家想用「{item_name}」但背包没有这个物品",
            },
        })
        return None

    result_dict: dict = {
        "item_name": use_result["item"].name,
        "item_type": use_result["item"].item_type,
        "applied_effects": use_result["applied_effects"],
        "removed_from_inventory": use_result["removed_from_inventory"],
    }

    _append_resolution(sess, {
        "turn": current_turn,
        "kind": "item",
        "input": dict(attrs),
        "result": result_dict,
    })
    return result_dict


# ── v0.15 Batch 3: combat tag handlers ───────────────────────────────────────

async def _apply_attack(
    session: AsyncSession,
    session_id: int,
    attrs: dict[str, str],
    current_turn: int,
    rng=None,  # random.Random | None — for testing
) -> dict | None:
    """Handle <attack attacker_kind="pc" attacker_id="3" target_kind="npc"
                      target_id="5" weapon="短剑"/>.

    Resolves via engine.combat.resolve_attack. Appends a "kind: attack" record
    to pending_resolutions_json. If target is defeated and is an NPC,
    sets NPC.state = "dead".

    AttackResult record shape in pending_resolutions_json:
        {
            "turn": int,
            "kind": "attack",
            "input": {attrs},
            "result": {
                "attacker_id": int,
                "attacker_kind": str,
                "target_id": int,
                "target_kind": str,
                "d20": int,
                "attack_mod": int,
                "attack_total": int,
                "ac": int,
                "hit": bool,
                "damage_formula": str | None,
                "damage_rolls": list[int] | None,
                "damage_mod": int | None,
                "damage_total": int,
                "target_hp_before": int,
                "target_hp_after": int,
                "target_defeated": bool,
                "critical_success": bool,
                "critical_failure": bool,
            }
        }
    """
    attacker_kind = (attrs.get("attacker_kind") or "").strip().lower()
    attacker_id_raw = (attrs.get("attacker_id") or "").strip()
    target_kind = (attrs.get("target_kind") or "").strip().lower()
    target_id_raw = (attrs.get("target_id") or "").strip()
    weapon_name = (attrs.get("weapon") or "").strip() or None

    # Validate required attrs
    if attacker_kind not in ("pc", "npc"):
        log.warning("_apply_attack: invalid attacker_kind %r, skipping", attacker_kind)
        return None
    if target_kind not in ("pc", "npc"):
        log.warning("_apply_attack: invalid target_kind %r, skipping", target_kind)
        return None

    try:
        attacker_id = int(attacker_id_raw)
        target_id = int(target_id_raw)
    except (TypeError, ValueError):
        log.warning(
            "_apply_attack: invalid attacker_id %r or target_id %r, skipping",
            attacker_id_raw,
            target_id_raw,
        )
        return None

    # Import here to avoid circular imports at module level
    from dzmm.engine.combat import resolve_attack

    try:
        result = await resolve_attack(
            session,
            session_id=session_id,
            attacker_id=attacker_id,
            attacker_kind=attacker_kind,
            target_id=target_id,
            target_kind=target_kind,
            weapon_name=weapon_name,
            rng=rng,
        )
    except ValueError as exc:
        log.warning("_apply_attack: resolve_attack failed — %s", exc)
        return None

    result_dict: dict = {
        "attacker_id": result.attacker_id,
        "attacker_kind": attacker_kind,
        "target_id": result.target_id,
        "target_kind": target_kind,
        "d20": result.attack_roll.rolls[0] if result.attack_roll.rolls else 0,
        "attack_mod": result.attack_roll.modifier,
        "attack_total": result.attack_roll.total,
        "ac": result.ac,
        "hit": result.hit,
        "damage_formula": result.damage_roll.formula if result.damage_roll else None,
        "damage_rolls": result.damage_roll.rolls if result.damage_roll else None,
        "damage_mod": result.damage_roll.modifier if result.damage_roll else None,
        "damage_total": result.damage_dealt,
        "target_hp_before": result.target_hp_before,
        "target_hp_after": result.target_hp_after,
        "target_defeated": result.target_defeated,
        "critical_success": result.attack_roll.critical_success,
        "critical_failure": result.attack_roll.critical_failure,
    }

    sess = await _load_session(session, session_id)
    if sess is not None:
        _append_resolution(sess, {
            "turn": current_turn,
            "kind": "attack",
            "input": dict(attrs),
            "result": result_dict,
        })
    return result_dict


async def _apply_initiative_request(
    session: AsyncSession,
    session_id: int,
    attrs: dict[str, str],
    current_turn: int,
) -> dict | None:
    """Handle <initiative_request combatants="PC,goblin_1,goblin_2"/>.

    Resolves NPC names → (kind, id) by looking up NPCs within the session.
    "PC" (case-insensitive) maps to the session's PC character.
    Rolls initiative for each combatant. Writes sorted order to:
      - pending_resolutions_json (for next-turn key_facts display)
      - Session.combat_order_json (persists across turns)

    Returns the sorted combatant list dict or None on error.
    """
    combatants_raw = (attrs.get("combatants") or "").strip()
    if not combatants_raw:
        log.warning("_apply_initiative_request: missing combatants attr, skipping")
        return None

    sess = await _load_session(session, session_id)
    if sess is None:
        log.warning("_apply_initiative_request: session %d not found", session_id)
        return None

    pc_character_id: int = sess.character_id

    # Load all NPCs in this session for name resolution
    npc_rows = (
        await session.execute(
            select(NPC).where(NPC.session_id == session_id)
        )
    ).scalars().all()
    npc_by_name: dict[str, NPC] = {npc.name: npc for npc in npc_rows}

    # Parse combatant names
    names = [n.strip() for n in combatants_raw.split(",") if n.strip()]
    combatants: list[tuple[str, int]] = []

    for name in names:
        if name.upper() == "PC" or name == "玩家" or name == "PC角色":
            combatants.append(("pc", pc_character_id))
        elif name in npc_by_name:
            combatants.append(("npc", npc_by_name[name].id))
        else:
            # Try partial match
            matched_npc = next(
                (npc for npc_name, npc in npc_by_name.items() if name in npc_name),
                None,
            )
            if matched_npc:
                combatants.append(("npc", matched_npc.id))
            else:
                log.warning(
                    "_apply_initiative_request: combatant %r not found in session %d, skipping",
                    name,
                    session_id,
                )

    if not combatants:
        log.warning("_apply_initiative_request: no valid combatants resolved, skipping")
        return None

    from dzmm.engine.combat import roll_initiative

    order = await roll_initiative(
        session,
        session_id=session_id,
        combatants=combatants,
    )

    result_dict: dict = {
        "order": order,
        "combatant_count": len(order),
    }

    # Persist to combat_order_json
    if hasattr(sess, "combat_order_json"):
        sess.combat_order_json = json.dumps(order, ensure_ascii=False)

    _append_resolution(sess, {
        "turn": current_turn,
        "kind": "initiative",
        "input": dict(attrs),
        "result": result_dict,
    })
    return result_dict
