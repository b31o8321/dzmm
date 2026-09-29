"""v1.7.0 asset ecosystem P0/P1: URL import + distillation MVP."""

from __future__ import annotations

import json
import time

from tests.test_world_compose import compose_payload


# ===== P0: URL 导入 =====
def test_import_from_url_accepts_st_world_info(migrated_client, monkeypatch) -> None:
    from dzmm import asset_import

    client, _ = migrated_client

    world_info = {
        "entries": {
            "0": {"key": ["灰潮"], "content": "灰潮是每夜升起的浓雾。", "constant": True},
        }
    }
    monkeypatch.setattr(asset_import, "fetch_asset", lambda url: json.dumps(world_info).encode())
    response = client_post_import(client, "http://example.com/card.json")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["lorebook"]["entries"], "world info entries imported"
    assert body["report"]["source_url"] == "http://example.com/card.json"


def test_import_from_url_accepts_png_card(migrated_client, monkeypatch) -> None:
    from dzmm import asset_import

    client, _ = migrated_client

    card = {
        "spec": "chara_card_v3",
        "data": {"name": "看门人", "description": "沉默寡言的守塔人。"},
    }
    # PNG 分支走 base64 → import_sillytavern_png 需要 _decode_png_card 支持的图像。
    # 这里直接验证 sniff 路由：PNG 头 → base64 payload。
    png_bytes = b"\x89PNG\r\n\x1a\n" + b"00"
    monkeypatch.setattr(asset_import, "fetch_asset", lambda url: png_bytes)
    monkeypatch.setattr(
        asset_import, "import_sillytavern_png",
        lambda encoded: asset_import.import_sillytavern(card),
    )
    response = client_post_import(client, "http://example.com/card.png")
    assert response.status_code == 200, response.text
    assert response.json()["character_cards"], "png card routed into ST import"


def test_import_from_url_rejects_unknown_and_bad_links(migrated_client, monkeypatch) -> None:
    from dzmm import asset_import

    client, _ = migrated_client

    monkeypatch.setattr(asset_import, "fetch_asset", lambda url: b"not json at all")
    bad = client_post_import(client, "http://example.com/x.txt")
    assert bad.status_code == 422
    assert "资产格式" in bad.text

    non_http = client.post(
        "/api/v2/content/assets:import-from-url", json={"url": "ftp://example.com/x"}
    )
    assert non_http.status_code == 422


def client_post_import(client, url: str):
    return client.post("/api/v2/content/assets:import-from-url", json={"url": url})


# ===== P1: 蒸馏 MVP =====
def test_distill_requires_model_profile(migrated_client) -> None:
    client, _ = migrated_client
    created = client.post("/api/v2/worlds:compose", json=compose_payload("distill-no-profile")).json()
    response = client.post(f"/api/v2/runs/{created['run_id']}:distill")
    assert response.status_code == 409


def test_distill_produces_three_assets(migrated_client, monkeypatch) -> None:
    import sqlite3

    from dzmm.model_profiles import ModelNarrator

    client, db_path = migrated_client
    profile = client.post(
        "/api/v2/model-profiles",
        json={"name": "distill-test", "provider_type": "ollama",
              "base_url": "http://127.0.0.1:11434", "model_name": "qwen2.5:7b"},
    ).json()
    payload = compose_payload("distill-run")
    payload["model_profile_id"] = profile["id"]
    created = client.post("/api/v2/worlds:compose", json=payload).json()
    run_id = created["run_id"]

    async def fake_narrate_with_actions(self, profile, definition, state, player_input,
                                        outcomes, lore_entries, *, variation_seed="", director_note=None):
        return "夜风穿过废墟。", []

    prompts: list[dict] = []

    async def fake_completion(self, profile, prompt):
        prompts.append(prompt)
        system = prompt["system"]
        if "角色小传" in system:
            return "她从灰雾中走来，带着未愈的旧伤。"
        if "语言指纹" in system:
            return '{"口头禅": ["……罢了"], "句式习惯": [], "情绪语气样本": []}'
        return '{"events": [{"回合": 1, "事件": "抵达废墟", "影响": "故事开始"}]}'

    monkeypatch.setattr(ModelNarrator, "narrate_with_actions", fake_narrate_with_actions)
    monkeypatch.setattr(ModelNarrator, "director_completion", fake_completion)

    client.post(f"/api/v2/runs/{run_id}/turns", json={
        "request_id": "d-turn-1", "expected_revision": 0,
        "player_input": "我抵达废墟。", "commands": [{"type": "narrate", "payload": {}}],
    })
    accepted = client.post(f"/api/v2/runs/{run_id}:distill")
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["status"] == "accepted"

    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        with sqlite3.connect(db_path) as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM distillations WHERE run_id = ?", (run_id,)
            ).fetchone()[0]
        if count == 3:
            break
        time.sleep(0.05)
    assert count == 3, "three distilled assets stored"

    listed = client.get(f"/api/v2/runs/{run_id}/distillations").json()
    assert {item["kind"] for item in listed} == {
        "character-bible", "dialogue-fingerprint", "chronicle",
    }

    exported = client.get(f"/api/v2/runs/{run_id}/distillations:export")
    assert exported.status_code == 200
    markdown = exported.json()["markdown"]
    assert "角色小传" in markdown and "台词指纹" in markdown and "事件年表" in markdown
    assert "她从灰雾中走来" in markdown
    assert prompts and all("corpus" in prompt for prompt in prompts)
