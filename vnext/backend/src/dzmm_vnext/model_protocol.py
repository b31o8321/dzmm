"""Transport-independent model endpoint and response protocol helpers."""

from __future__ import annotations

from typing import Any

SUPPORTED_PROVIDER_TYPES = frozenset({"ollama", "lm_studio", "openai_compat"})


def chat_endpoint(provider_type: str, base_url: str) -> str:
    if provider_type not in SUPPORTED_PROVIDER_TYPES:
        raise ValueError("unsupported model provider type")
    normalized = base_url.rstrip("/")
    if provider_type == "ollama":
        if normalized.endswith("/v1"):
            raise ValueError("Ollama base_url must be the server root, not an OpenAI /v1 root")
        return f"{normalized}/api/chat"
    if not normalized.endswith("/v1"):
        raise ValueError("LM Studio and OpenAI-compatible base_url must end with /v1")
    return f"{normalized}/chat/completions"


def probe_body(provider_type: str, model_name: str) -> dict[str, Any]:
    messages = [{"role": "user", "content": "Reply with OK."}]
    body: dict[str, Any] = {"model": model_name, "messages": messages, "stream": False}
    if provider_type != "ollama":
        body["max_tokens"] = 8
    return body


def chat_content(provider_type: str, payload: Any) -> str | None:
    if not isinstance(payload, dict) or payload.get("error"):
        return None
    if provider_type == "ollama":
        message = payload.get("message")
        return message.get("content") if isinstance(message, dict) else None
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        return None
    message = choices[0].get("message")
    return message.get("content") if isinstance(message, dict) else None
