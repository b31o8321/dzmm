"""Tests for the world_time state_apply handler and formatter."""
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from dzmm.service.state_apply.world_time import _apply_time_advance, format_world_time_cn


# ---------------------------------------------------------------------------
# format_world_time_cn (pure-function tests — no DB needed)
# ---------------------------------------------------------------------------


def test_format_world_time_cn_basic():
    s = format_world_time_cn(json.dumps({"day": 5, "period": "dusk", "weather": "雷雨"}))
    assert "第 5 天" in s
    assert "黄昏" in s
    assert "雷雨" in s


def test_format_world_time_cn_empty_string():
    assert format_world_time_cn("") == ""


def test_format_world_time_cn_empty_dict():
    result = format_world_time_cn("{}")
    # Should have defaults: day=1, period=morning, weather=clear
    assert "第 1 天" in result
    assert "上午" in result


def test_format_world_time_cn_bad_json():
    assert format_world_time_cn("not-json") == ""


def test_format_world_time_cn_all_periods():
    period_map = {
        "dawn": "凌晨",
        "morning": "上午",
        "noon": "正午",
        "afternoon": "下午",
        "dusk": "黄昏",
        "night": "夜晚",
        "midnight": "深夜",
    }
    for eng, cn in period_map.items():
        s = format_world_time_cn(json.dumps({"day": 1, "period": eng, "weather": ""}))
        assert cn in s, f"Expected {cn} for period={eng}, got: {s}"


# ---------------------------------------------------------------------------
# _apply_time_advance (mock-based tests — no real DB)
# ---------------------------------------------------------------------------


def _make_sess(wt: dict) -> MagicMock:
    """Create a minimal fake GameSession with world_time_json set."""
    sess = MagicMock()
    sess.world_time_json = json.dumps(wt)
    return sess


def _run(coro):
    return asyncio.run(coro)


def test_apply_time_advance_4h_morning_to_noon():
    """4 hours = 1 period step; morning → noon."""
    sess = _make_sess({"day": 1, "period": "morning", "weather": "clear"})
    db = MagicMock()
    db.get = AsyncMock(return_value=sess)

    _run(_apply_time_advance(db, 1, {"hours": "4"}))

    wt = json.loads(sess.world_time_json)
    assert wt["period"] == "noon"
    assert wt["day"] == 1


def test_apply_time_advance_8h_overnight():
    """Night → midnight → dawn (2 steps), wraps day."""
    # night is index 5 in _PERIODS (length 7)
    # steps=2: (5+2)=7 → 7%7=0 (dawn); day advance = (5+2)//7 = 1
    sess = _make_sess({"day": 1, "period": "night", "weather": "clear"})
    db = MagicMock()
    db.get = AsyncMock(return_value=sess)

    _run(_apply_time_advance(db, 1, {"hours": "8"}))

    wt = json.loads(sess.world_time_json)
    assert wt["day"] == 2
    assert wt["period"] == "dawn"


def test_apply_time_advance_explicit_day_and_weather():
    sess = _make_sess({"day": 1, "period": "morning", "weather": "clear"})
    db = MagicMock()
    db.get = AsyncMock(return_value=sess)

    _run(_apply_time_advance(db, 1, {"day": "15", "weather": "雪"}))

    wt = json.loads(sess.world_time_json)
    assert wt["day"] == 15
    assert wt["weather"] == "雪"
    # period unchanged
    assert wt["period"] == "morning"


def test_apply_time_advance_explicit_period_override():
    sess = _make_sess({"day": 3, "period": "morning", "weather": "sunny"})
    db = MagicMock()
    db.get = AsyncMock(return_value=sess)

    _run(_apply_time_advance(db, 1, {"period": "midnight"}))

    wt = json.loads(sess.world_time_json)
    assert wt["period"] == "midnight"
    assert wt["day"] == 3  # day not changed by period-only override


def test_apply_time_advance_zero_hours_noop():
    """0 hours should not advance period at all."""
    sess = _make_sess({"day": 1, "period": "morning", "weather": "clear"})
    db = MagicMock()
    db.get = AsyncMock(return_value=sess)

    _run(_apply_time_advance(db, 1, {"hours": "0"}))

    wt = json.loads(sess.world_time_json)
    assert wt["period"] == "morning"
    assert wt["day"] == 1


def test_apply_time_advance_no_sess():
    """If session not found, should silently no-op."""
    db = MagicMock()
    db.get = AsyncMock(return_value=None)

    # Should not raise
    _run(_apply_time_advance(db, 999, {"hours": "4"}))


def test_apply_time_advance_weather_clamped_to_30():
    """weather is clamped to 30 chars."""
    long_weather = "A" * 50
    sess = _make_sess({"day": 1, "period": "morning", "weather": "clear"})
    db = MagicMock()
    db.get = AsyncMock(return_value=sess)

    _run(_apply_time_advance(db, 1, {"weather": long_weather}))

    wt = json.loads(sess.world_time_json)
    assert len(wt["weather"]) == 30


def test_apply_time_advance_day_minimum_1():
    """day cannot go below 1."""
    sess = _make_sess({"day": 1, "period": "morning", "weather": "clear"})
    db = MagicMock()
    db.get = AsyncMock(return_value=sess)

    _run(_apply_time_advance(db, 1, {"day": "0"}))

    wt = json.loads(sess.world_time_json)
    assert wt["day"] == 1
