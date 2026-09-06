import json
import sqlite3
import time

from test_world_compose import compose_payload

from dzmm.director import (
    build_director_prompt,
    is_note_fresh,
    parse_director_note,
    should_run_director,
)
from dzmm.embedded_model_requests import request_director_note


def test_should_run_director_only_on_interval_boundaries() -> None:
    assert should_run_director(6) and should_run_director(12)
    assert not should_run_director(0) and not should_run_director(5)


def test_parse_director_note_whitelists_and_clamps() -> None:
    note = parse_director_note('{"tension": "追兵逼近", "hook": "星门钥匙", "extra": 1}')
    assert note == {"tension": "追兵逼近", "hook": "星门钥匙"}

    long = "长" * 200
    note = parse_director_note(json.dumps({"tension": long, "hook": "ok"}))
    assert note is not None and len(note["tension"]) == 120

    for bad in ('{"hook": "缺 tension"}', "不是 JSON", '{"tension": 3, "hook": "x"}', ""):
        assert parse_director_note(bad) is None


def test_parse_director_note_tolerates_code_fence() -> None:
    note = parse_director_note('```json\n{"tension": "a", "hook": "b"}\n```')
    assert note == {"tension": "a", "hook": "b"}


def test_note_freshness_window() -> None:
    assert is_note_fresh(6, 10) and is_note_fresh(6, 18)
    assert not is_note_fresh(6, 19) and not is_note_fresh(None, 3)


def test_build_director_prompt_carries_recent_turns_and_threads() -> None:
    state = {
        "hero": {"name": "凯拉"},
        "chapter": {"title": "最终决断"},
        "revision": 6,
        "narrative_context": {
            "recent_turns": [
                {"turn": 5, "player_input": "追查线索", "narrative": "灯笼移动了", "outcomes": []}
            ]
        },
        "plot_threads": [{"description": "钟声之谜", "status": "active"}],
    }
    definition = {"name": "迷雾钟楼"}
    prompt = build_director_prompt(state, definition)
    assert prompt["hero"] == "凯拉" and prompt["chapter"] == "最终决断"
    assert prompt["recent_turns"][0]["player_input"] == "追查线索"
    assert prompt["plot_threads"][0]["description"] == "钟声之谜"


def test_director_request_uses_small_budget_and_json_system() -> None:
    import dzmm.embedded_model_requests as requests_module

    captured: dict = {}

    class FakeResponse:
        status_code = 200

        def json(self):
            captured["done"] = True
            return {"message": {"content": '{"tension": "a", "hook": "b"}'}}

    def fake_post(url, payload, timeout=None):
        captured["payload"] = payload
        return FakeResponse()

    original = requests_module._post_chat
    requests_module._post_chat = fake_post
    try:
        body = request_director_note(
            {"provider_type": "ollama", "model_name": "qwen2.5:7b", "base_url": "http://x"},
            {"system": "导演提示", "hero": "凯拉"},
        )
    finally:
        requests_module._post_chat = original
    assert isinstance(body, FakeResponse)
    assert captured["payload"]["options"]["num_predict"] == 256
    assert "导演提示" in captured["payload"]["messages"][0]["content"]
    assert captured["payload"]["messages"][1]["role"] == "user"


