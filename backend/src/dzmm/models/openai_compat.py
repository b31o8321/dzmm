import json
from collections.abc import AsyncIterator

import httpx

from dzmm.models.client import (
    GenerationParams,
    Message,
    ModelClient,
    StreamChunk,
    TokenUsage,
)


class OpenAICompatClient(ModelClient):
    """Works for OpenAI, Doubao, Tongyi, DeepSeek, 零一万物 — any provider
    exposing an OpenAI /chat/completions-shaped endpoint."""

    def __init__(
        self,
        name: str,
        base_url: str,
        api_key: str,
        model: str,
        timeout: float = 60.0,
    ):
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        # None = untested, True = supported, False = not supported (e.g. LM Studio)
        self._json_mode_supported: bool | None = None

    def _build_headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def _raw_stream(
        self,
        messages: list[Message],
        params: GenerationParams,
        use_json_mode: bool,
    ) -> AsyncIterator[StreamChunk]:
        payload: dict = {
            "model": self.model,
            "messages": [m.model_dump() for m in messages],
            "temperature": params.temperature,
            "max_tokens": params.max_tokens,
            "top_p": params.top_p,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if params.stop:
            payload["stop"] = params.stop
        if use_json_mode:
            payload["response_format"] = {"type": "json_object"}

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/chat/completions",
                json=payload,
                headers=self._build_headers(),
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line or not line.startswith("data: "):
                        continue
                    data = line[6:]
                    if data == "[DONE]":
                        break
                    try:
                        obj = json.loads(data)
                    except json.JSONDecodeError:
                        continue

                    choices = obj.get("choices") or []
                    delta = ""
                    finish = None
                    if choices:
                        delta = (choices[0].get("delta") or {}).get("content") or ""
                        finish = choices[0].get("finish_reason")

                    usage = None
                    raw_usage = obj.get("usage")
                    if raw_usage:
                        usage = TokenUsage(
                            input_tokens=raw_usage.get("prompt_tokens", 0),
                            output_tokens=raw_usage.get("completion_tokens", 0),
                        )

                    if delta or finish or usage:
                        yield StreamChunk(delta=delta, finish_reason=finish, usage=usage)

    async def stream(
        self,
        messages: list[Message],
        params: GenerationParams,
    ) -> AsyncIterator[StreamChunk]:
        want_json = params.json_mode and self._json_mode_supported is not False

        if not want_json:
            async for chunk in self._raw_stream(messages, params, use_json_mode=False):
                yield chunk
            return

        # Try with json_mode; fall back silently if the server rejects it (400)
        collected: list[StreamChunk] = []
        try:
            async for chunk in self._raw_stream(messages, params, use_json_mode=True):
                collected.append(chunk)
                yield chunk
            self._json_mode_supported = True
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 400 and not collected:
                # Server doesn't support response_format — retry without it
                self._json_mode_supported = False
                async for chunk in self._raw_stream(messages, params, use_json_mode=False):
                    yield chunk
            else:
                raise
