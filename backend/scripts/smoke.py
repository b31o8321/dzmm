"""End-to-end smoke test against a running backend.

Prereqs:
    - Run `python scripts/run_dev.py` in another terminal
    - Have Ollama running locally with qwen2.5:7b (or edit MODEL_NAME below)

Usage:
    python scripts/smoke.py
"""
import asyncio
import json

import httpx

BASE = "http://127.0.0.1:8765"
MODEL_NAME = "qwen2.5:7b"


async def main():
    async with httpx.AsyncClient(base_url=BASE, timeout=120.0) as c:
        w = (await c.post("/worlds", json={
            "name": "测试世界", "style": "dark",
            "content_md": "赛博朋克末世，企业掌权，街头义体黑客横行。",
        })).json()
        ch = (await c.post("/characters", json={
            "world_id": w["id"], "name": "Riku", "profile_md": "义体黑客，30 岁",
            "base_stats_json": json.dumps({"hp": 20, "sanity": 15}),
        })).json()
        m = (await c.post("/model_configs", json={
            "name": "local", "type": "ollama",
            "base_url": "http://localhost:11434", "model_name": MODEL_NAME,
        })).json()
        s = (await c.post("/sessions", json={
            "name": "smoke-run", "world_id": w["id"], "character_id": ch["id"],
            "gm_model_config_id": m["id"], "summarizer_model_config_id": m["id"],
        })).json()
        print(f"Session created: {s['id']}")

        async with c.stream("POST", f"/sessions/{s['id']}/turn",
                            json={"action": "(开始游戏)"}) as r:
            r.raise_for_status()
            async for line in r.aiter_lines():
                if line:
                    print(line)


if __name__ == "__main__":
    asyncio.run(main())
