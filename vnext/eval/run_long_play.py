#!/usr/bin/env python3
"""Run a real-model vNext long-play check against an isolated temporary database."""
from __future__ import annotations

import argparse
import json
import os
import statistics
import tempfile
import time
from pathlib import Path

from fastapi.testclient import TestClient
from alembic import command
from alembic.config import Config

from dzmm.config import Settings
from dzmm.main import create_app


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    result.add_argument("--base-url", required=True, help="OpenAI-compatible /v1 root")
    result.add_argument("--model", required=True)
    result.add_argument("--turns", type=int, default=30)
    result.add_argument("--max-retries", type=int, default=2)
    result.add_argument("--evidence", type=Path, required=True)
    return result


def main() -> None:
    args = parser().parse_args()
    if args.turns < 1:
        raise SystemExit("--turns must be positive")
    if args.max_retries < 0:
        raise SystemExit("--max-retries must not be negative")
    latencies: list[float] = []
    retries = 0
    with tempfile.TemporaryDirectory(prefix="dzmm-long-play-") as temporary:
        data_dir = Path(temporary) / "data"
        os.environ["DZMM_DATA_DIR"] = str(data_dir)
        command.upgrade(Config(str(Path(__file__).parents[1] / "backend" / "alembic.ini")), "head")
        app = create_app(Settings(data_dir=data_dir))
        with TestClient(app, raise_server_exceptions=False) as client:
            profile = client.post(
                "/api/v2/model-profiles",
                json={
                    "name": "long-play-baseline",
                    "provider_type": "lm_studio",
                    "base_url": args.base_url,
                    "model_name": args.model,
                },
            )
            profile.raise_for_status()
            composed = client.post(
                "/api/v2/worlds:compose",
                json={
                    "request_id": "long-play-compose",
                    "model_profile_id": profile.json()["id"],
                    "world_definition": {
                        "schema_version": 3,
                        "name": "Long-play Fog Harbor",
                        "lorebook": {"entries": []},
                        "character_cards": [],
                        "locations": [
                            {"id": "harbor", "name": "Fog Harbor"},
                            {"id": "lighthouse", "name": "Old Lighthouse"},
                        ],
                        "factions": [],
                        "npcs": [],
                        "events": [],
                        "resources": [],
                        "ruleset": {"id": "trpg", "enabled_capabilities": ["trpg", "resources"]},
                        "story": {
                            "chapters": [],
                            "flags": [],
                            "relationships": [],
                            "relationship_events": [],
                            "routes": [],
                            "endings": [],
                        },
                    },
                    "hero": {"name": "Mira", "profile": {}},
                },
            )
            composed.raise_for_status()
            run_id = composed.json()["run_id"]
            for index in range(args.turns):
                destination = "lighthouse" if index % 2 == 0 else "harbor"
                request = {
                    "request_id": f"long-play-turn-{index + 1}",
                    "expected_revision": index,
                    "player_input": f"第 {index + 1} 回合，我谨慎前往 {destination}。",
                    "commands": [
                        {"type": "move", "payload": {"location_id": destination}},
                        {"type": "narrate", "payload": {}},
                    ],
                }
                for attempt in range(args.max_retries + 1):
                    started = time.perf_counter()
                    response = client.post(f"/api/v2/runs/{run_id}/turns:stream", json=request)
                    latencies.append(time.perf_counter() - started)
                    response.raise_for_status()
                    if "event: turn_completed" in response.text:
                        break
                    recovered = client.get(f"/api/v2/runs/{run_id}")
                    recovered.raise_for_status()
                    if recovered.json()["state"]["revision"] != index:
                        raise RuntimeError("failed stream changed RunState before retry")
                    if attempt == args.max_retries:
                        raise RuntimeError(f"turn {index + 1} did not complete: {response.text}")
                    retries += 1
            recovered = client.get(f"/api/v2/runs/{run_id}")
            recovered.raise_for_status()
            snapshot = recovered.json()
            if snapshot["state"]["revision"] != args.turns or len(snapshot["turns"]) != args.turns:
                raise RuntimeError("long-play recovery state does not match completed turns")
    args.evidence.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "environment": "fresh temporary DZMM_DATA_DIR; FastAPI TestClient; real LM Studio provider",
        "model": args.model,
        "base_url": args.base_url,
        "turns": args.turns,
        "retries_after_non_committing_model_failures": retries,
        "latency_seconds": {
            "min": round(min(latencies), 3),
            "median": round(statistics.median(latencies), 3),
            "max": round(max(latencies), 3),
        },
        "recovery": "state revision and persisted turn count matched completed turns",
    }
    args.evidence.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
