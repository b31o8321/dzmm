"""Visual service + API (v1.11.0 M1): settings, status, generate, media serving.

HTTP boundary is mocked at comfy_client (the actual ComfyUI client); the
service logic, DB records, worker queue and file serving run for real.
"""

import time
from unittest.mock import patch

from dzmm.comfy_client import ComfyUIError, GeneratedImage


def compose_payload(request_id: str) -> dict:
    return {
        "request_id": request_id,
        "world_definition": {
            "schema_version": 3,
            "name": "Fog Harbor",
            "lorebook": {"entries": []},
            "character_cards": [
                {"id": "lan", "name": "岚", "format": "native"},
            ],
            "locations": [
                {"id": "harbor", "name": "Fog Harbor"},
                {"id": "lighthouse", "name": "Old Lighthouse"},
            ],
            "factions": [],
            "npcs": [
                {
                    "id": "lan",
                    "name": "岚",
                    "description": "雾港码头的神秘少女，银发青瞳",
                },
            ],
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
        "hero": {"name": "Mira", "profile": {"origin": "sailor"}},
    }


def enable_visual(client) -> None:
    response = client.put(
        "/api/v2/visual/settings",
        json={"comfy_url": "http://127.0.0.1:8188", "enabled": True},
    )
    assert response.status_code == 200, response.text


def await_task(client, task_id: str, timeout_seconds: float = 5.0) -> dict:
    deadline = time.monotonic() + timeout_seconds
    last: dict = {}
    while time.monotonic() < deadline:
        response = client.get(f"/api/v2/visual/tasks/{task_id}")
        assert response.status_code == 200, response.text
        last = response.json()
        if last["status"] in {"done", "failed"}:
            return last
        time.sleep(0.05)
    return last


def test_visual_settings_roundtrip_and_validation(migrated_client) -> None:
    client, _ = migrated_client

    default = client.get("/api/v2/visual/settings").json()
    assert default["enabled"] is False
    assert default["comfy_url"] == "http://127.0.0.1:8188"

    bad = client.put(
        "/api/v2/visual/settings", json={"comfy_url": "not-a-url", "enabled": True}
    )
    assert bad.status_code == 422

    updated = client.put(
        "/api/v2/visual/settings",
        json={"comfy_url": "http://192.168.1.20:8188", "enabled": True},
    )
    assert updated.status_code == 200
    assert updated.json()["comfy_url"] == "http://192.168.1.20:8188"

    reread = client.get("/api/v2/visual/settings").json()
    assert reread["enabled"] is True
    # PUT 是整体替换：未传字段回落默认值
    assert reread["style_prefix"] == default["style_prefix"]


def test_visual_status_reports_unreachable_comfyui(migrated_client) -> None:
    client, _ = migrated_client
    # 127.0.0.1:1 几乎必然拒绝连接 → 状态探测必须收敛为 False 而非抛错
    response = client.get("/api/v2/visual/status")
    assert response.status_code == 200
    body = response.json()
    assert body["reachable"] is False
    assert body["enabled"] is False


def test_generate_requires_enabled_visual(migrated_client) -> None:
    client, _ = migrated_client
    world_id = client.post(
        "/api/v2/worlds:compose", json=compose_payload("compose-disabled")
    ).json()["world_id"]
    response = client.post(
        "/api/v2/visual/generate",
        json={"world_id": world_id, "kind": "cover"},
    )
    assert response.status_code == 409


def test_generate_portrait_end_to_end_with_mock_comfyui(migrated_client) -> None:
    client, _ = migrated_client
    created = client.post(
        "/api/v2/worlds:compose", json=compose_payload("compose-visual")
    ).json()
    world_id = created["world_id"]
    enable_visual(client)

    fake_blob = b"\x89PNG-mock"
    with (
        patch("dzmm.comfy_client.generate") as fake_generate,
        patch(
            "dzmm.comfy_client.submit_workflow",
            return_value="prompt-1",
        ),
    ):
        fake_generate.return_value = (
            [GeneratedImage(filename="out.png", subfolder="", image_type="output")],
            [fake_blob],
        )
        response = client.post(
            "/api/v2/visual/generate",
            json={"world_id": world_id, "kind": "portrait", "subject_id": "lan"},
        )
        assert response.status_code == 202, response.text
        task = response.json()
        assert task["status"] == "queued"

        final = await_task(client, task["id"])

    assert final["status"] == "done", final
    assert final["error"] is None
    assert final["file_path"] == f"{world_id}/{final['file_path'].split('/')[-1]}"
    assert "/".join(final["file_path"].split("/")[1:]).startswith("portrait-lan-")
    # 提示词 = 风格前缀 + npc description 兜底
    assert "silver" not in final["prompt"]
    assert "雾港码头" in final["prompt"]
    assert final["seed"] and final["seed"] > 0

    media = client.get(
        f"/api/v2/media/{world_id}/{final['file_path'].split('/')[-1]}"
    )
    assert media.status_code == 200
    assert media.content == fake_blob


def test_generate_rejects_unknown_subject_and_world(migrated_client) -> None:
    client, _ = migrated_client
    world_id = client.post(
        "/api/v2/worlds:compose", json=compose_payload("compose-badsubj")
    ).json()["world_id"]
    enable_visual(client)

    missing_subject = client.post(
        "/api/v2/visual/generate",
        json={"world_id": world_id, "kind": "portrait", "subject_id": "ghost"},
    )
    assert missing_subject.status_code == 422

    missing_world = client.post(
        "/api/v2/visual/generate",
        json={"world_id": "00000000-0000-0000-0000-000000000000", "kind": "cover"},
    )
    assert missing_world.status_code == 404

    scene_without_note = client.post(
        "/api/v2/visual/generate",
        json={"world_id": world_id, "kind": "scene"},
    )
    assert scene_without_note.status_code == 422


def test_failed_generation_records_error(migrated_client) -> None:
    client, _ = migrated_client
    world_id = client.post(
        "/api/v2/worlds:compose", json=compose_payload("compose-fail")
    ).json()["world_id"]
    enable_visual(client)

    with patch(
        "dzmm.comfy_client.submit_workflow",
        side_effect=ComfyUIError("connection refused"),
    ):
        response = client.post(
            "/api/v2/visual/generate", json={"world_id": world_id, "kind": "cover"}
        )
        assert response.status_code == 202
        final = await_task(client, response.json()["id"])

    assert final["status"] == "failed"
    assert "connection refused" in final["error"]
    assert final["file_path"] is None


def test_media_serving_blocks_path_traversal(migrated_client) -> None:
    client, _ = migrated_client
    traversal = client.get("/api/v2/media/../../dzmm-v3.db/x")
    assert traversal.status_code in {404, 400}
    missing = client.get(
        "/api/v2/media/00000000-0000-0000-0000-000000000000/none.png"
    )
    assert missing.status_code == 404
