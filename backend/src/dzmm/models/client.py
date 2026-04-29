from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Literal

from pydantic import BaseModel


class Message(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class GenerationParams(BaseModel):
    temperature: float = 0.8
    max_tokens: int = 1500
    top_p: float = 0.95
    stop: list[str] | None = None


class TokenUsage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0


class StreamChunk(BaseModel):
    delta: str = ""
    finish_reason: str | None = None
    usage: TokenUsage | None = None


class ModelClient(ABC):
    name: str

    @abstractmethod
    def stream(
        self,
        messages: list[Message],
        params: GenerationParams,
    ) -> AsyncIterator[StreamChunk]:
        """Stream completion. Implementations are async generators."""
        ...

    async def complete(
        self,
        messages: list[Message],
        params: GenerationParams,
    ) -> tuple[str, TokenUsage]:
        parts: list[str] = []
        usage = TokenUsage()
        async for chunk in self.stream(messages, params):
            parts.append(chunk.delta)
            if chunk.usage is not None:
                usage = chunk.usage
        return "".join(parts), usage

    async def health_check(self) -> tuple[bool, str]:
        try:
            text, _ = await self.complete(
                [Message(role="user", content="Reply with the single word: ok")],
                GenerationParams(max_tokens=10, temperature=0.0),
            )
            return True, text.strip()
        except Exception as e:  # noqa: BLE001
            return False, f"{type(e).__name__}: {e}"
