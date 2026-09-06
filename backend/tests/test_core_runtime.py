import pytest

from dzmm.core_runtime import (
    CoreRuntimeError,
    LocalCoreRuntime,
    _narrative_chapter_context,
    _narrative_entity_names,
    _narrative_memory_layers,
    _narrative_outcome_context,
    _narrative_world_material,
)
from dzmm.story_beats import build_opening_story_beat
from dzmm.world_templates import fog_harbor_template


def test_opening_story_beat_contains_scene_dialogue_objective_and_guidance() -> None:
    template = fog_harbor_template()
    beat = build_opening_story_beat(template["world_definition"], template["hero"])

    assert beat["kind"] == "opening"
    assert "雾港码头" in beat["narrative"]
    assert beat["dialogue"]["speaker"] == "岚"
    assert "潮雾抵港" in beat["objective"]
    assert "救岚" in beat["guidance"]


def test_narrative_model_context_uses_player_names_instead_of_internal_ids() -> None:
    definition = fog_harbor_template()["world_definition"]
    state = {
        "chapter": {"id": "ch1", "resolved_choice_ids": []},
    }

    entities = _narrative_entity_names(definition)
    material = _narrative_world_material(definition)
    chapter = _narrative_chapter_context(definition, state)
    outcomes = _narrative_outcome_context(
        definition,
        [
            {"type": "choose_story_choice", "choice_id": "rescue-lan"},
            {"type": "apply_relationship_event", "relationship_id": "lan"},
            {"type": "advance_chapter", "next_chapter_id": "ch2"},
        ],
    )

    assert entities["characters"] == ["岚", "沈砚"]
    assert material["characters"][0]["name"] == "岚"
    assert chapter["title"] == "潮雾抵港"
    assert [choice["label"] for choice in chapter["choices"]] == ["救岚", "替沈砚藏起航图"]
    assert outcomes == [
        {"type": "choose_story_choice", "choice_name": "救岚"},
        {"type": "apply_relationship_event", "relationship_name": "岚"},
        {"type": "advance_chapter", "next_chapter_name": "沉船的证词"},
    ]


def test_narrative_memory_layers_keep_worldbook_and_open_threads_player_safe() -> None:
    definition = fog_harbor_template()["world_definition"]
    definition["lorebook"]["entries"][0]["activation"] = "always"
    state = {
        "location_id": "harbor",
        "plot_threads": [
            {"status": "active", "description": "失踪航图指向北岸"},
        ],
        "active_events": [
            {"status": "active", "description": "潮门将在午夜开启"},
        ],
        "narrative_context": {
            "recent_turns": [
                {"turn": 1, "player_input": "调查码头", "narrative": "你发现脚印。", "outcomes": []}
            ]
        },
    }

    layers = _narrative_memory_layers(definition, state, "查看潮水")

    assert layers["worldbook"][0]["title"] == "灰潮"
    assert layers["open_threads"] == ["失踪航图指向北岸"]
    assert layers["active_events"] == ["潮门将在午夜开启"]
    assert layers["recent_turns"][0]["player_input"] == "调查码头"


def test_transport_free_core_runs_story_ending_and_rollback(tmp_path) -> None:
    runtime = LocalCoreRuntime(tmp_path / "core.db")
    composed = runtime.compose(fog_harbor_template())
    run_id = composed["run_id"]
    for index in range(3):
        run = runtime.get_run(run_id)
        choice = run["available_choices"][0]
        run = runtime.choose(
            run_id,
            {
                "request_id": f"core-choice-{index}",
                "expected_revision": run["state"]["revision"],
                "choice_id": choice["id"],
                "player_input": choice["label"],
            },
        )
    assert run["state"]["ending"]["kind"] == "good"
    assert run["presentation"]["resources"]["fog-lantern"] == "雾灯"
    assert run["presentation"]["relationships"]["lan"] == "岚"
    assert run["presentation"]["routes"]["lan-route"] == "岚路线"
    assert run["status"] == "completed"
    assert run["story_beats"][-1]["kind"] == "ending"
    with pytest.raises(CoreRuntimeError, match="run has ended"):
        runtime.play(
            run_id,
            {
                "request_id": "after-ending",
                "expected_revision": 3,
                "player_input": "继续前进",
                "commands": [{"type": "narrate", "payload": {}}],
            },
        )
    target = run["turns"][0]["id"]
    restored = runtime.rollback(
        run_id,
        {"request_id": "core-rollback", "expected_revision": 3, "target_turn_id": target},
    )
    assert restored["state"]["revision"] == 4
    assert restored["state"]["ending"] is None
    assert restored["status"] == "active"
    assert [(turn["sequence"], turn["kind"]) for turn in restored["turns"]] == [
        (1, "turn"),
        (2, "turn"),
        (3, "turn"),
        (4, "rollback"),
    ]