def test_play_cycle_stores_director_note_and_injects_into_later_turn(
    migrated_client, monkeypatch
) -> None:
    """HTTP path: revision 6 schedules the director; turn 7 receives the note."""

    from dzmm.model_profiles import ModelNarrator

    client, db_path = migrated_client
    template = client.get("/api/v2/world-templates/d20-frontier").json()

    profile = client.post(
        "/api/v2/model-profiles",
        json={
            "name": "director-test",
            "provider_type": "ollama",
            "base_url": "http://127.0.0.1:11434",
            "model_name": "qwen2.5:7b",
        },
    ).json()
    payload = compose_payload("director-compose-1")
    payload["model_profile_id"] = profile["id"]
    payload["world_definition"] = template["world_definition"]
    payload["hero"] = template["hero"]
    composed = client.post("/api/v2/worlds:compose", json=payload).json()
    run_id = composed["run_id"]

    calls: list[dict] = []

    async def fake_narrate_with_actions(
        self,
        profile,
        definition,
        state,
        player_input,
        outcomes,
        lore_entries,
        *,
        variation_seed="",
        director_note=None,
    ):
        calls.append({"kind": "narrative", "director_note": director_note})
        return "夜风穿过废墟。艾登低声说：“走。” 雷欧点头检查装备。", []

    async def fake_director_completion(self, profile, prompt):
        calls.append({"kind": "director", "hero": prompt.get("hero")})
        return '{"tension": "追兵将至", "hook": "星图碎片"}'

    monkeypatch.setattr(ModelNarrator, "narrate_with_actions", fake_narrate_with_actions)
    monkeypatch.setattr(ModelNarrator, "director_completion", fake_director_completion)

    revision = composed["state"]["revision"]
    for index in range(1, 7):
        response = client.post(
            f"/api/v2/runs/{run_id}/turns",
            json={
                "request_id": f"director-turn-{index}",
                "expected_revision": revision,
                "player_input": f"第{index}回合行动",
                "commands": [{"type": "narrate", "payload": {}}],
            },
        )
        assert response.status_code == 201, response.text
        revision = response.json()["state"]["revision"]
    assert revision == 6

    deadline = time.monotonic() + 5
    note_row = None
    while time.monotonic() < deadline:
        with sqlite3.connect(db_path) as connection:
            note_row = connection.execute(
                "SELECT tension, hook FROM director_notes WHERE run_id = ?", (run_id,)
            ).fetchone()
        if note_row is not None:
            break
        time.sleep(0.05)
    assert note_row is not None, "director task did not store a note"
    assert note_row == ("追兵将至", "星图碎片")

    response = client.post(
        f"/api/v2/runs/{run_id}/turns",
        json={
            "request_id": "director-turn-7",
            "expected_revision": revision,
            "player_input": "第7回合行动",
            "commands": [{"type": "narrate", "payload": {}}],
        },
    )
    assert response.status_code == 201, response.text
    narrative_calls = [call for call in calls if call["kind"] == "narrative"]
    assert len(narrative_calls) == 7
    assert narrative_calls[-1]["director_note"]["tension"] == "追兵将至"
    assert narrative_calls[-1]["director_note"]["hook"] == "星图碎片"
    assert narrative_calls[-1]["director_note"]["turn"] == 6
    assert all(call["director_note"] is None for call in narrative_calls[:-1])


def test_director_failure_degrades_silently(migrated_client, monkeypatch) -> None:
    from dzmm.model_profiles import ModelNarrator

    client, db_path = migrated_client
    template = client.get("/api/v2/world-templates/d20-frontier").json()

    profile = client.post(
        "/api/v2/model-profiles",
        json={
            "name": "director-fail",
            "provider_type": "ollama",
            "base_url": "http://127.0.0.1:11434",
            "model_name": "qwen2.5:7b",
        },
    ).json()
    payload = compose_payload("director-compose-fail")
    payload["model_profile_id"] = profile["id"]
    payload["world_definition"] = template["world_definition"]
    payload["hero"] = template["hero"]
    composed = client.post("/api/v2/worlds:compose", json=payload).json()
    run_id = composed["run_id"]

    narrative_notes: list = []

    async def fake_narrate_with_actions(
        self,
        profile,
        definition,
        state,
        player_input,
        outcomes,
        lore_entries,
        *,
        variation_seed="",
        director_note=None,
    ):
        narrative_notes.append(director_note)
        return "艾登检查了废墟的每一块石板。雷欧守在门口。", []

    def failing_director_completion(self, profile, prompt):
        raise TimeoutError("director model overloaded")

    monkeypatch.setattr(ModelNarrator, "narrate_with_actions", fake_narrate_with_actions)
    monkeypatch.setattr(ModelNarrator, "director_completion", failing_director_completion)

    revision = composed["state"]["revision"]
    for index in range(1, 7):
        response = client.post(
            f"/api/v2/runs/{run_id}/turns",
            json={
                "request_id": f"director-fail-turn-{index}",
                "expected_revision": revision,
                "player_input": f"第{index}回合行动",
                "commands": [{"type": "narrate", "payload": {}}],
            },
        )
        assert response.status_code == 201, response.text
        revision = response.json()["state"]["revision"]

    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        time.sleep(0.1)
    with sqlite3.connect(db_path) as connection:
        note_row = connection.execute(
            "SELECT tension FROM director_notes WHERE run_id = ?", (run_id,)
        ).fetchone()
        turn_count = connection.execute(
            "SELECT COUNT(*) FROM turns WHERE run_id = ?", (run_id,)
        ).fetchone()[0]
    assert note_row is None
    assert turn_count == 6
    assert all(note is None for note in narrative_notes)
