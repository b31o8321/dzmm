"""v1.6.0 NPC 试玩场：sandbox run 不进世界统计，只允许沙盒删除。"""

from __future__ import annotations

from tests.test_world_compose import compose_payload


def _compose_sandbox(client, request_id: str):
    payload = compose_payload(request_id)
    payload["sandbox"] = True
    created = client.post("/api/v2/worlds:compose", json=payload)
    assert created.status_code == 201, created.text
    return created.json()


def test_sandbox_run_marks_state_and_excludes_world_stats(migrated_client) -> None:
    client, _ = migrated_client
    sandbox = _compose_sandbox(client, "sandbox-compose-1")
    assert sandbox["state"]["sandbox"] is True

    world_id = sandbox["world_id"]
    # 世界列表里，试玩场运行不计入局数
    worlds_list = client.get("/api/v2/worlds").json()
    target = next(w for w in (worlds_list if isinstance(worlds_list, list) else worlds_list["items"]) if w["id"] == world_id)
    assert target["run_count"] == 0


def test_sandbox_run_plays_turns_normally(migrated_client) -> None:
    client, _ = migrated_client
    sandbox = _compose_sandbox(client, "sandbox-compose-2")
    run_id = sandbox["run_id"]
    turn = client.post(
        f"/api/v2/runs/{run_id}/turns",
        json={
            "request_id": "sandbox-turn-1",
            "expected_revision": 0,
            "player_input": "我看着看门人，想先聊聊昨夜的钟声。",
            "commands": [{"type": "narrate", "payload": {}}],
        },
    )
    assert turn.status_code == 201, turn.text
    assert turn.json()["state"]["sandbox"] is True


def test_delete_allows_only_sandbox_runs(migrated_client) -> None:
    client, _ = migrated_client
    normal = client.post("/api/v2/worlds:compose", json=compose_payload("sandbox-normal")).json()
    sandbox = _compose_sandbox(client, "sandbox-compose-3")

    forbidden = client.delete(f"/api/v2/runs/{normal['run_id']}")
    assert forbidden.status_code == 409

    allowed = client.delete(f"/api/v2/runs/{sandbox['run_id']}")
    assert allowed.status_code == 204
    assert client.get(f"/api/v2/runs/{sandbox['run_id']}").status_code == 404


def test_normal_compose_has_no_sandbox_flag(migrated_client) -> None:
    client, _ = migrated_client
    normal = client.post("/api/v2/worlds:compose", json=compose_payload("sandbox-normal-2")).json()
    assert "sandbox" not in normal["state"] or normal["state"]["sandbox"] is not True
