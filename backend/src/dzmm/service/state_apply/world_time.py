"""<time_advance hours="N" period="..." weather="..." day="N"/> handler.

Periods cycle: dawn → morning → noon → afternoon → dusk → night → midnight → dawn.
Each period is roughly 4 hours; 24h = 6 period steps with midnight as a wrap point.
"""
import json

from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.db.models import Session as GameSession

_PERIODS = ["dawn", "morning", "noon", "afternoon", "dusk", "night", "midnight"]
_PERIODS_CN = {
    "dawn": "凌晨",
    "morning": "上午",
    "noon": "正午",
    "afternoon": "下午",
    "dusk": "黄昏",
    "night": "夜晚",
    "midnight": "深夜",
}


def _read_world_time(sess: GameSession) -> dict:
    try:
        wt = json.loads(sess.world_time_json or "{}")
        if not isinstance(wt, dict):
            wt = {}
    except (TypeError, ValueError):
        wt = {}
    wt.setdefault("day", 1)
    wt.setdefault("period", "morning")
    wt.setdefault("weather", "clear")
    return wt


async def _apply_time_advance(
    session: AsyncSession,
    session_id: int,
    attrs: dict,
) -> None:
    sess = await session.get(GameSession, session_id)
    if sess is None:
        return
    wt = _read_world_time(sess)

    # hours: roughly 4h per period step
    h = attrs.get("hours")
    if h is not None:
        try:
            hours = max(0, int(h))
            steps = hours // 4
            if steps > 0:
                cur_idx = _PERIODS.index(wt["period"]) if wt["period"] in _PERIODS else 1
                new_idx = (cur_idx + steps) % len(_PERIODS)
                wt["period"] = _PERIODS[new_idx]
                # Day rolls over each full cycle past midnight (wrapping)
                wt["day"] = int(wt["day"]) + (cur_idx + steps) // len(_PERIODS)
        except ValueError:
            pass

    # Explicit period override
    if (p := attrs.get("period")) and p in _PERIODS:
        wt["period"] = p

    # Weather (free-form short phrase)
    if w := attrs.get("weather"):
        wt["weather"] = str(w)[:30]

    # Explicit day override
    if (d := attrs.get("day")) is not None:
        try:
            wt["day"] = max(1, int(d))
        except ValueError:
            pass

    sess.world_time_json = json.dumps(wt, ensure_ascii=False)


def format_world_time_cn(wt_json: str) -> str:
    """Render world_time as a one-line Chinese string for prompt + UI display."""
    if not wt_json or not wt_json.strip():
        return ""
    try:
        wt = json.loads(wt_json)
    except (TypeError, ValueError):
        return ""
    if not isinstance(wt, dict):
        return ""
    day = wt.get("day", 1)
    period = wt.get("period", "morning")
    weather = wt.get("weather", "")
    period_cn = _PERIODS_CN.get(period, period)
    parts = [f"第 {day} 天", period_cn]
    if weather:
        parts.append(weather)
    return " · ".join(parts)
