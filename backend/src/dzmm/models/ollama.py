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


class OllamaClient(ModelClient):
    def __init__(
        self,
        name: str,
        base_url: str,
        model: str,
        timeout: float = 120.0,
    ):
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    async def stream(
        self,
        messages: list[Message],
        params: GenerationParams,
    ) -> AsyncIterator[StreamChunk]:
        payload: dict = {
            "model": self.model,
            "messages": [m.model_dump() for m in messages],
            "stream": True,
            "options": {
                "temperature": params.temperature,
                "num_predict": params.max_tokens,
                "top_p": params.top_p,
                "stop": params.stop or [],
                "num_ctx": 8192,
            },
        }
        if params.json_mode:
            payload["format"] = "json"

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            async with client.stream(
                "POST", f"{self.base_url}/api/chat", json=payload,
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    delta = (obj.get("message") or {}).get("content", "")
                    done = obj.get("done", False)

                    usage = None
                    if done:
                        usage = TokenUsage(
                            input_tokens=obj.get("prompt_eval_count", 0),
                            output_tokens=obj.get("eval_count", 0),
                        )

                    yield StreamChunk(
                        delta=delta,
                        finish_reason="stop" if done else None,
                        usage=usage,
                    )

    async def list_models(self) -> list[str]:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{self.base_url}/api/tags")
            resp.raise_for_status()
            return [m["name"] for m in resp.json().get("models", [])]
