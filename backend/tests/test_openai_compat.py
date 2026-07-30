import json
import httpx
import pytest
import respx

from dzmm.models.client import GenerationParams, Message
from dzmm.models.openai_compat import OpenAICompatClient


def sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


@pytest.fixture
def client():
    return OpenAICompatClient(
        name="test", base_url="https://api.example.com/v1",
        api_key="sk-test", model="test-model", timeout=5.0,
    )


@respx.mock
async def test_stream_yields_deltas_and_usage(client):
    body = (
        sse({"choices": [{"delta": {"content": "Hello"}, "finish_reason": None}]})
        + sse({"choices": [{"delta": {"content": " world"}, "finish_reason": None}]})
        + sse({"choices": [{"delta": {}, "finish_reason": "stop"}],
               "usage": {"prompt_tokens": 12, "completion_tokens": 3}})
        + "data: [DONE]\n\n"
    )
    respx.post("https://api.example.com/v1/chat/completions").mock(
        return_value=httpx.Response(200, text=body,
                                    headers={"content-type": "text/event-stream"})
    )

    chunks = []
    async for ch in client.stream(
        [Message(role="user", content="hi")], GenerationParams(),
    ):
        chunks.append(ch)

    text = "".join(c.delta for c in chunks)
    assert text == "Hello world"
    final = chunks[-1]
    assert final.finish_reason == "stop"
    assert final.usage is not None
    assert final.usage.input_tokens == 12
    assert final.usage.output_tokens == 3


@respx.mock
async def test_stream_handles_malformed_lines(client):
    body = (
        "garbage line\n\n"
        + sse({"choices": [{"delta": {"content": "ok"}, "finish_reason": None}]})
        + "data: not-json\n\n"
        + "data: [DONE]\n\n"
    )
    respx.post("https://api.example.com/v1/chat/completions").mock(
        return_value=httpx.Response(200, text=body)
    )

    text, _ = await client.complete(
        [Message(role="user", content="hi")], GenerationParams(),
    )
    assert text == "ok"


@respx.mock
async def test_stream_rejects_http_200_json_protocol_error(client):
    respx.post("https://api.example.com/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={
            "error": "Unexpected endpoint or method POST /api/chat",
        })
    )

    with pytest.raises(RuntimeError, match="HTTP 200 but no SSE data"):
        async for _ in client.stream(
            [Message(role="user", content="hi")], GenerationParams(),
        ):
            pass


@respx.mock
async def test_stream_rejects_error_inside_sse(client):
    respx.post("https://api.example.com/v1/chat/completions").mock(
        return_value=httpx.Response(200, text=sse({"error": {"message": "model not loaded"}}))
    )

    with pytest.raises(RuntimeError, match="model not loaded"):
        async for _ in client.stream(
            [Message(role="user", content="hi")], GenerationParams(),
        ):
            pass


@respx.mock
async def test_stream_raises_on_4xx(client):
    respx.post("https://api.example.com/v1/chat/completions").mock(
        return_value=httpx.Response(401, json={"error": "unauthorized"})
    )

    with pytest.raises(httpx.HTTPStatusError):
        async for _ in client.stream(
            [Message(role="user", content="hi")], GenerationParams(),
        ):
            pass


@respx.mock
async def test_stream_retries_on_429_then_succeeds(client, monkeypatch):
    """429 → backoff → retry → success. Verifies the retry layer works
    end-to-end and that final output is correct."""
    # Patch sleep to avoid real waits
    sleeps: list[float] = []

    async def fake_sleep(s: float) -> None:
        sleeps.append(s)

    monkeypatch.setattr("dzmm.models.openai_compat.asyncio.sleep", fake_sleep)

    success_body = (
        sse({"choices": [{"delta": {"content": "ok"}, "finish_reason": "stop"}]})
        + "data: [DONE]\n\n"
    )

    route = respx.post("https://api.example.com/v1/chat/completions")
    route.side_effect = [
        httpx.Response(429, headers={"Retry-After": "2"}, json={"error": "rate"}),
        httpx.Response(200, text=success_body),
    ]

    text, _ = await client.complete(
        [Message(role="user", content="hi")], GenerationParams(),
    )
    assert text == "ok"
    # Honored the Retry-After header
    assert sleeps == [2.0]


@respx.mock
async def test_stream_retries_on_429_no_retry_after(client, monkeypatch):
    """429 without Retry-After → exponential backoff."""
    sleeps: list[float] = []

    async def fake_sleep(s: float) -> None:
        sleeps.append(s)

    monkeypatch.setattr("dzmm.models.openai_compat.asyncio.sleep", fake_sleep)

    success_body = (
        sse({"choices": [{"delta": {"content": "ok"}, "finish_reason": "stop"}]})
        + "data: [DONE]\n\n"
    )

    route = respx.post("https://api.example.com/v1/chat/completions")
    route.side_effect = [
        httpx.Response(429, json={"error": "rate"}),
        httpx.Response(429, json={"error": "rate"}),
        httpx.Response(200, text=success_body),
    ]

    text, _ = await client.complete(
        [Message(role="user", content="hi")], GenerationParams(),
    )
    assert text == "ok"
    # Exponential: 1.5 * 2^0 = 1.5, 1.5 * 2^1 = 3.0
    assert sleeps == [1.5, 3.0]


