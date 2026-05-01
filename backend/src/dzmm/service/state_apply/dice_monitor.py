"""Dice randomness monitoring (v0.2.2). Detects when GM emits the same d20
value in consecutive rolls — a strong signal the model is stuck on a
deterministic value (real playtest saw d20=9 repeated 8 times). When detected,
log a warning and inject a hint into next turn's key_facts."""
import json
import re

_D20_RE = re.compile(r"d20\s*=\s*(\d{1,2})", re.IGNORECASE)


def extract_d20_value(content: str) -> int | None:
    """Pull the d20 number out of a <dice> body like 'd20=15，成功'."""
    m = _D20_RE.search(content or "")
    if not m:
        return None
    try:
        v = int(m.group(1))
        return v if 1 <= v <= 20 else None
    except ValueError:
        return None


def detect_stuck_dice(recent_d20_values: list[int], min_streak: int = 2) -> int | None:
    """Return the value that's been emitted N+ times in a row, or None.

    `min_streak=2` means: trigger when the current value has been preceded by
    ≥2 same values (so a streak of 3+ in a row triggers).
    """
    if len(recent_d20_values) < min_streak + 1:
        return None
    last = recent_d20_values[-1]
    streak = 1
    for v in reversed(recent_d20_values[:-1]):
        if v == last:
            streak += 1
        else:
            break
    return last if streak > min_streak else None


def extract_d20_values_from_messages(messages: list) -> list[int]:
    """Walk a list of Message rows (newest last) and pull out every d20 value
    from their events_json `dice` entries. Tolerates malformed rows.

    Each message row is expected to expose an `events_json` attribute (string
    of JSON) — typical for the persisted assistant turn. Format::

        [{"type": "dice", "payload": {...}, "content": "d20=9，失败"}, ...]
    """
    out: list[int] = []
    for msg in messages:
        raw = getattr(msg, "events_json", None) or ""
        if not raw:
            continue
        try:
            events = json.loads(raw)
        except (TypeError, ValueError):
            continue
        if not isinstance(events, list):
            continue
        for ev in events:
            if not isinstance(ev, dict):
                continue
            if (ev.get("type") or "").lower() != "dice":
                continue
            # Try the body content first (most common), then fall back to
            # any payload attrs that might encode the value.
            v = extract_d20_value(ev.get("content") or "")
            if v is None:
                payload = ev.get("payload") or {}
                if isinstance(payload, dict):
                    # Some emitters put it in an attr like d20="9"
                    for key in ("d20", "value", "result"):
                        cand = payload.get(key)
                        if cand is not None:
                            v = extract_d20_value(f"d20={cand}")
                            if v is not None:
                                break
            if v is not None:
                out.append(v)
    return out


def build_stuck_warning(values: list[int], stuck_value: int) -> str:
    """Format the GM-only warning block that gets injected into key_facts."""
    tail = values[-3:] if len(values) >= 3 else values
    seq = ", ".join(str(v) for v in tail)
    return (
        "## ⚠️ Dice 警告（仅 GM 看）\n"
        f"你最近 {len(tail)} 次 dice 都是 d20={stuck_value}（序列: [{seq}]）。"
        "这显然不是真随机。下次必须输出不同的 d20 值"
        "（用本回合 PC 输入的字符数 mod 20 + 1 作为简单伪随机源）。"
    )
