import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import httpx
import pytest

from dzmm_vnext.model_profiles import (
    ModelDraftGenerator,
    ModelNarrator,
    ModelProber,
    ModelProfile,
    NarrationError,
    NarrationRateLimitError,
    ProviderType,
)


class _MemorySecretStore:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def get(self, reference: str) -> str | None:
        return self.values.get(reference)

    def set(self, reference: str, value: str) -> None:
        self.values[reference] = value

    def delete(self, reference: str) -> None:
        self.values.pop(reference, None)


class _BlockingNarrator:
    def __init__(self) -> None:
        self.started = Event()
        self.release = Event()

    async def narrate(self, *_args, **_kwargs) -> str:
        self.started.set()
        await asyncio.to_thread(self.release.wait)
        return "岚抬头望向雾灯。"


async def collect_stream(narrator: ModelNarrator, profile: ModelProfile) -> list[str]:
    return [
        piece
        async for piece in narrator.stream(
            profile,
            {"name": "Fog Harbor"},
            {"hero": {"name": "Mira"}, "location_id": "lighthouse"},
            "I light the lamp.",
            [],
            [],
        )
    ]


def test_profile_requires_a_complete_provider_protocol(migrated_client) -> None:
    client, _ = migrated_client

    missing_v1 = client.post(
        "/api/v2/model-profiles",
        json={
            "name": "LM Studio",
            "provider_type": "lm_studio",
            "base_url": "http://localhost:1234",
            "model_name": "huihui-ai_qwen3-14b-abliterated",
        },
    )
    assert missing_v1.status_code == 422

    bad_ollama_root = client.post(
        "/api/v2/model-profiles",
        json={
            "name": "Ollama",
            "provider_type": "ollama",
            "base_url": "http://localhost:11434/v1",
            "model_name": "qwen3:8b",
        },
    )
    assert bad_ollama_root.status_code == 422

    created = client.post(
        "/api/v2/model-profiles",
        json={
            "name": "Desktop LM Studio",
            "provider_type": "lm_studio",
            "base_url": "http://desktop.local:1234/v1/",
            "model_name": "huihui-ai_qwen3-14b-abliterated",
        },
    )
    assert created.status_code == 201
    assert created.json()["base_url"] == "http://desktop.local:1234/v1"


def test_remote_model_credential_stays_out_of_sqlite_and_api_responses(
    migrated_client,
) -> None:
    client, database = migrated_client
    secrets = _MemorySecretStore()
    client.app.state.model_profiles._secret_store = secrets

    created = client.post(
        "/api/v2/model-profiles",
        json={
            "name": "Remote story model",
            "provider_type": "openai_compat",
            "base_url": "https://models.example/v1",
            "model_name": "story-large",
            "api_key": "sk-player-secret",
        },
    )

    assert created.status_code == 201
    body = created.json()
    assert body["has_api_key"] is True
    assert "api_key" not in body
    assert "api_key_ref" not in body
    assert list(secrets.values.values()) == ["sk-player-secret"]

    import sqlite3

    with sqlite3.connect(database) as connection:
        row = connection.execute(
            "SELECT api_key_ref FROM model_profiles WHERE id = ?", (body["id"],)
        ).fetchone()
        database_text = " ".join(
            value
            for record in connection.execute("SELECT * FROM model_profiles")
            for value in map(str, record)
        )
    assert row and row[0].startswith("profile:")
    assert "sk-player-secret" not in database_text

    deleted = client.delete(f"/api/v2/model-profiles/{body['id']}")
    assert deleted.status_code == 204
    assert secrets.values == {}


