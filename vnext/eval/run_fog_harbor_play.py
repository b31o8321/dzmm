#!/usr/bin/env python3
"""Run the deterministic Fog Harbor route with a real local model in an isolated DB."""
from __future__ import annotations

import argparse
import json
import os
import statistics
import tempfile
import time
from pathlib import Path

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from dzmm_vnext.config import Settings
from dzmm_vnext.main import create_app
from dzmm_vnext.world_templates import fog_harbor_template


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    result.add_argument("--base-url", required=True, help="OpenAI-compatible /v1 root")
    result.add_argument("--model", required=True)
    result.add_argument("--evidence", type=Path, required=True)
    return result


def main() -> None:
    args = parser().parse_args()
    latencies: list[float] = []
    narratives: list[str] = []
    choices = ["rescue-lan", "lan-testimony", "open-tide-gate"]
    with tempfile.TemporaryDirectory(prefix="dzmm-vnext-fog-harbor-") as temporary:
        data_dir = Path(temporary) / "data"
        os.environ["DZMM_NEXT_DATA_DIR"] = str(data_dir)
        command.upgrade(Config(str(Path(__file__).parents[1] / "backend" / "alembic.ini")), "head")
        app = create_app(Settings(data_dir=data_dir))
        with TestClient(app, raise_server_exceptions=False) as client:
            profile = client.post(
                "/api/v2/model-profiles",
                json={
                    "name": "fog-harbor-baseline",
                    "provider_type": "lm_studio",
                    "base_url": args.base_url,
                    "model_name": args.model,
                },
            )
            profile.raise_for_status()
            payload = fog_harbor_template()
            payload.update(
                {
                    "request_id": "fog-harbor-compose",
                    "model_profile_id": profile.json()["id"],
                }
            )
            composed = client.post("/api/v2/worlds:compose", json=payload)
            composed.raise_for_status()
            run_id = composed.json()["run_id"]
            for revision, choice_id in enumerate(choices):
                started = time.perf_counter()
                response = client.post(
                    f"/api/v2/runs/{run_id}/choices",
                    json={
                        "request_id": f"fog-choice-{revision + 1}",
                        "expected_revision": revision,
                        "player_input": choice_id,
                        "choice_id": choice_id,
                    },
                )
                latencies.append(time.perf_counter() - started)
                response.raise_for_status()
                turn = response.json()
                if not turn["narrative"].strip():
                    raise RuntimeError(f"choice {choice_id} committed without narrative")
                narratives.append(turn["narrative"])
            snapshot = client.get(f"/api/v2/runs/{run_id}")
            snapshot.raise_for_status()
            state = snapshot.json()["state"]
            if state["revision"] != len(choices) or state["ending"]["id"] != "lan-dawn":
                raise RuntimeError("Fog Harbor did not reach the expected good ending")
    payload = {
        "environment": "fresh temporary DZMM_NEXT_DATA_DIR; FastAPI TestClient; real LM Studio provider",
        "model": args.model,
        "base_url": args.base_url,
        "choices": choices,
        "ending": "lan-dawn",
        "non_empty_narratives": len(narratives),
        "latency_seconds": {
            "min": round(min(latencies), 3),
            "median": round(statistics.median(latencies), 3),
            "max": round(max(latencies), 3),
        },
        "recovery": "RunState revision and good ending matched the persisted turn sequence",
    }
    args.evidence.parent.mkdir(parents=True, exist_ok=True)
    args.evidence.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
