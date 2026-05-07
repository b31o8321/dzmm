import json
import httpx
import pytest
import respx

from dzmm.models.client import GenerationParams, Message
from dzmm.models.ollama import OllamaClient


@pytest.fixture
def client():
    return OllamaClient(
        name="local",
        base_url="http://localhost:11434",
        model="qwen2.5:7b",
        timeout=5.0,
    )


@respx.mock
async def test_stream_yields_message_deltas(client):
    body = (
        json.dumps({"message": {"role": "assistant", "content": "Hi"}, "done": False}) + "\n"
        + json.dumps({"message": {"content": " there"}, "done": False}) + "\n"
        + json.dumps({"message": {"content": ""}, "done": True,
                      "prompt_eval_count": 10, "eval_count": 4}) + "\n"
    )
    respx.post("http://localhost:11434/api/chat").mock(
        return_value=httpx.Response(200, text=body)
    )

    chunks = []
    async for ch in client.stream(
        [Message(role="user", content="hi")], GenerationParams(),
    ):
        chunks.append(ch)

    text = "".join(c.delta for c in chunks)
    assert text == "Hi there"
    final = chunks[-1]
    assert final.finish_reason == "stop"
    assert final.usage is not None
    assert final.usage.input_tokens == 10
    assert final.usage.output_tokens == 4


@respx.mock
async def test_list_models(client):
    respx.get("http://localhost:11434/api/tags").mock(
        return_value=httpx.Response(200, json={
            "models": [{"name": "qwen2.5:7b"}, {"name": "llama3:8b"}]
        })
    )
    names = await client.list_models()
    assert names == ["qwen2.5:7b", "llama3:8b"]


@respx.mock
async def test_stream_sets_num_ctx(client):
    captured = {}

    def handler(request):
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            text=(
                json.dumps({"message": {"content": "hi"}, "done": True,
                            "prompt_eval_count": 1, "eval_count": 1}) + "\n"
            ),
        )

    respx.post("http://localhost:11434/api/chat").mock(side_effect=handler)

    async for _ in client.stream(
        [Message(role="user", content="hi")], GenerationParams(),
    ):
        pass

    # v0.9.1: bumped 8192 → 32768 (ollama runner ignores Modelfile defaults
    # when an API request specifies num_ctx, so we MUST send a large value).
    assert captured["body"]["options"]["num_ctx"] == 32768