def test_model_requests_use_bearer_token_from_secure_store() -> None:
    seen: dict[str, str | None] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["authorization"] = request.headers.get("authorization")
        return httpx.Response(200, json={"choices": [{"message": {"content": "OK"}}]})

    secrets = _MemorySecretStore()
    secrets.set("profile:remote", "sk-runtime")
    profile = ModelProfile(
        id="remote",
        name="Remote",
        provider_type=ProviderType.OPENAI_COMPAT,
        base_url="https://models.example/v1",
        model_name="story-large",
        api_key_ref="profile:remote",
        has_api_key=True,
    )

    result = asyncio.run(
        ModelProber(httpx.MockTransport(handler), secret_store=secrets).probe(profile)
    )

    assert result.success is True
    assert seen["authorization"] == "Bearer sk-runtime"


def test_cancelling_slow_narration_preserves_original_run(migrated_client) -> None:
    client, _ = migrated_client
    profile = client.post(
        "/api/v2/model-profiles",
        json={
            "name": "Slow local model",
            "provider_type": "ollama",
            "base_url": "http://127.0.0.1:11434",
            "model_name": "qwen:slow",
        },
    ).json()
    template = client.get("/api/v2/world-templates/fog-harbor").json()
    composed = client.post(
        "/api/v2/worlds:compose",
        json={
            "request_id": "cancel-world",
            "model_profile_id": profile["id"],
            **template,
        },
    ).json()
    narrator = _BlockingNarrator()
    client.app.state.turn_coordinator._narrator = narrator
    request_id = "cancel-slow-turn"
    choice = client.get(f"/api/v2/runs/{composed['run_id']}").json()["available_choices"][0]

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(
            client.post,
            f"/api/v2/runs/{composed['run_id']}/choices",
            json={
                "request_id": request_id,
                "expected_revision": 0,
                "choice_id": choice["id"],
                "player_input": choice["label"],
            },
        )
        assert narrator.started.wait(timeout=2)
        cancelled = client.post(f"/api/v2/operations/{request_id}:cancel")
        assert cancelled.json()["accepted"] is True
        narrator.release.set()
        result = future.result(timeout=2)

    assert result.status_code == 409
    assert "cancelled" in result.json()["detail"]
    restored = client.get(f"/api/v2/runs/{composed['run_id']}").json()
    assert restored["state"]["revision"] == 0
    assert restored["turns"] == []
    assert len(restored["story_beats"]) == 1


def test_lm_studio_http_200_error_is_not_a_successful_probe() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"error": "Unexpected endpoint or method"})

    profile = ModelProfile(
        id="profile-1",
        name="LM Studio",
        provider_type=ProviderType.LM_STUDIO,
        base_url="http://desktop.local:1234/v1",
        model_name="huihui-ai_qwen3-14b-abliterated",
    )
    result = asyncio.run(ModelProber(httpx.MockTransport(handler)).probe(profile))

    assert result.success is False
    assert seen["url"] == "http://desktop.local:1234/v1/chat/completions"
    assert seen["body"] == {
        "model": "huihui-ai_qwen3-14b-abliterated",
        "messages": [{"role": "user", "content": "Reply with OK."}],
        "stream": False,
        "max_tokens": 8,
    }


def test_probe_requires_non_empty_protocol_content() -> None:
    profile = ModelProfile(
        id="profile-2",
        name="Ollama",
        provider_type=ProviderType.OLLAMA,
        base_url="http://localhost:11434",
        model_name="qwen3:8b",
    )
    empty = asyncio.run(
        ModelProber(
            httpx.MockTransport(lambda _: httpx.Response(200, json={"message": {"content": ""}}))
        ).probe(profile)
    )
    successful = asyncio.run(
        ModelProber(
            httpx.MockTransport(lambda _: httpx.Response(200, json={"message": {"content": "OK"}}))
        ).probe(profile)
    )

    assert empty.success is False
    assert successful.success is True


