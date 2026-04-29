import json
from typing import Any


def parse_loose_json(content: str) -> dict[str, Any]:
    """Best-effort JSON parsing for LLM-generated state tags.
    Returns {} if unrecoverable."""
    s = content.strip()
    if not s:
        return {}

    try:
        result = json.loads(s)
        return result if isinstance(result, dict) else {}
    except json.JSONDecodeError:
        pass

    try:
        result = json.loads(s.replace("'", '"'))
        return result if isinstance(result, dict) else {}
    except json.JSONDecodeError:
        pass

    start = s.find("{")
    end = s.rfind("}")
    if start >= 0 and end > start:
        candidate = s[start : end + 1]
        try:
            result = json.loads(candidate)
            return result if isinstance(result, dict) else {}
        except json.JSONDecodeError:
            pass
        try:
            result = json.loads(candidate.replace("'", '"'))
            return result if isinstance(result, dict) else {}
        except json.JSONDecodeError:
            pass

    return {}
