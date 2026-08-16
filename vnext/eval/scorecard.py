from __future__ import annotations

import json
import sys
from pathlib import Path


DIMENSIONS = {
    "domain_lifecycle": 15,
    "game_loop": 20,
    "creation_content": 15,
    "model_stream": 10,
    "desktop_ux": 10,
    "mobile_recovery": 10,
    "long_play_performance": 10,
    "engineering_release": 10,
}


def score(evidence: dict[str, object]) -> dict[str, object]:
    scores = evidence.get("scores")
    if not isinstance(scores, dict) or set(scores) != set(DIMENSIONS):
        raise ValueError("scores must contain every vNext maturity dimension exactly once")
    values: dict[str, int] = {}
    for name in DIMENSIONS:
        value = scores[name]
        if not isinstance(value, int) or not 0 <= value <= 100:
            raise ValueError(f"{name} must be an integer from 0 to 100")
        values[name] = value
    weighted = sum(values[name] * weight for name, weight in DIMENSIONS.items()) / 100
    return {
        "scores": values,
        "weighted_score": round(weighted, 2),
        "all_p0_at_least_80": all(value >= 80 for value in values.values()),
        "release_ready": weighted >= 85 and all(value >= 80 for value in values.values()),
    }


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: scorecard.py EVIDENCE.json", file=sys.stderr)
        return 2
    result = score(json.loads(Path(argv[1]).read_text(encoding="utf-8")))
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
