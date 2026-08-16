import asyncio
import json

import httpx

from dzmm_vnext.model_profiles import ModelNarrator, ModelProber, ModelProfile, ProviderType


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
        ModelProber(httpx.MockTransport(lambda _: httpx.Response(200, json={"message": {"content": ""}}))).probe(
            profile
        )
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
            lambda _: httpx.Response(200, json={"choices": [{"message": {"content": "灯塔亮起。"}}]})
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


def test_narrator_removes_qwen_rp_wrapper_and_json_echo() -> None:
    profile = ModelProfile(
        id="profile-4",
        name="LM Studio",
        provider_type=ProviderType.LM_STUDIO,
        base_url="http://desktop.local:1234/v1",
        model_name="huihui-ai_qwen3-14b-abliterated",
    )
    wrapped = "### TRPG Narrative:\n### 灯塔的微光摇曳。\n\n### JSON:\n{\"narrative\": \"ignored\"}"
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