def test_existing_embedded_turns_gain_semantic_kinds_without_losing_history(tmp_path) -> None:
    database = tmp_path / "legacy-turns.db"
    runtime = LocalCoreRuntime(database)
    run_id = runtime.compose(fog_harbor_template())["run_id"]
    first = runtime.get_run(run_id)["available_choices"][0]
    played = runtime.choose(
        run_id,
        {
            "request_id": "legacy-turn",
            "expected_revision": 0,
            "choice_id": first["id"],
            "player_input": first["label"],
        },
    )
    runtime.rollback(
        run_id,
        {
            "request_id": "legacy-rollback",
            "expected_revision": 1,
            "target_turn_id": played["turns"][0]["id"],
        },
    )

    import sqlite3

    with sqlite3.connect(database) as connection:
        connection.execute("ALTER TABLE local_turns RENAME COLUMN kind TO legacy_kind")
    reopened = LocalCoreRuntime(database).get_run(run_id)

    assert [turn["kind"] for turn in reopened["turns"]] == ["turn", "rollback"]


def test_core_uses_world_version_run_state_aggregates_and_idempotent_request(tmp_path) -> None:
    database = tmp_path / "normalized.db"
    runtime = LocalCoreRuntime(database)
    composed = runtime.compose(fog_harbor_template())
    run_id = composed["run_id"]

    import sqlite3

    with sqlite3.connect(database) as connection:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
    assert {
        "local_worlds",
        "local_world_versions",
        "local_heroes",
        "local_runs",
        "local_story_beats",
        "local_turns",
    } <= tables

    choice = runtime.get_run(run_id)["available_choices"][0]
    request = {
        "request_id": "same-request",
        "expected_revision": 0,
        "choice_id": choice["id"],
        "player_input": choice["label"],
    }
    first = runtime.choose(run_id, request)
    second = runtime.choose(run_id, request)
    assert first["state"] == second["state"]
    assert len(second["turns"]) == 1
    assert second["story_beats"][1]["dialogue"]["speaker"] == "岚"
    assert any("获得" in item for item in second["story_beats"][1]["state_feedback"])


def test_core_cancelled_operation_is_rejected_at_the_commit_boundary(tmp_path) -> None:
    runtime = LocalCoreRuntime(tmp_path / "cancel.db")
    composed = runtime.compose(fog_harbor_template())
    run_id = composed["run_id"]
    choice = runtime.get_run(run_id)["available_choices"][0]
    request_id = "cancel-before-apply"
    assert runtime.begin_operation(request_id) is True
    assert runtime.cancel_operation(request_id) is True
    try:
        with pytest.raises(CoreRuntimeError, match="operation cancelled"):
            runtime.choose(
                run_id,
                {
                    "request_id": request_id,
                    "expected_revision": 0,
                    "choice_id": choice["id"],
                    "player_input": choice["label"],
                },
            )
    finally:
        runtime.finish_operation(request_id)
    restored = runtime.get_run(run_id)
    assert restored["state"]["revision"] == 0
    assert restored["turns"] == []


