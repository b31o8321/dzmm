#!/usr/bin/env python3
"""Exercise every Fog Harbor ending with a real local model in an isolated DB."""
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

from dzmm.config import Settings
from dzmm.main import create_app
from dzmm.world_templates import fog_harbor_template


ROUTES = {
    "lan_good": (["rescue-lan", "lan-testimony", "open-tide-gate"], "lan-dawn"),
    "shen_good": (["hide-chart", "shen-confession", "open-tide-gate"], "shen-low-tide"),
    "neutral": (["hide-chart", "neutral-lead", "open-tide-gate"], "neutral-harbor"),
    "bad": (["hide-chart", "neutral-lead", "miss-the-tide"], "fog-drowned"),
    "hidden": (["rescue-lan", "unite-witnesses", "open-tide-gate"], "bell-beyond-fog"),
}


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    result.add_argument("--provider", choices=["ollama", "lm_studio", "openai_compat"], default="lm_studio")
    result.add_argument("--base-url", required=True, help="Provider root; Ollama uses server root, others use /v1")
    result.add_argument("--model", required=True)
    result.add_argument("--cycles", type=int, default=1, help="Repeat every route for a longer real-model matrix")
    result.add_argument("--evidence", type=Path, required=True)
    return result


def main() -> None:
    args = parser().parse_args()
    if args.cycles < 1:
        raise SystemExit("--cycles must be positive")
    latencies: list[float] = []
    route_results: dict[str, list[dict[str, object]]] = {name: [] for name in ROUTES}
    with tempfile.TemporaryDirectory(prefix="dzmm-fog-matrix-") as temporary:
        data_dir = Path(temporary) / "data"
        os.environ["DZMM_DATA_DIR"] = str(data_dir)
        command.upgrade(Config(str(Path(__file__).parents[1] / "backend" / "alembic.ini")), "head")
        app = create_app(Settings(data_dir=data_dir))
        with TestClient(app, raise_server_exceptions=False) as client:
            profile = client.post(
                "/api/v2/model-profiles",
                json={
                    "name": "fog-harbor-matrix",
                    "provider_type": args.provider,
                    "base_url": args.base_url,
                    "model_name": args.model,
                },
            )
            profile.raise_for_status()
            for cycle in range(args.cycles):
                for route_name, (choices, expected_ending) in ROUTES.items():
                    run_name = f"{route_name}-{cycle + 1}"
                    payload = fog_harbor_template()
                    payload.update(
                        {
                            "request_id": f"fog-matrix-compose-{run_name}",
                            "model_profile_id": profile.json()["id"],
                        }
                    )
                    composed = client.post("/api/v2/worlds:compose", json=payload)
                    composed.raise_for_status()
                    run_id = composed.json()["run_id"]
                    narratives: list[str] = []
                    first_turn_id: str | None = None
                    for revision, choice_id in enumerate(choices):
                        started = time.perf_counter()
                        response = client.post(
                            f"/api/v2/runs/{run_id}/choices",
                            json={
                                "request_id": f"fog-{run_name}-{revision + 1}",
                                "expected_revision": revision,
                                "player_input": choice_id,
                                "choice_id": choice_id,
                            },
                        )
                        latencies.append(time.perf_counter() - started)
                        if response.is_error:
                            raise RuntimeError(
                                f"{run_name} choice {choice_id} failed: {response.status_code} {response.text}"
                            )
                        turn = response.json()
                        if not turn["narrative"].strip():
                            raise RuntimeError(f"{run_name} choice {choice_id} committed without narrative")
                        narratives.append(turn["narrative"])
                        if revision == 0:
                            first_turn_id = turn["turn_id"]
                    snapshot = client.get(f"/api/v2/runs/{run_id}")
                    snapshot.raise_for_status()
                    state = snapshot.json()["state"]
                    if state["revision"] != len(choices) or state["ending"]["id"] != expected_ending:
                        raise RuntimeError(f"{run_name} did not reach {expected_ending}")
                    assert first_turn_id is not None
                    rollback = client.post(
                        f"/api/v2/runs/{run_id}/rollbacks",
                        json={
                            "request_id": f"fog-{run_name}-rollback",
                            "expected_revision": len(choices),
                            "target_turn_id": first_turn_id,
                        },
                    )
                    rollback.raise_for_status()
                    reopened = client.get(f"/api/v2/runs/{run_id}")
                    reopened.raise_for_status()
                    restored = reopened.json()["state"]
                    if restored["chapter"]["id"] != "ch2" or restored["ending"] is not None:
                        raise RuntimeError(f"{run_name} rollback did not restore its second chapter")
                    route_results[route_name].append(
                        {
                            "choices": choices,
                            "ending": expected_ending,
                            "non_empty_narratives": len(narratives),
                            "rollback": "restored ch2 with ending unlocked after persisted reopen",
                        }
                    )
    payload = {
        "environment": "fresh temporary DZMM_DATA_DIR; FastAPI TestClient; real local provider",
        "provider": args.provider,
        "model": args.model,
        "base_url": args.base_url,
        "cycles": args.cycles,
        "routes": route_results,
        "total_choice_turns": args.cycles * sum(len(choices) for choices, _ending in ROUTES.values()),
        "latency_seconds": {
            "min": round(min(latencies), 3),
            "median": round(statistics.median(latencies), 3),
            "max": round(max(latencies), 3),
        },
    }
    args.evidence.parent.mkdir(parents=True, exist_ok=True)
    args.evidence.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