def test_narrator_only_accepts_protocol_valid_content() -> None:
    profile = ModelProfile(
        id="profile-3",
        name="LM Studio",
        provider_type=ProviderType.LM_STUDIO,
        base_url="http://desktop.local:1234/v1",
        model_name="huihui-ai_qwen3-14b-abliterated",
    )
    narrator = ModelNarrator(
        httpx.MockTransport(
            lambda _: httpx.Response(
                200, json={"choices": [{"message": {"content": "灯塔亮起。"}}]}
            )
        )
    )
    narrative = asyncio.run(
        narrator.narrate(
            profile,
            {"name": "Fog Harbor"},
            {"hero": {"name": "Mira"}, "location_id": "lighthouse"},
            "I light the lamp.",
            [{"type": "move", "location_id": "lighthouse"}],
            [],
        )
    )

    assert narrative == "灯塔亮起。"


def test_narrator_reports_a_provider_error_detail() -> None:
    profile = ModelProfile(
        id="profile-error-detail",
        name="Ollama",
        provider_type=ProviderType.OLLAMA,
        base_url="http://localhost:11434",
        model_name="sakura",
    )
    narrator = ModelNarrator(
        httpx.MockTransport(lambda _: httpx.Response(500, json={"error": "model is overloaded"}))
    )

    with pytest.raises(NarrationError, match="HTTP 500: model is overloaded"):
        asyncio.run(
            narrator.narrate(
                profile,
                {"name": "Fog Harbor"},
                {"hero": {"name": "Mira"}, "location_id": "lighthouse"},
                "I light the lamp.",
                [],
                [],
            )
        )


def test_narrator_turns_timeout_into_actionable_player_feedback() -> None:
    profile = ModelProfile(
        id="profile-timeout-detail",
        name="Ollama",
        provider_type=ProviderType.OLLAMA,
        base_url="http://localhost:11434",
        model_name="sakura",
    )
    narrator = ModelNarrator(
        httpx.MockTransport(lambda _: (_ for _ in ()).throw(httpx.ReadTimeout("")))
    )

    with pytest.raises(
        NarrationError,
        match="模型在 120 秒内没有返回内容.*没有写入结果.*重试",
    ):
        asyncio.run(
            narrator.narrate(
                profile,
                {"name": "Fog Harbor"},
                {"hero": {"name": "Mira"}, "location_id": "lighthouse"},
                "I light the lamp.",
                [],
                [],
            )
        )


def test_model_probe_uses_its_short_timeout_in_player_feedback() -> None:
    profile = ModelProfile(
        id="profile-probe-timeout",
        name="Ollama",
        provider_type=ProviderType.OLLAMA,
        base_url="http://localhost:11434",
        model_name="sakura",
    )
    prober = ModelProber(
        httpx.MockTransport(lambda _: (_ for _ in ()).throw(httpx.ConnectTimeout("")))
    )

    result = asyncio.run(prober.probe(profile))

    assert result.success is False
    assert result.detail.startswith("模型在 10 秒内没有返回内容。")
    assert "没有写入结果" in result.detail


def test_stream_timeout_uses_the_same_player_feedback() -> None:
    profile = ModelProfile(
        id="profile-stream-timeout",
        name="LM Studio",
        provider_type=ProviderType.LM_STUDIO,
        base_url="http://localhost:1234/v1",
        model_name="sakura",
    )
    narrator = ModelNarrator(
        httpx.MockTransport(lambda _: (_ for _ in ()).throw(httpx.ReadTimeout("")))
    )

    with pytest.raises(NarrationError, match="模型在 120 秒内没有返回内容"):
        asyncio.run(collect_stream(narrator, profile))


