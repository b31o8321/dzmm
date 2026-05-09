"""Tests for wizard_framework service — Plan C (Open-World Wizard API).

TDD: tests written before implementation for each task.
"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock
from dzmm.models.client import TokenUsage


class _FakeClient:
    def __init__(self, response: str):
        self._response = response
    async def complete(self, messages, params):
        return self._response, TokenUsage()
    async def stream(self, messages, params):
        from dzmm.models.client import StreamChunk
        yield StreamChunk(delta=self._response, finish_reason="stop")


LOCATIONS_JSON = json.dumps([
    {"name": "暗影港", "description_md": "阴暗的港口城市。", "location_type": "city",
     "connections": [{"target_name": "迷雾森林", "direction": "north", "distance": 1, "travel_turns": 2}],
     "initial_state": "normal"},
    {"name": "迷雾森林", "description_md": "雾气弥漫的森林。", "location_type": "wilderness",
     "connections": [{"target_name": "暗影港", "direction": "south", "distance": 1, "travel_turns": 2}],
     "initial_state": "normal"},
])


async def test_generate_locations_returns_list():
    from dzmm.service.wizard_framework import generate_locations
    client = _FakeClient(LOCATIONS_JSON)
    result = await generate_locations(
        genre="悬疑", world_brief_md="一个阴暗的维多利亚时代城市。", client=client
    )
    assert isinstance(result, list)
    assert len(result) == 2
    assert result[0]["name"] == "暗影港"
    assert "connections" in result[0]