def test_core_starts_another_run_from_existing_world_and_reopens_opening(tmp_path) -> None:
    runtime = LocalCoreRuntime(tmp_path / "new-run.db")
    composed = runtime.compose(fog_harbor_template())
    created = runtime.create_run(
        composed["world_id"],
        {
            "request_id": "android-new-run",
            "world_version_id": composed["world_version_id"],
            "hero": {"name": "诺拉", "profile": {"origin": "测绘员"}},
        },
    )
    replay = runtime.create_run(
        composed["world_id"],
        {
            "request_id": "android-new-run",
            "world_version_id": composed["world_version_id"],
            "hero": {"name": "诺拉", "profile": {"origin": "测绘员"}},
        },
    )

    assert created["run_id"] != composed["run_id"]
    assert replay["created"] is False
    assert replay["run_id"] == created["run_id"]
    assert runtime.get_world(composed["world_id"])["runs"][0]["id"] == created["run_id"]
    reopened = LocalCoreRuntime(tmp_path / "new-run.db").get_run(created["run_id"])
    assert reopened["turns"] == []
    assert reopened["story_beats"][0]["dialogue"]["speaker"] == "岚"


def test_core_model_profiles_support_edit_default_and_safe_delete(tmp_path) -> None:
    runtime = LocalCoreRuntime(tmp_path / "models.db")
    first = runtime.create_model_profile(
        {
            "name": "Ollama",
            "provider_type": "ollama",
            "base_url": "http://127.0.0.1:11434/",
            "model_name": "qwen:7b",
        }
    )
    second = runtime.create_model_profile(
        {
            "name": "Studio",
            "provider_type": "lm_studio",
            "base_url": "http://127.0.0.1:1234/v1",
            "model_name": "qwen-14b",
        }
    )

    assert first["is_default"] is True
    assert second["is_default"] is False
    edited = runtime.update_model_profile(
        second["id"],
        {
            "name": "Studio 14B",
            "provider_type": "lm_studio",
            "base_url": "http://127.0.0.1:1234/v1/",
            "model_name": "qwen-14b-v2",
        },
    )
    assert edited["name"] == "Studio 14B"
    assert edited["base_url"] == "http://127.0.0.1:1234/v1"
    assert runtime.set_default_model_profile(second["id"])["is_default"] is True

    template = fog_harbor_template()
    runtime.compose({**template, "model_profile_id": second["id"]})
    with pytest.raises(CoreRuntimeError, match="正被 1 个 Run 使用"):
        runtime.delete_model_profile(second["id"])
    runtime.delete_model_profile(first["id"])
    assert [item["id"] for item in runtime.list_model_profiles()] == [second["id"]]


def test_core_portable_bundles_create_new_aggregate_ids(tmp_path) -> None:
    runtime = LocalCoreRuntime(tmp_path / "portable.db")
    source = runtime.compose(fog_harbor_template())
    world_bundle = runtime.export_world(source["world_id"])
    imported = runtime.import_world({"bundle": world_bundle})
    assert imported["world_id"] != source["world_id"]
    assert imported["world_version_id"] != source["world_version_id"]
    assert imported["run_id"] != source["run_id"]

    choice = runtime.get_run(source["run_id"])["available_choices"][0]
    runtime.choose(
        source["run_id"],
        {
            "request_id": "portable-choice",
            "expected_revision": 0,
            "choice_id": choice["id"],
            "player_input": choice["label"],
        },
    )
    cloned = runtime.clone_run({"bundle": runtime.export_run(source["run_id"])})
    assert cloned["run_id"] != source["run_id"]
    assert len(cloned["turns"]) == 1


def test_core_reopens_after_thirty_local_narrative_turns(tmp_path) -> None:
    runtime = LocalCoreRuntime(tmp_path / "long-play.db")
    composed = runtime.compose(fog_harbor_template())
    run_id = composed["run_id"]

    for index in range(30):
        current = runtime.get_run(run_id)
        current = runtime.play(
            run_id,
            {
                "request_id": f"long-play-{index}",
                "expected_revision": current["state"]["revision"],
                "player_input": f"继续观察第 {index + 1} 个片段",
                "commands": [{"type": "narrate", "payload": {}}],
            },
        )

    reopened = LocalCoreRuntime(tmp_path / "long-play.db").get_run(run_id)
    assert current["state"]["revision"] == 30
    assert len(reopened["turns"]) == 30
    assert reopened["state"]["ending"] is None


