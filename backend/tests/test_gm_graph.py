"""Tests for LangGraph multi-agent GM pipeline (Phase B)."""
import pytest
from dzmm.models.client import GenerationParams, Message, ModelClient, StreamChunk, TokenUsage
from dzmm.parsing.events import TagComplete
from dzmm.prompts.npc_react_template import build_npc_react_messages
from dzmm.prompts.rules_template import build_rules_messages
from dzmm.service.gm_graph import run_npc_post_pass, run_pre_pass


class _FakeClient(ModelClient):
    """Fake ModelClient that returns a preset response."""
    name = "fake"

    def __init__(self, response: str):
        self._response = response

    async def stream(self, messages, params):  # noqa: ARG002
        yield StreamChunk(delta=self._response, finish_reason="stop")

    async def complete(self, messages, params):  # noqa: ARG002
        return self._response, TokenUsage()


def test_build_rules_messages_returns_one_user_message():
    msgs = build_rules_messages("## 当前情境\n测试", "我尝试推开门")
    assert len(msgs) == 1
    assert msgs[0].role == "user"
    assert "推开门" in msgs[0].content


def test_build_npc_react_messages_returns_one_user_message():
    msgs = build_npc_react_messages(
        narrative="你推开了门，走进了酒馆。",
        present_npcs=["老板王五（心情：平静）", "流浪者李四（心情：警惕）"],
        user_action="我走进酒馆四处张望",
    )
    assert len(msgs) == 1
    assert msgs[0].role == "user"
    assert "王五" in msgs[0].content
    assert "李四" in msgs[0].content


@pytest.mark.asyncio
async def test_run_pre_pass_appends_enrichment():
    client = _FakeClient("行动类型：探索\n技能检定：无\n叙事指令：PC 四处张望，发现了蛛丝马迹。")
    original_key_facts = "## 情境\n当前在酒馆"
    result = await run_pre_pass(original_key_facts, "我四处张望", client)
    assert original_key_facts in result
    assert "规则分析" in result
    assert "探索" in result


@pytest.mark.asyncio
async def test_run_pre_pass_marks_dice_check():
    client = _FakeClient("行动类型：战斗\n技能检定：力量检定 DC12\n叙事指令：PC 推门。")
    result = await run_pre_pass("## 情境\n门很重", "用力推门", client)
    assert "骰子" in result or "DC" in result


@pytest.mark.asyncio
async def test_run_pre_pass_returns_original_on_empty_enrichment():
    client = _FakeClient("")
    original = "## 情境\n测试"
    result = await run_pre_pass(original, "行动", client)
    assert result == original


@pytest.mark.asyncio
async def test_run_npc_post_pass_parses_npc_update_tags():
    client = _FakeClient('<npc_update name="王五">注意到你，微微点头</npc_update>')
    events = await run_npc_post_pass(
        narrative="你走进了酒馆",
        present_npcs=["王五（心情：平静）"],
        user_action="我走进酒馆",
        client=client,
    )
    assert len(events) == 1
    assert isinstance(events[0], TagComplete)
    assert events[0].name == "npc_update"
    assert events[0].attrs.get("name") == "王五"


@pytest.mark.asyncio
async def test_run_npc_post_pass_returns_empty_for_none_response():
    client = _FakeClient('<npc_update name="none">无需补充</npc_update>')
    events = await run_npc_post_pass(
        narrative="...", present_npcs=["李四"], user_action="...", client=client
    )
    assert events == []


@pytest.mark.asyncio
async def test_run_npc_post_pass_returns_empty_when_no_npcs():
    client = _FakeClient("should not be called")
    events = await run_npc_post_pass(
        narrative="...", present_npcs=[], user_action="...", client=client
    )
    assert events == []
