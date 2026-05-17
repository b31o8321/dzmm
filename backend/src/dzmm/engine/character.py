"""
engine/character.py — Character stat/skill/inventory helpers for the v0.15 engine.

All functions are async and accept an open AsyncSession.
They read Character and CharState rows and return structured values.

Public API:
  load_character_stats(s, character_id)           -> StatBlock
  load_character_skills(s, character_id)          -> dict[str, int]
  load_character_inventory(s, character_id)       -> list[Item]
  get_skill_check_modifiers(s, character_id, skill_name, attribute_name)
                                                  -> tuple[int, int]
  apply_vital_delta(s, session_id, character_id, *, hp, sanity, stamina)
                                                  -> dict
  level_up(s, character_id)
                                                  -> dict | None
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.db.models import Character, CharState
from dzmm.engine.schema import Item, StatBlock, parse_items, parse_skills

logger = logging.getLogger(__name__)


async def load_character_stats(s: AsyncSession, character_id: int) -> StatBlock:
    """Load a Character row and return a StatBlock pydantic model.

    Reads the six v0.15 attribute columns plus the three max-vital columns.
    Raises ValueError if the character is not found.
    """
    char = await s.get(Character, character_id)
    if char is None:
        raise ValueError(f"Character {character_id} not found")

    return StatBlock(
        strength=char.strength,
        dexterity=char.dexterity,
        constitution=char.constitution,
        intelligence=char.intelligence,
        wisdom=char.wisdom,
        charisma=char.charisma,
        max_hp=char.max_hp,
        max_sanity=char.max_sanity,
        max_stamina=char.max_stamina,
    )


async def load_character_skills(s: AsyncSession, character_id: int) -> dict[str, int]:
    """Load the skills_json column from Character and return a dict.

    Returns {} if the character is not found or the JSON is malformed.
    """
    char = await s.get(Character, character_id)
    if char is None:
        logger.warning("load_character_skills: character %d not found", character_id)
        return {}
    return parse_skills(char.skills_json)


async def load_character_inventory(s: AsyncSession, character_id: int) -> list[Item]:
    """Load the inventory_json column from Character and return a list[Item].

    Returns [] if the character is not found or the JSON is malformed.
    """
    char = await s.get(Character, character_id)
    if char is None:
        logger.warning("load_character_inventory: character %d not found", character_id)
        return []
    return parse_items(char.inventory_json)


async def get_skill_check_modifiers(
    s: AsyncSession,
    character_id: int,
    skill_name: str,
    attribute_name: str,
) -> tuple[int, int]:
    """Return (attribute_value, skill_level) for use with dice.skill_check().

    attribute_name must be one of: strength, dexterity, constitution,
    intelligence, wisdom, charisma.
    skill_level defaults to 0 if the skill is not found.
    Raises ValueError for unknown attribute_name or missing character.
    """
    _VALID_ATTRS = {
        "strength", "dexterity", "constitution",
        "intelligence", "wisdom", "charisma",
    }
    if attribute_name not in _VALID_ATTRS:
        raise ValueError(
            f"Unknown attribute {attribute_name!r}. "
            f"Must be one of: {sorted(_VALID_ATTRS)}"
        )

    char = await s.get(Character, character_id)
    if char is None:
        raise ValueError(f"Character {character_id} not found")

    attribute_value: int = getattr(char, attribute_name)
    skills = parse_skills(char.skills_json)
    skill_level = skills.get(skill_name, 0)

    return attribute_value, skill_level


async def apply_vital_delta(
    s: AsyncSession,
    session_id: int,
    character_id: int,
    *,
    hp: int = 0,
    sanity: int = 0,
    stamina: int = 0,
) -> dict:
    """Apply clamped deltas to CharState vitals and persist.

    Values are clamped to [0, max_<vital>] from the Character row.
    Returns a dict with the new values: {"hp": N, "sanity": N, "stamina": N}.

    Raises ValueError if character or CharState is not found.
    """
    char = await s.get(Character, character_id)
    if char is None:
        raise ValueError(f"Character {character_id} not found")

    state = await s.get(CharState, session_id)
    if state is None:
        raise ValueError(f"CharState for session {session_id} not found")

    # Parse current vitals from stats_json (legacy storage field)
    try:
        stats = json.loads(state.stats_json)
    except Exception:
        stats = {}

    # Read current values; default to max if key missing (fresh state)
    cur_hp = int(stats.get("hp", char.max_hp))
    cur_sanity = int(stats.get("sanity", char.max_sanity))
    cur_stamina = int(state.stamina)  # v0.15 dedicated column

    # Apply clamped deltas
    new_hp = max(0, min(char.max_hp, cur_hp + hp))
    new_sanity = max(0, min(char.max_sanity, cur_sanity + sanity))
    new_stamina = max(0, min(char.max_stamina, cur_stamina + stamina))

    # Persist back to stats_json (HP + sanity kept there for legacy compat)
    stats["hp"] = new_hp
    stats["sanity"] = new_sanity
    state.stats_json = json.dumps(stats, ensure_ascii=False)

    # Persist stamina to dedicated column
    state.stamina = new_stamina
    state.updated_at = datetime.now(UTC).replace(tzinfo=None)

    return {"hp": new_hp, "sanity": new_sanity, "stamina": new_stamina}


# ── Skill → attribute mapping (used by level_up heuristic) ───────────────────
# Skills listed here map to their governing attribute.
# Unlisted skills default to "intelligence".
_SKILL_TO_ATTR: dict[str, str] = {
    # wisdom
    "调查": "wisdom",
    "察言观色": "wisdom",
    "搜索": "wisdom",
    # dexterity
    "潜行": "dexterity",
    "开锁": "dexterity",
    "闪避": "dexterity",
    # strength
    "近战": "strength",
    "攻击": "strength",
    # charisma
    "说服": "charisma",
    "魅惑": "charisma",
    # intelligence
    "推理": "intelligence",
    "破解": "intelligence",
    "学问": "intelligence",
    # constitution
    "体力": "constitution",
    "坚持": "constitution",
}

_ALL_ATTRS = ("strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma")


async def level_up(s: AsyncSession, character_id: int) -> dict | None:
    """Check if Character should level up; apply +1 level / +1 attribute / +5 skill.

    Returns {"level": new_level, "attribute_raised": str, "skill_raised": str}
    or None if not enough XP.  Idempotent: can be called every turn.
    Threshold formula: required_xp = level * 100.
    Loops if multiple levels can be granted at once.

    Attribute heuristic (in priority order):
      1. Attribute that governs the highest-level skill (ties broken by
         attribute name alphabetically for determinism).
      2. If no skills, pick the attribute with the highest current value
         (favours what the PC is already good at).
      3. Fallback: "intelligence".

    Skill raised: the highest-level skill (ties broken by name). +5, capped at 100.
    """
    char = await s.get(Character, character_id)
    if char is None:
        raise ValueError(f"Character {character_id} not found")

    # Determine if at least one level-up is possible
    if char.xp < char.level * 100:
        return None

    old_level = char.level
    last_result: dict | None = None

    while char.xp >= char.level * 100:
        required = char.level * 100
        char.xp -= required

        # ── 1. Pick skill to raise ────────────────────────────────────────
        skills = parse_skills(char.skills_json)
        if skills:
            # Highest-level skill; ties broken alphabetically (deterministic)
            top_skill_name = max(skills, key=lambda k: (skills[k], k))
            top_skill_level = skills[top_skill_name]
        else:
            top_skill_name = ""
            top_skill_level = 0

        # ── 2. Pick attribute to raise ────────────────────────────────────
        if top_skill_name:
            attr_to_raise = _SKILL_TO_ATTR.get(top_skill_name, "intelligence")
        else:
            # No skills → pick attribute with highest current value (ties by name)
            attr_to_raise = max(
                _ALL_ATTRS,
                key=lambda a: (getattr(char, a), a),
            )

        # ── 3. Apply changes ──────────────────────────────────────────────
        char.level += 1
        setattr(char, attr_to_raise, getattr(char, attr_to_raise) + 1)

        if top_skill_name:
            skills[top_skill_name] = min(100, top_skill_level + 5)
            char.skills_json = json.dumps(skills, ensure_ascii=False)

        last_result = {
            "level": char.level,
            "attribute_raised": attr_to_raise,
            "skill_raised": top_skill_name,
        }
        logger.info(
            "level_up: character %d → Lv %d (+%s +5 %s)",
            character_id, char.level, attr_to_raise, top_skill_name,
        )

    # Store one-shot announcement so _build_key_facts can surface it next turn.
    # We record old_level → new_level so the GM message shows the delta clearly.
    if last_result is not None:
        char.level_up_pending_json = json.dumps(
            {
                "old_level": old_level,
                "new_level": char.level,
                "attribute_raised": last_result["attribute_raised"],
                "skill_raised": last_result["skill_raised"],
            },
            ensure_ascii=False,
        )

    # Flush so the changes are visible to the same session's subsequent reads
    # (e.g. refresh() or nested queries). Caller is still responsible for commit.
    await s.flush()

    return last_result
