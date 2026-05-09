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


# ── Task 2: factions, npc_templates, events ───────────────────────────────

FACTIONS_JSON = json.dumps([
    {"name": "暗夜公会", "description_md": "控制地下经济的秘密组织。",
     "rival_faction_names": ["教会"], "ally_faction_names": [],
     "tension_rules": {"passive_gain_per_turn": 1, "threshold_conflict": 80}},
    {"name": "教会", "description_md": "维护秩序的宗教势力。",
     "rival_faction_names": ["暗夜公会"], "ally_faction_names": [],
     "tension_rules": {"passive_gain_per_turn": 0, "threshold_conflict": 90}},
])

NPC_TEMPLATES_JSON = json.dumps([
    {"name": "李影", "gender": "female", "role": "公会密探",
     "description_md": "冷静多疑。", "motivation": "保护组织机密",
     "home_location_name": "暗影港", "faction_name": "暗夜公会",
     "contact_favor_threshold": 70, "contact_cooldown_turns": 10},
])

EVENTS_JSON = json.dumps([
    {"name": "港口谋杀案", "summary_md": "港口发现神秘尸体。",
     "scope_type": "location", "scope_location_name": "暗影港", "importance": 3,
     "trigger_conditions": [{"type": "location", "location_name": "暗影港"}],
     "is_repeatable": False, "cooldown_turns": 0},
])


async def test_generate_factions_returns_list():
    from dzmm.service.wizard_framework import generate_factions
    client = _FakeClient(FACTIONS_JSON)
    result = await generate_factions(
        genre="悬疑", world_brief_md="维多利亚城市", locations=[], client=client
    )
    assert len(result) == 2
    assert result[0]["name"] == "暗夜公会"


async def test_generate_npc_templates_returns_list():
    from dzmm.service.wizard_framework import generate_npc_templates
    client = _FakeClient(NPC_TEMPLATES_JSON)
    result = await generate_npc_templates(
        genre="悬疑", world_brief_md="维多利亚城市",
        locations=[], factions=[], client=client,
    )
    assert len(result) == 1
    assert result[0]["gender"] == "female"


async def test_generate_events_returns_list():
    from dzmm.service.wizard_framework import generate_events
    client = _FakeClient(EVENTS_JSON)
    result = await generate_events(
        genre="悬疑", world_brief_md="维多利亚城市",
        locations=[], factions=[], npc_templates=[], client=client,
    )
    assert len(result) == 1
    assert result[0]["importance"] == 3
