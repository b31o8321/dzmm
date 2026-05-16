"""
engine/dice.py — Python-owned dice rolling service for the v0.15 engine.

Provides:
  get_modifier(attribute_value)  -> int   D&D-style ability modifier
  roll(formula, *, rng=None)     -> DiceResult
  skill_check(*, attribute_value, skill_level, dc, rng=None) -> CheckResult

Formula syntax: [N]d<sides>[+/-<mod>]
  Examples: "d20", "2d6+3", "d100", "3d8-1", "1d4"

Critical flags are only set for d20 single-die rolls:
  natural 1  -> DiceResult.critical_failure = True
  natural 20 -> DiceResult.critical_success = True
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass, field


# ── Modifier ──────────────────────────────────────────────────────────────────

def get_modifier(attribute_value: int) -> int:
    """D&D-style ability modifier: (attribute_value - 10) // 2.

    attribute_value=3  → -4
    attribute_value=10 →  0
    attribute_value=11 →  0
    attribute_value=18 → +4
    attribute_value=30 → +10
    """
    return (attribute_value - 10) // 2


# ── Dice result dataclasses ────────────────────────────────────────────────────

@dataclass
class DiceResult:
    """Result of a single roll() call."""
    rolls: list[int]        # individual die values
    modifier: int           # flat +/- bonus applied after rolling
    total: int              # sum(rolls) + modifier
    formula: str            # original input string, e.g. "2d6+3"
    critical_success: bool = False   # d20 only: natural 20
    critical_failure: bool = False   # d20 only: natural 1


@dataclass
class CheckResult:
    """Result of a skill_check() call."""
    roll: DiceResult
    dc: int
    succeeded: bool
    crit: bool      # True if critical success OR critical failure
    margin: int     # roll.total - dc (positive = succeeded by N, negative = failed by N)


# ── Regex for dice formula parsing ────────────────────────────────────────────

# Matches: optional count, 'd', sides, optional modifier sign+value
_DICE_RE = re.compile(
    r"^(?P<count>[1-9]\d*)?d(?P<sides>[1-9]\d*)(?P<sign>[+-])(?P<mod>[1-9]\d*)?$",
    re.IGNORECASE,
)
# Simpler form: just NdX with no modifier (the sign+mod group is optional above,
# but let's also handle plain "d20" / "2d6" without a trailing sign.
_DICE_PLAIN_RE = re.compile(
    r"^(?P<count>[1-9]\d*)?d(?P<sides>[1-9]\d*)$",
    re.IGNORECASE,
)

_MODULE_RNG = random.Random()  # uses OS entropy; seeded from /dev/urandom


def _parse_formula(formula: str) -> tuple[int, int, int]:
    """Return (count, sides, modifier) from a dice formula string.

    Raises ValueError for unrecognised patterns.
    """
    s = formula.strip().lower()

    # Try with modifier first
    m = _DICE_RE.match(s)
    if m:
        count = int(m.group("count") or "1")
        sides = int(m.group("sides"))
        mod_val = int(m.group("mod") or "0")
        modifier = mod_val if m.group("sign") == "+" else -mod_val
        return count, sides, modifier

    # Try plain NdX
    m = _DICE_PLAIN_RE.match(s)
    if m:
        count = int(m.group("count") or "1")
        sides = int(m.group("sides"))
        return count, sides, 0

    raise ValueError(f"Unrecognised dice formula: {formula!r}")


def roll(formula: str, *, rng: random.Random | None = None) -> DiceResult:
    """Roll dice according to standard notation and return a DiceResult.

    Supported: "d20", "2d6+3", "d100", "3d8-1", "1d4", etc.
    Raises ValueError for unrecognised formulas.
    Critical success/failure flags are only set for *single d20* rolls.
    """
    r = rng or _MODULE_RNG
    count, sides, modifier = _parse_formula(formula)

    rolls = [r.randint(1, sides) for _ in range(count)]
    total = sum(rolls) + modifier

    crit_success = False
    crit_failure = False
    if sides == 20 and count == 1:
        if rolls[0] == 20:
            crit_success = True
        elif rolls[0] == 1:
            crit_failure = True

    return DiceResult(
        rolls=rolls,
        modifier=modifier,
        total=total,
        formula=formula,
        critical_success=crit_success,
        critical_failure=crit_failure,
    )


def skill_check(
    *,
    attribute_value: int,
    skill_level: int,
    dc: int,
    rng: random.Random | None = None,
) -> CheckResult:
    """Roll d20 + attr_modifier + skill_level//10 vs DC.

    Args:
        attribute_value: raw attribute (3-18 typical, 1-30 possible)
        skill_level:     0-100 CoC-style skill value
        dc:              difficulty class to meet or beat
        rng:             optional seeded Random for reproducible tests

    Critical behaviour:
        natural 1  → crit failure regardless of total (succeeded=False)
        natural 20 → crit success regardless of DC   (succeeded=True)
    """
    attr_mod = get_modifier(attribute_value)
    skill_bonus = skill_level // 10
    d20_result = roll("d20", rng=rng)

    total = d20_result.rolls[0] + attr_mod + skill_bonus
    # Rebuild DiceResult with adjusted total and modifier
    final_roll = DiceResult(
        rolls=d20_result.rolls,
        modifier=attr_mod + skill_bonus,
        total=total,
        formula=f"d20+{attr_mod}+{skill_bonus}",
        critical_success=d20_result.critical_success,
        critical_failure=d20_result.critical_failure,
    )

    # Determine success: crit overrides total
    if d20_result.critical_success:
        succeeded = True
    elif d20_result.critical_failure:
        succeeded = False
    else:
        succeeded = total >= dc

    crit = d20_result.critical_success or d20_result.critical_failure

    return CheckResult(
        roll=final_roll,
        dc=dc,
        succeeded=succeeded,
        crit=crit,
        margin=total - dc,
    )
