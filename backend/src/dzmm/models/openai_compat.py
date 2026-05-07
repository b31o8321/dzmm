import asyncio
import json
import logging
from collections.abc import AsyncIterator

import httpx

from dzmm.models.client import (
    GenerationParams,
    Message,
    ModelClient,
    StreamChunk,
    TokenUsage,
)

log = logging.getLogger(__name__)

# 429 backoff: respect Retry-After when present, otherwise grow exponentially
# from 1.5s. 4 attempts total (= 3 retries) tolerates short rate-limit bursts
# from cloud providers (Zhipu / OpenAI / Moonshot) without making the user wait
# more than ~10s in the worst case.
_MAX_429_RETRIES = 3
_429_BASE_DELAY = 1.5
_429_MAX_DELAY = 8.0


def _parse_retry_after(value: str | None) -> float | None:
    """RFC 7231: Retry-After is either delta-seconds or HTTP-date. We only
    handle delta-seconds (the common case for cloud LLM providers)."""
    if not value:
        return None
    try:
        return max(0.0, float(value.strip()))
    except (TypeError, ValueError):
        return None


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
        concurrency_gate: asyncio.Semaphore | None = None,
    ):
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        # None = untested, True = supported, False = not supported (e.g. LM Studio)
        self._json_mode_supported: bool | None = None
        # Process-wide gate (typically max_concurrent=1 for Zhipu free tier).
        # When set, the entire stream() — including all retries and chunks —
        # runs inside the semaphore, so any concurrent caller waits its turn.
        self._concurrency_gate = concurrency_gate

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
        """Stream with 429 retry. Retries are only safe BEFORE the first chunk
        is yielded — once we've started streaming to the caller, retrying
        would produce duplicate output. So 429s mid-stream are surfaced as
        errors (rare; cloud providers normally apply rate limit at request
        admission, not mid-response).
        """
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

        attempt = 0
        while True:
            try:
                async for chunk in self._do_request(payload):
                    yield chunk
                return  # success
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code != 429 or attempt >= _MAX_429_RETRIES:
                    raise
                retry_after = _parse_retry_after(exc.response.headers.get("Retry-After"))
                delay = retry_after if retry_after is not None else min(
                    _429_BASE_DELAY * (2 ** attempt), _429_MAX_DELAY,
                )
                attempt += 1
                log.info(
                    "openai_compat 429 from %s (attempt %d/%d); sleeping %.1fs before retry",
                    self.base_url, attempt, _MAX_429_RETRIES, delay,
                )
                await asyncio.sleep(delay)

    async def _do_request(self, payload: dict) -> AsyncIterator[StreamChunk]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/chat/completions",
                json=payload,
                headers=self._build_headers(),
            ) as resp:
                if resp.status_code == 429:
                    # Read body so the connection can be reused / closed cleanly,
                    # then raise so the retry layer in _raw_stream can react.
                    await resp.aread()
                    resp.raise_for_status()  # raises HTTPStatusError
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
        if self._concurrency_gate is None:
            async for chunk in self._stream_inner(messages, params):
                yield chunk
            return

        # Hold the gate for the entire stream — including retries and all chunk
        # iteration. The provider's concurrency limit applies to the wire-level
        # request, so we must own the slot from request start to last chunk.
        #
        # We use explicit acquire/release (instead of `async with`) plus
        # logging so leaks are diagnosable: a missing "released" line means
        # the consumer broke iteration without aclose-ing this generator.
        # Async generators' finally clauses run on:
        #   - natural completion (full iteration) — common path
        #   - explicit aclose() (e.g. anyio TaskGroup cancellation) — works
        #   - GeneratorExit injected by GC — eventually works, but delayed
        #     until next GC cycle, which under high load can leave the
        #     semaphore held for many seconds.
        import time
        wait_t0 = time.monotonic()
        await self._concurrency_gate.acquire()
        wait_ms = int((time.monotonic() - wait_t0) * 1000)
        acquire_t0 = time.monotonic()
        held_for_warned = False
        log.info(
            "openai_compat: gate ACQUIRED for %s (waited %dms)",
            self.base_url, wait_ms,
        )
        try:
            async for chunk in self._stream_inner(messages, params):
                if not held_for_warned and (time.monotonic() - acquire_t0) > 60.0:
                    log.warning(
                        "openai_compat: gate held >60s for %s/%s — possible stuck stream",
                        self.base_url, self.model,
                    )
                    held_for_warned = True
                yield chunk
        except BaseException as e:
            # Catch BaseException (incl. GeneratorExit / CancelledError) so we
            # log when an early exit happens — the most likely leak path.
            log.info(
                "openai_compat: gate path exiting via %s for %s",
                type(e).__name__, self.base_url,
            )
            raise
        finally:
            held_ms = int((time.monotonic() - acquire_t0) * 1000)
            self._concurrency_gate.release()
            log.info(
                "openai_compat: gate RELEASED after %dms for %s",
                held_ms, self.base_url,
            )

    async def _stream_inner(
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
