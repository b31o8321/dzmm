"""v1.8.0 first slice: hero reuse across runs + novel material export."""

from __future__ import annotations

from tests.test_world_compose import compose_payload


def test_hero_reuse_keeps_identity_and_carries_snapshot(migrated_client) -> None:
    client, _ = migrated_client
    first = client.post("/api/v2/worlds:compose", json=compose_payload("hero-first")).json()
    world_id = first["world_id"]
    hero_id = first["hero_id"]

    second = client.post(
        f"/api/v2/worlds/{world_id}/runs",
        json={
            "request_id": "hero-second-run",
            "hero": {"name": "任意名，将被覆盖", "profile": {}},
            "hero_id": hero_id,
        },
    )
    assert second.status_code == 201, second.text
    state = second.json()["state"]
    assert state["hero"]["id"] == hero_id
    assert state["hero"]["name"] == "Mira"
    assert state["hero"]["carried"]["previous_runs"] >= 1

    reused = client.get(f"/api/v2/runs/{second.json()['run_id']}").json()
    assert reused["hero_id"] == hero_id


def test_hero_reuse_rejects_foreign_hero(migrated_client) -> None:
    client, _ = migrated_client
    other = client.post("/api/v2/worlds:compose", json=compose_payload("hero-other")).json()
    payload = compose_payload("hero-foreign")
    created = client.post("/api/v2/worlds:compose", json=payload).json()
    response = client.post(
        f"/api/v2/worlds/{created['world_id']}/runs",
        json={
            "request_id": "hero-foreign-run",
            "hero": {"name": "X", "profile": {}},
            "hero_id": other["hero_id"],
        },
    )
    assert response.status_code == 422
    assert "hero_id" in response.text


def test_novel_export_assembles_sections(migrated_client) -> None:
    client, _ = migrated_client
    created = client.post("/api/v2/worlds:compose", json=compose_payload("novel-export")).json()
    client.post(
        f"/api/v2/runs/{created['run_id']}/turns",
        json={
            "request_id": "novel-t1",
            "expected_revision": 0,
            "player_input": "我检查码头的灯火。",
            "commands": [{"type": "narrate", "payload": {}}],
        },
    )
    exported = client.get(f"/api/v2/runs/{created['run_id']}/novel:export")
    assert exported.status_code == 200, exported.text
    body = exported.json()
    assert body["sections"][0] == "正文素材"
    assert "【第 1 回合】" in body["markdown"]
    assert body["hero"] == "Mira"