def test_model_probe_rejects_http_200_error_and_empty_protocol_content(tmp_path) -> None:
    import json
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            if self.path.endswith("/api/chat"):
                body = {"error": "unexpected endpoint or method"}
            else:
                body = {"choices": [{"message": {"content": ""}}]}
            payload = json.dumps(body).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *_args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        runtime = LocalCoreRuntime(tmp_path / "models.db")
        ollama = runtime.create_model_profile(
            {
                "name": "bad-ollama",
                "provider_type": "ollama",
                "base_url": f"http://127.0.0.1:{server.server_port}",
                "model_name": "qwen",
            }
        )
        lm_studio = runtime.create_model_profile(
            {
                "name": "empty-lm",
                "provider_type": "lm_studio",
                "base_url": f"http://127.0.0.1:{server.server_port}/v1",
                "model_name": "qwen",
            }
        )
        ollama_result = runtime.probe_model_profile(ollama["id"])
        assert ollama_result["success"] is False
        assert ollama_result["detail"] == "protocol response error: unexpected endpoint or method"
        assert (
            runtime.probe_model_profile(lm_studio["id"])["detail"]
            == "protocol response contains no content"
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_android_core_uses_run_model_for_narrative_and_keeps_failure_atomic(tmp_path) -> None:
    import json
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("content-length", "0"))
            request = json.loads(self.rfile.read(length) or b"{}")
            body = (
                {"error": "provider unavailable"}
                if request.get("model") == "broken"
                else {
                    "choices": [
                        {
                            "message": {
                                "content": "雾灯在掌心亮起。\n\n岚低声说：“潮门正在等你的下一个决定。”"
                            }
                        }
                    ]
                }
            )
            payload = json.dumps(body, ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *_args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        runtime = LocalCoreRuntime(tmp_path / "narrative.db")
        good = runtime.create_model_profile(
            {
                "name": "story",
                "provider_type": "lm_studio",
                "base_url": f"http://127.0.0.1:{server.server_port}/v1",
                "model_name": "story",
            }
        )
        template = fog_harbor_template()
        composed = runtime.compose({**template, "model_profile_id": good["id"]})
        choice = runtime.get_run(composed["run_id"])["available_choices"][0]
        advanced = runtime.choose(
            composed["run_id"],
            {
                "request_id": "narrated-choice",
                "expected_revision": 0,
                "choice_id": choice["id"],
                "player_input": choice["label"],
            },
        )
        assert "岚低声说" in advanced["turns"][0]["narrative"]
        assert advanced["story_beats"][1]["kind"] == "narrative"

        broken = runtime.create_model_profile(
            {
                "name": "broken",
                "provider_type": "lm_studio",
                "base_url": f"http://127.0.0.1:{server.server_port}/v1",
                "model_name": "broken",
            }
        )
        failed_run = runtime.create_run(
            composed["world_id"],
            {
                "request_id": "broken-run",
                "hero": {"name": "卡住前", "profile": {}},
                "model_profile_id": broken["id"],
            },
        )
        failed_choice = runtime.get_run(failed_run["run_id"])["available_choices"][0]
        with pytest.raises(CoreRuntimeError, match="model protocol error"):
            runtime.choose(
                failed_run["run_id"],
                {
                    "request_id": "failed-choice",
                    "expected_revision": 0,
                    "choice_id": failed_choice["id"],
                    "player_input": failed_choice["label"],
                },
            )
        unchanged = runtime.get_run(failed_run["run_id"])
        assert unchanged["state"]["revision"] == 0
        assert unchanged["turns"] == []
        assert len(unchanged["story_beats"]) == 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_model_draft_type_error_maps_to_explainable_safe_skeleton(tmp_path, monkeypatch) -> None:
    import json
    from copy import deepcopy

    from dzmm import core_runtime

    payload = fog_harbor_template()
    payload["world_definition"] = deepcopy(payload["world_definition"])
    payload["world_definition"]["story"]["relationships"][0]["dimensions"]["trust"] = 0
    monkeypatch.setattr(
        core_runtime,
        "request_world_draft",
        lambda _profile, _prompt: {"choices": [{"message": {"content": json.dumps(payload)}}]},
    )
    runtime = LocalCoreRuntime(tmp_path / "malformed-draft.db")
    profile = runtime.create_model_profile(
        {
            "name": "mock-lm",
            "provider_type": "lm_studio",
            "base_url": "http://127.0.0.1:1234/v1",
            "model_name": "mock",
        }
    )
    result = runtime.generate_draft({"model_profile_id": profile["id"], "ruleset": "hybrid"})
    assert result["valid"] is True
    assert any("受控 hybrid 规则骨架" in repair for repair in result["repairs"])
    assert runtime.list_worlds() == []


def test_android_core_uses_ephemeral_api_key_without_persisting_it(tmp_path, monkeypatch) -> None:
    import sqlite3

    from dzmm import embedded_model_profiles

    seen = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b'{"choices":[{"message":{"content":"OK"}}]}'

    def open_request(request, **_kwargs):
        seen["authorization"] = request.get_header("Authorization")
        return Response()

    monkeypatch.setattr(embedded_model_profiles.urllib.request, "urlopen", open_request)
    database = tmp_path / "secure-model.db"
    runtime = LocalCoreRuntime(database)
    profile = runtime.create_model_profile(
        {
            "name": "remote",
            "provider_type": "openai_compat",
            "base_url": "https://models.example/v1",
            "model_name": "story-large",
            "has_api_key": True,
        }
    )

    result = runtime.probe_model_profile(profile["id"], "sk-ephemeral")

    assert result["success"] is True
    assert seen["authorization"] == "Bearer sk-ephemeral"
    with sqlite3.connect(database) as connection:
        serialized = " ".join(
            value
            for row in connection.execute("SELECT * FROM local_model_profiles")
            for value in map(str, row)
        )
    assert "sk-ephemeral" not in serialized


def test_core_world_archive_blocks_new_and_existing_run_actions_until_restore(tmp_path) -> None:
    runtime = LocalCoreRuntime(tmp_path / "archive.db")
    composed = runtime.compose(fog_harbor_template())
    run_id = composed["run_id"]

    assert runtime.archive_world(composed["world_id"]) == {
        "world_id": composed["world_id"],
        "status": "archived",
    }
    assert runtime.list_worlds()[0]["status"] == "archived"
    assert runtime.get_world(composed["world_id"])["status"] == "archived"
    with pytest.raises(CoreRuntimeError, match="archived world cannot start a new run"):
        runtime.create_run(
            composed["world_id"],
            {
                "request_id": "archived-new-run",
                "hero": {"name": "归档旅人"},
            },
        )
    choice = runtime.get_run(run_id)["available_choices"][0]
    with pytest.raises(CoreRuntimeError, match="archived world cannot choose"):
        runtime.choose(
            run_id,
            {
                "request_id": "archived-choice",
                "expected_revision": 0,
                "choice_id": choice["id"],
                "player_input": choice["label"],
            },
        )
    assert runtime.restore_world(composed["world_id"])["status"] == "active"
    created = runtime.create_run(
        composed["world_id"],
        {"request_id": "restored-new-run", "hero": {"name": "恢复旅人"}},
    )
    assert created["created"] is True


def test_core_world_delete_cascades_runs_turns_and_history(tmp_path) -> None:
    runtime = LocalCoreRuntime(tmp_path / "delete.db")
    first = runtime.compose(fog_harbor_template())
    run = runtime.get_run(first["run_id"])
    runtime.choose(
        first["run_id"],
        {
            "request_id": "delete-turn",
            "expected_revision": run["state"]["revision"],
            "choice_id": run["available_choices"][0]["id"],
            "player_input": run["available_choices"][0]["label"],
        },
    )
    runtime.create_run(
        first["world_id"],
        {"request_id": "delete-run-2", "hero": {"name": "重玩者", "profile": {}}},
    )

    deleted = runtime.delete_world(first["world_id"])

    assert deleted["deleted_runs"] == 2
    assert runtime.list_worlds() == []
    with runtime._connect() as connection:
        for table in (
            "local_world_versions",
            "local_heroes",
            "local_runs",
            "local_turns",
            "local_story_beats",
            "local_run_create_requests",
        ):
            assert connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
