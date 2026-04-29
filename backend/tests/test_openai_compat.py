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
async def test_stream_raises_on_4xx(client):
    respx.post("https://api.example.com/v1/chat/completions").mock(
        return_value=httpx.Response(401, json={"error": "unauthorized"})
    )

    with pytest.raises(httpx.HTTPStatusError):
        async for _ in client.stream(
            [Message(role="user", content="hi")], GenerationParams(),
        ):
            pass
