#!/usr/bin/env python3
"""Measure reopening a large persisted vNext run without using a model."""
from __future__ import annotations

import argparse
import json
import os
import tempfile
import time
from pathlib import Path

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from dzmm_vnext.config import Settings
from dzmm_vnext.main import create_app


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--turns", type=int, default=500)
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    if args.turns < 1:
        raise SystemExit("--turns must be positive")
    with tempfile.TemporaryDirectory(prefix="dzmm-vnext-reopen-") as temporary:
        data_dir = Path(temporary) / "data"
        os.environ["DZMM_NEXT_DATA_DIR"] = str(data_dir)
        command.upgrade(Config(str(Path(__file__).parents[1] / "backend" / "alembic.ini")), "head")
        app = create_app(Settings(data_dir=data_dir))
        with TestClient(app) as client:
            composed = client.post(
                "/api/v2/worlds:compose",
                json={
                    "request_id": "reopen-compose",
                    "world_definition": {
                        "schema_version": 1,
                        "name": "Reopen Benchmark",
                        "lore": [],
                        "locations": [
                            {"id": "harbor", "name": "Fog Harbor"},
                            {"id": "lighthouse", "name": "Old Lighthouse"},
                        ],
                        "factions": [],
                        "npcs": [],
                        "events": [],
                        "ruleset": {"id": "core"},
                    },
                    "hero": {"name": "Mira", "profile": {}},
                },
            )
            composed.raise_for_status()
            run_id = composed.json()["run_id"]
            for index in range(args.turns):
                turn = client.post(
                    f"/api/v2/runs/{run_id}/turns",
                    json={
                        "request_id": f"reopen-turn-{index + 1}",
                        "expected_revision": index,
                        "player_input": f"Benchmark action {index + 1}",
                        "commands": [{"type": "narrate", "payload": {}}],
                    },
                )
                turn.raise_for_status()
            started = time.perf_counter()
            reopened = client.get(f"/api/v2/runs/{run_id}")
            elapsed = time.perf_counter() - started
            reopened.raise_for_status()
            snapshot = reopened.json()
            if len(snapshot["turns"]) != args.turns or snapshot["state"]["revision"] != args.turns:
                raise RuntimeError("reopened run does not contain every persisted turn")
            payload = {
                "environment": "fresh temporary DZMM_NEXT_DATA_DIR; FastAPI TestClient; deterministic narrator",
                "persisted_turns": args.turns,
                "reopen_seconds": round(elapsed, 3),
                "response_bytes": len(reopened.content),
                "recovery": "reopened state revision and persisted turn count matched benchmark",
            }
    args.evidence.parent.mkdir(parents=True, exist_ok=True)
    args.evidence.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