def test_narrator_describes_validated_narrative_state_without_granting_state_authority() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "岚接过证词。"}}]})

    profile = ModelProfile(
        id="profile-narrative",
        name="LM Studio",
        provider_type=ProviderType.LM_STUDIO,
        base_url="http://desktop.local:1234/v1",
        model_name="huihui-ai_qwen3-14b-abliterated",
    )
    narrative = asyncio.run(
        ModelNarrator(httpx.MockTransport(handler)).narrate(
            profile,
            {"name": "雾港"},
            {
                "hero": {"name": "米拉"},
                "location_id": "harbor",
                "ruleset": {"id": "hybrid"},
                "chapter": {"id": "ch2", "status": "active", "resolved_choice_ids": []},
                "route": {"id": "lan-route", "status": "locked"},
                "relationships": {"lan": {"dimensions": {"trust": 40}}},
                "ending": None,
                "narrative_context": {
                    "recent_turns": [
                        {
                            "turn": 1,
                            "player_input": "观察潮水",
                            "narrative": "潮水退去，露出一枚生锈的钥匙。",
                            "outcomes": [],
                        }
                    ]
                },
            },
            "把证词交给岚",
            [{"type": "lock_route", "route_id": "lan-route"}],
            [],
            variation_seed="run-a",
        )
    )

    assert narrative == "岚接过证词。"
    system = seen["body"]["messages"][0]["content"]
    payload = json.loads(seen["body"]["messages"][1]["content"].removeprefix("/no_think\n"))
    assert "不是状态裁判" in system
    assert "不得输出 JSON、标签、Markdown 标题、列表或状态摘要" in system
    assert seen["body"]["max_tokens"] == 480
    assert seen["body"]["temperature"] == 0.85
    assert seen["body"]["top_p"] == 0.9
    assert payload["ruleset"] == "hybrid"
    assert payload["chapter"]["id"] == "ch2"
    assert payload["relationships"]["lan"]["dimensions"]["trust"] == 40
    assert payload["narrative_memory"][0]["player_input"] == "观察潮水"
    assert payload["variation_directive"]["key"]


def test_narrator_removes_qwen_rp_wrapper_and_json_echo() -> None:
    profile = ModelProfile(
        id="profile-4",
        name="LM Studio",
        provider_type=ProviderType.LM_STUDIO,
        base_url="http://desktop.local:1234/v1",
        model_name="huihui-ai_qwen3-14b-abliterated",
    )
    wrapped = '### TRPG Narrative:\n### 灯塔的微光摇曳。\n\n### JSON:\n{"narrative": "ignored"}'
    narrator = ModelNarrator(
        httpx.MockTransport(
            lambda _: httpx.Response(200, json={"choices": [{"message": {"content": wrapped}}]})
        )
    )

    narrative = asyncio.run(
        narrator.narrate(
            profile,
            {"name": "Fog Harbor"},
            {"hero": {"name": "Mira"}, "location_id": "lighthouse"},
            "I light the lamp.",
            [],
            [],
        )
    )

    assert narrative == "灯塔的微光摇曳。"


def test_narrator_removes_accidental_technical_state_summary() -> None:
    profile = ModelProfile(
        id="profile-state-summary",
        name="Ollama",
        provider_type=ProviderType.OLLAMA,
        base_url="http://localhost:11434",
        model_name="qwen3:8b",
    )
    content = (
        "迷雾灯在掌心亮起，岚压低声音：‘潮门就在前面。’\n\n"
        "雾港浏览器： - 当前章节：第2章（正在进行） - 主角：第二位旅人 "
        "- 目的地：海港 - 特殊物品：迷雾灯"
    )
    narrator = ModelNarrator(
        httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json={
                    "message": {"content": content},
                    "done": True,
                    "done_reason": "stop",
                },
            )
        )
    )

    narrative = asyncio.run(
        narrator.narrate(
            profile,
            {"name": "雾港"},
            {"hero": {"name": "第二位旅人"}, "location_id": "harbor"},
            "点亮迷雾灯",
            [],
            [],
        )
    )

    assert narrative == "迷雾灯在掌心亮起，岚压低声音：‘潮门就在前面。’"