@respx.mock
async def test_stream_429_gives_up_after_max_retries(client, monkeypatch):
    """4 consecutive 429s → final raise."""
    async def fake_sleep(s: float) -> None:
        pass

    monkeypatch.setattr("dzmm.models.openai_compat.asyncio.sleep", fake_sleep)

    route = respx.post("https://api.example.com/v1/chat/completions")
    route.side_effect = [
        httpx.Response(429),
        httpx.Response(429),
        httpx.Response(429),
        httpx.Response(429),  # 4th attempt = exceeds _MAX_429_RETRIES (3)
    ]

    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        async for _ in client.stream(
            [Message(role="user", content="hi")], GenerationParams(),
        ):
            pass
    assert exc_info.value.response.status_code == 429


@respx.mock
async def test_concurrency_gate_releases_on_early_break():
    """If consumer breaks out mid-stream (e.g. user disconnects), the gate
    must release so subsequent calls aren't blocked. Without explicit aclose
    this would only release on GC — verify the try/finally path works."""
    import asyncio
    gate = asyncio.Semaphore(1)
    client = OpenAICompatClient(
        name="test", base_url="https://api.example.com/v1",
        api_key="sk-test", model="test-model", timeout=5.0,
        concurrency_gate=gate,
    )

    body = (
        sse({"choices": [{"delta": {"content": "first"}, "finish_reason": None}]})
        + sse({"choices": [{"delta": {"content": " second"}, "finish_reason": None}]})
        + sse({"choices": [{"delta": {"content": " third"}, "finish_reason": "stop"}]})
        + "data: [DONE]\n\n"
    )
    respx.post("https://api.example.com/v1/chat/completions").mock(
        return_value=httpx.Response(200, text=body)
    )

    # First call: break after first chunk, then explicitly aclose.
    gen = client.stream([Message(role="user", content="hi")], GenerationParams())
    try:
        async for _ch in gen:
            break  # bail mid-stream
    finally:
        await gen.aclose()  # essential for prompt release

    # Gate must be released — try acquiring with a tiny timeout.
    try:
        await asyncio.wait_for(gate.acquire(), timeout=0.5)
        gate.release()  # success: pretend we're a follow-up caller
    except asyncio.TimeoutError:
        pytest.fail("semaphore was not released after consumer break + aclose")


@respx.mock
async def test_concurrency_gate_releases_on_early_break_NO_aclose():
    """SCARY case: consumer breaks WITHOUT calling aclose. Documents whether
    Python's GC-based async-gen finalization actually releases the semaphore
    promptly. Currently expected to FAIL (semaphore held until GC) — if it
    passes, great; if it fails, we've confirmed the leak path."""
    import asyncio
    import gc
    gate = asyncio.Semaphore(1)
    client = OpenAICompatClient(
        name="test", base_url="https://api.example.com/v1",
        api_key="sk-test", model="test-model", timeout=5.0,
        concurrency_gate=gate,
    )

    body = (
        sse({"choices": [{"delta": {"content": "first"}, "finish_reason": None}]})
        + sse({"choices": [{"delta": {"content": " second"}, "finish_reason": "stop"}]})
        + "data: [DONE]\n\n"
    )
    respx.post("https://api.example.com/v1/chat/completions").mock(
        return_value=httpx.Response(200, text=body)
    )

    async def consume_and_break():
        async for _ch in client.stream(
            [Message(role="user", content="hi")], GenerationParams(),
        ):
            return  # exit without aclose
    await consume_and_break()

    # Force GC + give the event loop a tick to run finalizers
    gc.collect()
    await asyncio.sleep(0)
    gc.collect()
    await asyncio.sleep(0.1)

    # Try to acquire — if leaked, this times out.
    try:
        await asyncio.wait_for(gate.acquire(), timeout=0.5)
        gate.release()
    except asyncio.TimeoutError:
        pytest.fail(
            "LEAK CONFIRMED: semaphore not released after early break without "
            "explicit aclose(). Need a stronger pattern (e.g. ownership in caller)."
        )


@respx.mock
async def test_concurrency_gate_releases_on_exception():
    """If the inner stream raises (after first chunk), the gate must still
    release so the next caller can proceed."""
    import asyncio
    gate = asyncio.Semaphore(1)
    client = OpenAICompatClient(
        name="test", base_url="https://api.example.com/v1",
        api_key="sk-test", model="test-model", timeout=5.0,
        concurrency_gate=gate,
    )

    respx.post("https://api.example.com/v1/chat/completions").mock(
        return_value=httpx.Response(500, json={"error": "boom"})
    )

    with pytest.raises(httpx.HTTPStatusError):
        async for _ch in client.stream(
            [Message(role="user", content="hi")], GenerationParams(),
        ):
            pass

    # Gate must be released even though the request failed.
    try:
        await asyncio.wait_for(gate.acquire(), timeout=0.5)
        gate.release()
    except asyncio.TimeoutError:
        pytest.fail("semaphore was not released after request failure")
