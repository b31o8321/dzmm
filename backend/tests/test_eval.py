"""Tests for Phase C autonomous evaluation agents."""
import json
import pytest
from dzmm.models.client import GenerationParams, ModelClient, StreamChunk, TokenUsage
from dzmm.prompts.player_template import build_player_messages
from dzmm.prompts.judge_template import build_judge_messages


class _FakeClient(ModelClient):
    name = "fake"

    def __init__(self, response: str):
        self._response = response

    async def stream(self, messages, params):  # noqa: ARG002
        yield StreamChunk(delta=self._response, finish_reason="stop")

    async def complete(self, messages, params):  # noqa: ARG002
        return self._response, TokenUsage()


def test_build_player_messages_includes_history():
    msgs = build_player_messages(
        character_name="林峰",
        character_md="林峰，一名侦探，沉默寡言。",
        recent_history=[("我走进房间", "你看到一具尸体倒在地板上，窗户半开。")],
    )
    assert len(msgs) == 1
    assert msgs[0].role == "user"
    assert "林峰" in msgs[0].content
    assert "尸体" in msgs[0].content


def test_build_judge_messages_includes_history():
    msgs = build_judge_messages(
        world_summary="维多利亚时代的伦敦，充满迷雾和阴谋。",
        recent_history=[("我检查现场", "你发现了一枚奇怪的徽章。")],
        n_turns=1,
    )
    assert len(msgs) == 1
    assert msgs[0].role == "user"
    assert "维多利亚" in msgs[0].content
    assert "plot_speed" in msgs[0].content
