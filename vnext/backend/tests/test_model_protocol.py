import pytest

from dzmm_vnext.model_protocol import chat_content, chat_endpoint, probe_body


def test_chat_endpoint_keeps_provider_protocol_boundaries() -> None:
    assert chat_endpoint("ollama", "http://localhost:11434/") == (
        "http://localhost:11434/api/chat"
    )
    assert chat_endpoint("lm_studio", "http://localhost:1234/v1/") == (
        "http://localhost:1234/v1/chat/completions"
    )
    assert chat_endpoint("openai_compat", "https://provider.example/v1") == (
        "https://provider.example/v1/chat/completions"
    )


@pytest.mark.parametrize(
    ("provider_type", "base_url", "message"),
    [
        ("ollama", "http://localhost:11434/v1", "server root"),
        ("lm_studio", "http://localhost:1234", "must end with /v1"),
        ("unknown", "http://localhost:1", "unsupported"),
    ],
)
def test_chat_endpoint_rejects_mismatched_protocols(
    provider_type: str, base_url: str, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        chat_endpoint(provider_type, base_url)


def test_chat_content_rejects_200_error_and_empty_protocol_bodies() -> None:
    assert chat_content("ollama", {"error": "wrong endpoint"}) is None
    assert chat_content("ollama", {"message": {"content": "OK"}}) == "OK"
    assert chat_content("lm_studio", {"choices": []}) is None
    assert (
        chat_content("lm_studio", {"choices": [{"message": {"content": "ready"}}]})
        == "ready"
    )


def test_probe_body_limits_openai_compatible_probe_output() -> None:
    assert "max_tokens" not in probe_body("ollama", "qwen")
    assert probe_body("lm_studio", "qwen")["max_tokens"] == 8
