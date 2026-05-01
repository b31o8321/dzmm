"""PC name drift repair (v0.12).

GM occasionally drifts and starts referring to PC by a different name after a
few turns. We post-process the streamed output before persisting / re-injecting
into key_facts so future turns see the canonical name.

Conservative — only rewrites self-introduction patterns ("我叫 X" / "我是 X" /
"在下 X" / "鄙人 X" / "叫我 X" / "本人是 X" / "敝人 X") outside of
``<say speaker="...">`` blocks. NPC dialogue inside `<say>` is intentionally
left alone — an NPC named "林峰" really should self-introduce as "林峰".

Extracted from `service/game.py` (v0.1.6 refactor).
"""
import re

# ([一-鿿A-Za-z0-9·_]) accepts hanzi, latin, digits and the middle-dot used in
# transliterated names ("艾米丽·斯通"). Length 1-8 covers everything from "我"
# (rare 1-char nicknames) through 8-char transliterations.
_NAME_PATTERNS = [
    re.compile(
        r"(我叫|我是|在下|鄙人|叫我|本人是?|敝人)([一-鿿A-Za-z0-9·_]{1,8})"
    ),
]

_SAY_BLOCK_RE = re.compile(r"<say\b[^>]*>.*?</say>", flags=re.DOTALL)


def _repair_pc_name(content: str, character_name: str) -> tuple[str, int]:
    """Detect and fix PC name drift in GM output.

    Returns ``(repaired_text, num_fixes)``. ``num_fixes == 0`` when content is
    already canonical — caller can short-circuit logging in that case.
    """
    if not character_name or not content:
        return content, 0

    fixes = 0

    # Mask <say>...</say> blocks first so we never rewrite NPC dialogue.
    say_blocks: list[str] = []

    def _mask(m: re.Match[str]) -> str:
        say_blocks.append(m.group(0))
        return f"\x00SAY{len(say_blocks) - 1}\x00"

    masked = _SAY_BLOCK_RE.sub(_mask, content)

    for pat in _NAME_PATTERNS:
        def _fix(m: re.Match[str]) -> str:
            nonlocal fixes
            verb, name = m.group(1), m.group(2)
            # Only rewrite when the name differs AND is at least 2 chars
            # (avoids replacing pronouns / 1-char tails). Also no-op when the
            # captured name is already the PC name.
            if name == character_name:
                return m.group(0)
            if len(name) < 2:
                return m.group(0)
            fixes += 1
            return f"{verb}{character_name}"

        masked = pat.sub(_fix, masked)

    # Restore say blocks.
    for i, block in enumerate(say_blocks):
        masked = masked.replace(f"\x00SAY{i}\x00", block)

    return masked, fixes
