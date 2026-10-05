"""Tolerant JSON repair for weak-model world drafts.

qwen-family 7B drafts drift in parse-breaking ways that plain ``json.loads``
cannot absorb (all captured from real device/emulator play sessions):

1. Missing array closer before a sibling key —
   ``"story": ["第一章…", "character_cards": […]`` (no ``]``).
2. Values opening with a CJK quote — ``"name": “未来”信箱"`` — the parser
   does not treat ``“`` as a string delimiter.

Both are delimiter-level damage; a conservative repair never touches value
content, only swaps/inserts quote glyphs and array closers.
"""

from __future__ import annotations

import json
import re
from typing import Any

_MAX_REPAIR_PASSES = 6


def _bracket_stack(text: str, upto: int | None = None) -> list[tuple[str, int]]:
    """Return the open-bracket stack for text[:upto], skipping strings."""

    stack: list[tuple[str, int]] = []
    in_str = False
    esc = False
    end = len(text) if upto is None else min(upto, len(text))
    for i in range(end):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "{[":
            stack.append((ch, i))
        elif ch in "}]" and stack:
            stack.pop()
    return stack


def _close_missing_array(text: str, error: json.JSONDecodeError) -> str | None:
    """Insert ``]`` before a sibling key that starts while an array is open.

    Failure signature: ``Expecting ',' delimiter`` pointing at ``"key":``
    right after an array item — the model forgot the array closer.
    """

    if error.msg != "Expecting ',' delimiter":
        return None
    line_start = text.rfind("\n", 0, error.pos) + 1
    line = text[line_start : error.pos + 1]
    key_match = re.search(r'"[^"]*"(?=\s*:)', line)
    if not key_match:
        return None
    key_start = line_start + key_match.start()
    stack = _bracket_stack(text, key_start)
    if not stack or stack[-1][0] != "[":
        return None  # not inside an array; not this repair
    # Insert the closer right before the key; if a comma separates the
    # previous item, place ``]`` before that comma to avoid a trailing comma.
    before = text[:key_start].rstrip()
    if before.endswith(","):
        comma = before.rfind(",")
        return text[:comma] + "]" + text[comma:]
    return text[:key_start] + "], " + text[key_start:]


def _fix_cjk_quoted_value(text: str, error: json.JSONDecodeError) -> str | None:
    """Promote a CJK open-quote starting a value into a JSON string delimiter.

    Failure signature: ``Expecting value`` where the nearest preceding
    non-space glyph is ``“`` — the model used ``“…”`` as value quotes.
    Only the delimiters change; inner CJK close-quotes are legal content.
    """

    if error.msg != "Expecting value":
        return None
    # error.pos 指向 ':' 后（可能隔着空白）；向后跳过空白定位 CJK 开引号
    probe = error.pos
    while probe < len(text) and text[probe] in " \t":
        probe += 1
    if probe < len(text) and text[probe] == "“":
        return text[:probe] + '"' + text[probe + 1 :]
    return None


def repair_json_text(text: str) -> tuple[Any, bool]:
    """Parse ``text``, applying conservative structural repairs if needed.

    Returns ``(value, repaired)``. Raises ``json.JSONDecodeError`` when no
    conservative repair produces valid JSON.
    """

    try:
        return json.loads(text), False
    except json.JSONDecodeError as first_error:
        current = text
        last_error: json.JSONDecodeError = first_error
        for _ in range(_MAX_REPAIR_PASSES):
            fixed = _close_missing_array(current, last_error)
            if fixed is None:
                fixed = _fix_cjk_quoted_value(current, last_error)
            if fixed is None or fixed == current:
                break
            try:
                return json.loads(fixed), True
            except json.JSONDecodeError as next_error:
                current = fixed
                last_error = next_error
        raise last_error
