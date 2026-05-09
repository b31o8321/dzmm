import json
import re
from typing import Any

# LLMs frequently write "+2" or "+10" as JSON values (Python-style but invalid
# JSON). Strip leading "+" from numeric values before parsing.
_PLUS_NUM_RE = re.compile(r'(?<=[:, \[{])\+(\d)')


def _strip_plus_prefix(s: str) -> str:
    """Replace "+N" with "N" in JSON strings so json.loads accepts them."""
    return _PLUS_NUM_RE.sub(r'\1', s)


def _try_loads(s: str) -> dict | None:
    """Try json.loads, returning None on failure."""
    try:
        result = json.loads(s)
        return result if isinstance(result, dict) else None
    except (json.JSONDecodeError, ValueError):
        return None


def parse_loose_json(content: str) -> dict[str, Any]:
    """Best-effort JSON parsing for LLM-generated state tags.
    Returns {} if unrecoverable.

    Handles common LLM quirks:
    - Single quotes instead of double quotes
    - "+N" positive-number literals (invalid JSON, valid Python)
    - Leading/trailing non-JSON text wrapping a {...} block
    """
    s = content.strip()
    if not s:
        return {}

    # Attempt 1: strict parse
    if (r := _try_loads(s)) is not None:
        return r

    # Attempt 2: strip +prefix from numbers (most common LLM deviation)
    cleaned = _strip_plus_prefix(s)
    if (r := _try_loads(cleaned)) is not None:
        return r

    # Attempt 3: single-quote fix
    sq = s.replace("'", '"')
    if (r := _try_loads(sq)) is not None:
        return r

    # Attempt 4: single-quote + strip +prefix
    sq_cleaned = _strip_plus_prefix(sq)
    if (r := _try_loads(sq_cleaned)) is not None:
        return r

    # Attempt 5: extract first {...} block and retry with all fixes
    start = s.find("{")
    end = s.rfind("}")
    if start >= 0 and end > start:
        candidate = s[start : end + 1]
        for variant in (
            candidate,
            _strip_plus_prefix(candidate),
            candidate.replace("'", '"'),
            _strip_plus_prefix(candidate.replace("'", '"')),
        ):
            if (r := _try_loads(variant)) is not None:
                return r

    return {}
