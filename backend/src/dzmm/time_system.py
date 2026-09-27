"""Time system (v1.4.0 M1) — the universal temporal base layer.

Worlds declare a time system (``time_system`` in the definition) and enable
the ``time`` capability. Each turn advances the clock by the model-proposed
cost (clamped by the engine); the GM payload receives the clock so narration
can reference time of day.

Clock semantics are pure functions here; persistence lives in run state.
"""

from __future__ import annotations

from typing import Any

DEFAULT_START_MINUTES = 6 * 60  # 06:00
DEFAULT_PER_TURN_MAX = 240      # 4 hours
MINUTES_PER_DAY = 1440


def initial_clock(time_system: dict[str, Any]) -> dict[str, Any]:
    """Build the clock block from the world's time_system declaration."""

    start = _bounded(time_system.get("start_minutes"), 0, 1439, DEFAULT_START_MINUTES)
    loop_at = time_system.get("loop_at_minutes")
    return {
        "now_minutes": start,
        "start_minutes": start,
        "loop_at_minutes": _bounded(loop_at, 1, MINUTES_PER_DAY, None) if loop_at is not None else None,
        "day": 1,
        "per_turn_max": _bounded(time_system.get("per_turn_max"), 1, MINUTES_PER_DAY, DEFAULT_PER_TURN_MAX),
        "unit": str(time_system.get("unit") or "分钟"),
    }


def propose_time_cost(clock: dict[str, Any], minutes: Any) -> tuple[dict[str, Any], int, list[str]]:
    """Apply a model-proposed time cost. Returns (clock, applied, notes).

    Engine adjudication: clamp to [0, per_turn_max]; non-numeric proposals fall
    back to a default 30 minutes.
    """
    per_turn_max = int(clock.get("per_turn_max") or DEFAULT_PER_TURN_MAX)
    if isinstance(minutes, bool) or not isinstance(minutes, (int, float)):
        applied = 30
        return advance_clock(clock, applied), applied, ["propose_time_cost 非数值，已按默认 30 分钟计"]
    applied = max(0, min(per_turn_max, int(minutes)))
    notes = [] if applied == int(minutes) else [f"propose_time_cost 已 clamp 至每回合上限 {per_turn_max}"]
    return advance_clock(clock, applied), applied, notes


def advance_clock(clock: dict[str, Any], minutes: int) -> dict[str, Any]:
    """Advance the clock by minutes, rolling over days at midnight."""

    now = int(clock.get("now_minutes") or 0) + int(minutes)
    day = int(clock.get("day") or 1)
    while now >= MINUTES_PER_DAY:
        now -= MINUTES_PER_DAY
        day += 1
    clock["now_minutes"] = now
    clock["day"] = day
    return clock


def tick_countdown(clock: dict[str, Any]) -> int:
    """Countdown worlds: subtract the declared per-turn tick, floored at zero.

    Returns the applied tick (0 when the clock has no countdown block).
    """

    block = clock.get("countdown")
    if not isinstance(block, dict):
        return 0
    tick = int(block.get("tick_per_turn") or 0)
    if tick <= 0:
        return 0
    clock["now_minutes"] = max(0, int(clock.get("now_minutes") or 0) - tick)
    return tick


def reached_loop_boundary(clock: dict[str, Any]) -> bool:
    """True when the clock has reached the loop boundary (if declared)."""

    loop_at = clock.get("loop_at_minutes")
    if loop_at is None:
        return False
    return int(clock.get("now_minutes") or 0) >= int(loop_at)


def _bounded(value: Any, low: int, high: int, default: int | None) -> int | None:
    try:
        number = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    return max(low, min(high, number))


def format_clock(clock: dict[str, Any]) -> str:
    minutes = int(clock.get("now_minutes") or 0)
    day = int(clock.get("day") or 1)
    unit = clock.get("unit") or "分钟"
    return f"第 {day} 天 · {minutes // 60:02d}:{minutes % 60:02d}（{unit}）"
