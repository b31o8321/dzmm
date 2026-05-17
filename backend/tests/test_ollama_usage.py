"""Tests for Ollama token-usage tracking (G3 bug fix).

Ollama's /api/chat final chunk includes prompt_eval_count (input tokens) and
eval_count (output tokens). These tests verify that OllamaClient.stream()
correctly surfaces a TokenUsage on the final StreamChunk.
"""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from dzmm.models.client import GenerationParams, Message, TokenUsage
from dzmm.models.ollama import OllamaClient


def _make_ollama_client() -> OllamaClient:
    return OllamaClient(
        name="test-ollama",
        base_url="http://localhost:11434",
        model="qwen2.5:7b",
    )


def _build_stream_lines(*chunks: dict) -> list[bytes]:
    """Encode a sequence of Ollama chat response dicts as newline-separated JSON bytes."""
    return [json.dumps(c).encode() + b"\n" for c in chunks]


async def _collect_stream(client: OllamaClient, lines: list[bytes]):
    """Collect all StreamChunks from a mocked httpx stream."""
    messages = [Message(role="user", content="hello")]
    params = GenerationParams()

    # Build async line iterator
    async def aiter_lines():
        for line in lines:
            yield line.decode().rstrip("\n")

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.aiter_lines = aiter_lines

    mock_stream_ctx = AsyncMock()
    mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_response)
    mock_stream_ctx.__aexit__ = AsyncMock(return_value=False)

    mock_client = MagicMock()
    mock_client.stream = MagicMock(return_value=mock_stream_ctx)

    mock_http_ctx = AsyncMock()
    mock_http_ctx.__aenter__ = AsyncMock(return_value=mock_client)
    mock_http_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("dzmm.models.ollama.httpx.AsyncClient", return_value=mock_http_ctx):
        chunks = []
        async for chunk in client.stream(messages, params):
            chunks.append(chunk)
    return chunks


async def test_ollama_stream_emits_usage_on_final_chunk():
    """Final done=true chunk with prompt_eval_count + eval_count produces a TokenUsage."""
    client = _make_ollama_client()
    lines = _build_stream_lines(
        {"message": {"role": "assistant", "content": "你"}, "done": False},
        {"message": {"role": "assistant", "content": "好"}, "done": False},
        {
            "message": {"role": "assistant", "content": ""},
            "done": True,
            "prompt_eval_count": 42,
            "eval_count": 17,
        },
    )
    chunks = await _collect_stream(client, lines)

    # Find the chunk that carries usage
    usage_chunks = [c for c in chunks if c.usage is not None]
    assert len(usage_chunks) == 1, "Exactly one chunk should carry usage"
    usage = usage_chunks[0].usage
    assert isinstance(usage, TokenUsage)
    assert usage.input_tokens == 42
    assert usage.output_tokens == 17


async def test_ollama_stream_zero_when_field_missing():
    """Final chunk without eval_count fields yields TokenUsage(0, 0) cleanly."""
    client = _make_ollama_client()
    lines = _build_stream_lines(
        {"message": {"role": "assistant", "content": "ok"}, "done": False},
        # done=True but no eval counts
        {"message": {"role": "assistant", "content": ""}, "done": True},
    )
    chunks = await _collect_stream(client, lines)

    usage_chunks = [c for c in chunks if c.usage is not None]
    assert len(usage_chunks) == 1
    usage = usage_chunks[0].usage
    assert usage.input_tokens == 0
    assert usage.output_tokens == 0


async def test_ollama_stream_accumulates_partial_eval_count_correctly():
    """Ollama emits cumulative eval_count; the final done=True value is the total."""
    client = _make_ollama_client()
    # Simulate: Ollama may not emit eval_count on intermediate chunks (only on done);
    # the final value IS the total output token count.
    lines = _build_stream_lines(
        {"message": {"role": "assistant", "content": "一"}, "done": False},
        {"message": {"role": "assistant", "content": "二"}, "done": False},
        {"message": {"role": "assistant", "content": "三"}, "done": False},
        {
            "message": {"role": "assistant", "content": ""},
            "done": True,
            "prompt_eval_count": 100,
            "eval_count": 3,   # total output tokens for the 3 content chunks
        },
    )
    chunks = await _collect_stream(client, lines)

    # Text content chunks
    text_chunks = [c for c in chunks if c.delta]
    assert len(text_chunks) == 3

    usage_chunks = [c for c in chunks if c.usage is not None]
    assert len(usage_chunks) == 1
    usage = usage_chunks[0].usage
    assert usage.input_tokens == 100
    assert usage.output_tokens == 3
