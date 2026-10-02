"""Transport-independent model endpoint and response protocol helpers."""

from __future__ import annotations

from typing import Any

SUPPORTED_PROVIDER_TYPES = frozenset({"ollama", "lm_studio", "openai_compat"})

# 模型名 → Ollama 上下文推断；显式 context_size 永远优先
OLLAMA_CONTEXT_MARKERS = (
    ("128k", 131072),
    ("64k", 65536),
    ("32k", 32768),
    ("16k", 16384),
    ("8k", 8192),
)
OLLAMA_DEFAULT_CONTEXT = 16384


def ollama_context_size(model_name: str, context_size: int | None = None) -> int:
    if context_size:
        return context_size
    lowered = (model_name or "").lower()
    for marker, size in OLLAMA_CONTEXT_MARKERS:
        if marker in lowered:
            return size
    return OLLAMA_DEFAULT_CONTEXT


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


def probe_body(
    provider_type: str, model_name: str, context_size: int | None = None
) -> dict[str, Any]:
    messages = [{"role": "user", "content": "Reply with OK."}]
    body: dict[str, Any] = {"model": model_name, "messages": messages, "stream": False}
    if provider_type == "ollama":
        # qwen3.5 思考模式会拖垮测试连接；原生 think 开关对非思考模型无害。
        # num_ctx 与游玩请求一致：否则探针会按 Ollama 默认 4096 加载模型，
        # 用户在服务端看到/复用的就是错误上下文。
        body["think"] = False
        body["options"] = {"num_ctx": ollama_context_size(model_name, context_size)}
    else:
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