def test_narrator_rejects_provider_reported_truncation() -> None:
    profile = ModelProfile(
        id="profile-truncated",
        name="Ollama",
        provider_type=ProviderType.OLLAMA,
        base_url="http://localhost:11434",
        model_name="qwen3:8b",
    )
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "message": {"content": "身后海浪翻滚的声音逐渐接近，似乎"},
                "done": True,
                "done_reason": "length",
            },
        )

    narrator = ModelNarrator(httpx.MockTransport(handler))
    with pytest.raises(NarrationError, match="narrative was truncated"):
        asyncio.run(
            narrator.narrate(
                profile,
                {"name": "雾港"},
                {"hero": {"name": "旅人"}, "location_id": "harbor"},
                "继续前进",
                [],
                [],
            )
        )

    assert seen["body"]["options"]["num_predict"] == 384


def test_narrator_streams_openai_deltas_only_after_protocol_completion() -> None:
    profile = ModelProfile(
        id="profile-stream",
        name="LM Studio",
        provider_type=ProviderType.LM_STUDIO,
        base_url="http://desktop.local:1234/v1",
        model_name="huihui-ai_qwen3-14b-abliterated",
    )
    response = (
        'data: {"choices":[{"delta":{"content":"灯塔"}}]}\n'
        'data: {"choices":[{"delta":{"content":"亮起。"}}]}\n'
        "data: [DONE]"
    ).encode()
    narrator = ModelNarrator(httpx.MockTransport(lambda _: httpx.Response(200, content=response)))

    assert asyncio.run(collect_stream(narrator, profile)) == ["灯塔", "亮起。"]


def test_narrator_rejects_provider_reported_stream_truncation() -> None:
    profile = ModelProfile(
        id="profile-stream-truncated",
        name="LM Studio",
        provider_type=ProviderType.LM_STUDIO,
        base_url="http://desktop.local:1234/v1",
        model_name="qwen3-8b",
    )
    response = (
        'data: {"choices":[{"delta":{"content":"灯塔仍在"}}]}\n'
        'data: {"choices":[{"delta":{},"finish_reason":"length"}]}\n'
    ).encode()
    narrator = ModelNarrator(httpx.MockTransport(lambda _: httpx.Response(200, content=response)))

    with pytest.raises(NarrationError, match="narrative was truncated"):
        asyncio.run(collect_stream(narrator, profile))


def test_draft_generator_uses_lm_studio_text_json_with_a_restricted_prompt() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": '{"world_name":"雾港","summary":"潮门","hero":{"name":"米拉","origin":"水手"},"locations":["码头","灯塔"],"characters":[],"lore":[]}'
                        }
                    }
                ]
            },
        )

    profile = ModelProfile(
        id="profile-draft",
        name="LM Studio",
        provider_type=ProviderType.LM_STUDIO,
        base_url="http://desktop.local:1234/v1",
        model_name="huihui-ai_qwen3-14b-abliterated",
    )
    payload, repairs = asyncio.run(
        ModelDraftGenerator(httpx.MockTransport(handler)).generate(
            profile,
            {
                "system": "JSON only; no command.",
                "brief": {"genre": "mystery"},
                "first_slice": "three chapters",
            },
        )
    )

    assert payload["world_name"] == "雾港"
    assert repairs == []
    body = seen["body"]
    assert "response_format" not in body
    assert body["chat_template_kwargs"] == {"enable_thinking": False}
    assert body["messages"][0]["content"] == "JSON only; no command."


def test_narrator_rejects_empty_malformed_and_rate_limited_streams() -> None:
    profile = ModelProfile(
        id="profile-stream-errors",
        name="LM Studio",
        provider_type=ProviderType.LM_STUDIO,
        base_url="http://desktop.local:1234/v1",
        model_name="huihui-ai_qwen3-14b-abliterated",
    )
    for response, error in [
        (httpx.Response(200, content=b"data: not-json"), "malformed SSE JSON"),
        (httpx.Response(429), "HTTP 429"),
    ]:
        narrator = ModelNarrator(httpx.MockTransport(lambda _, response=response: response))
        expected = NarrationRateLimitError if response.status_code == 429 else NarrationError
        with pytest.raises(expected, match=error):
            asyncio.run(collect_stream(narrator, profile))
