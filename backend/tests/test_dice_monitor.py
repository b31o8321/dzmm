"""v0.2.2 P1.6 — dice randomness monitoring tests.

Detects when the GM emits the same d20 value 3+ turns in a row (real playtest
saw d20=9 repeated 8 times) so we can inject a corrective hint into the next
turn's key_facts.
"""
import json

from dzmm.service.state_apply.dice_monitor import (
    build_stuck_warning,
    detect_stuck_dice,
    extract_d20_value,
    extract_d20_values_from_messages,
)


def test_extract_d20_basic():
    assert extract_d20_value("d20=15, 成功") == 15
    assert extract_d20_value("d20 = 1, 大失败") == 1
    assert extract_d20_value("无骰子") is None


def test_extract_d20_out_of_range():
    assert extract_d20_value("d20=21") is None
    assert extract_d20_value("d20=0") is None


def test_extract_d20_chinese_punct():
    """Real GM output uses CJK fullwidth comma after the value."""
    assert extract_d20_value("d20=9，失败") == 9
    assert extract_d20_value("d20=12，成功") == 12


def test_extract_d20_uppercase():
    assert extract_d20_value("D20=7，失败") == 7


def test_extract_d20_none_for_empty():
    assert extract_d20_value("") is None
    assert extract_d20_value(None) is None


def test_detect_stuck_three_same():
    assert detect_stuck_dice([5, 9, 9, 9]) == 9


def test_detect_no_stuck_when_varied():
    assert detect_stuck_dice([9, 12, 9, 15]) is None


def test_detect_stuck_min_streak_param():
    assert detect_stuck_dice([5, 5], min_streak=1) == 5
    assert detect_stuck_dice([5, 5], min_streak=2) is None


def test_detect_stuck_too_few_values():
    """min_streak=2 default needs ≥3 values to possibly trigger."""
    assert detect_stuck_dice([]) is None
    assert detect_stuck_dice([9]) is None
    assert detect_stuck_dice([9, 9]) is None


def test_detect_stuck_long_streak():
    """8 same in a row should trigger trivially (real playtest scenario)."""
    assert detect_stuck_dice([9] * 8) == 9


def test_detect_stuck_breaks_when_last_is_different():
    """Streak only counts trailing same-values."""
    assert detect_stuck_dice([9, 9, 9, 12]) is None


class _FakeMsg:
    def __init__(self, events_json: str):
        self.events_json = events_json


def test_extract_from_messages_basic():
    msg1 = _FakeMsg(json.dumps([
        {"type": "dice", "payload": {"skill": "洞察", "target": "12"},
         "content": "d20=9，失败"},
    ]))
    msg2 = _FakeMsg(json.dumps([
        {"type": "narrative", "content": "..."},
        {"type": "dice", "payload": {}, "content": "d20=15，成功"},
    ]))
    assert extract_d20_values_from_messages([msg1, msg2]) == [9, 15]


def test_extract_from_messages_tolerates_malformed():
    msgs = [
        _FakeMsg(""),                      # empty
        _FakeMsg("not json"),              # bad json
        _FakeMsg(json.dumps({"x": 1})),    # not a list
        _FakeMsg(json.dumps([{"type": "dice"}])),  # no content
        _FakeMsg(json.dumps([
            {"type": "dice", "content": "d20=11"}
        ])),
    ]
    assert extract_d20_values_from_messages(msgs) == [11]


def test_extract_from_messages_payload_fallback():
    """If content lacks d20, payload attrs may carry the value."""
    msg = _FakeMsg(json.dumps([
        {"type": "dice", "payload": {"d20": "8"}, "content": ""},
    ]))
    assert extract_d20_values_from_messages([msg]) == [8]


def test_build_stuck_warning_format():
    text = build_stuck_warning([9, 9, 9], 9)
    assert "Dice 警告" in text
    assert "d20=9" in text
    assert "9, 9, 9" in text
    assert "字符数" in text  # mentions the simple pseudo-random suggestion
