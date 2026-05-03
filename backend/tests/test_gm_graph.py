"""Tests for LangGraph multi-agent GM pipeline (Phase B)."""
import pytest
from dzmm.models.client import GenerationParams, Message, ModelClient, StreamChunk, TokenUsage
from dzmm.parsing.events import TagComplete
from dzmm.prompts.npc_react_template import build_npc_react_messages, build_npc_single_react_messages
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
    npc = _FakeNpc(name="王五", archetype="冷静商人", state="平静")
    events = await run_npc_post_pass(
        narrative="你走进了酒馆",
        present_npcs=[npc],
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
    npc = _FakeNpc(name="李四")
    events = await run_npc_post_pass(
        narrative="...", present_npcs=[npc], user_action="...", client=client
    )
    assert events == []


@pytest.mark.asyncio
async def test_run_npc_post_pass_returns_empty_when_no_npcs():
    client = _FakeClient("should not be called")
    events = await run_npc_post_pass(
        narrative="...", present_npcs=[], user_action="...", client=client
    )
    assert events == []


class _FakeNpc:
    """Minimal NPC stub for testing — mirrors NPC ORM fields used by the prompt."""
    def __init__(
        self,
        name: str,
        archetype: str = "普通人",
        description: str = "一个普通的人。",
        state: str = "平静",
        purpose: str = "",
        emotion_json: str = "{}",
    ):
        self.name = name
        self.archetype = archetype
        self.description = description
        self.state = state
        self.purpose = purpose
        self.emotion_json = emotion_json


def test_build_npc_single_react_messages_embeds_archetype():
    npc = _FakeNpc(
        name="卫队长",
        archetype="冷酷军人",
        description="前帝国精锐，话少，但观察敏锐。",
        state="戒备",
        purpose="守护王城安全",
        emotion_json='{"suspicious": 7}',
    )
    msgs = build_npc_single_react_messages(
        narrative="你走进了城门，卫队长瞥了你一眼，手按在剑柄上。",
        npc=npc,
        user_action="我微笑着递上通行证",
    )
    assert len(msgs) == 1
    assert msgs[0].role == "user"
    assert "冷酷军人" in msgs[0].content
    assert "卫队长" in msgs[0].content
    assert "戒备" in msgs[0].content
    assert "守护王城安全" in msgs[0].content   # purpose
    assert "前帝国精锐" in msgs[0].content      # description (part of the description text)
    assert "suspicious" in msgs[0].content      # emotion key from emotion_json


def test_build_npc_single_react_messages_different_archetype():
    npc = _FakeNpc(
        name="酒馆老板",
        archetype="热情商人",
        description="胖乎乎，总是笑着，非常健谈。",
        state="高兴",
        purpose="经营酒馆，广结善缘",
    )
    msgs = build_npc_single_react_messages(
        narrative="你推开酒馆大门，热气扑面而来。",
        npc=npc,
        user_action="我走进酒馆",
    )
    assert "热情商人" in msgs[0].content
    assert "酒馆老板" in msgs[0].content


@pytest.mark.asyncio
async def test_run_npc_post_pass_per_npc_with_objects():
    """run_npc_post_pass should call LLM once per NPC object and return all non-none events."""
    call_count = 0

    class _CountingClient(ModelClient):
        name = "counting"

        async def stream(self, messages, params):
            yield StreamChunk(delta="", finish_reason="stop")

        async def complete(self, messages, params):
            nonlocal call_count
            call_count += 1
            npc_name = "王五" if call_count == 1 else "李四"
            return f'<npc_update name="{npc_name}">有反应</npc_update>', TokenUsage()

    npc1 = _FakeNpc(name="王五", archetype="冷酷商人")
    npc2 = _FakeNpc(name="李四", archetype="热情向导")
    events = await run_npc_post_pass(
        narrative="你进入了市场。",
        present_npcs=[npc1, npc2],
        user_action="我四处张望",
        client=_CountingClient(),
    )
    assert call_count == 2  # one LLM call per NPC
    assert len(events) == 2


@pytest.mark.asyncio
async def test_run_npc_post_pass_skips_none_responses():
    """NPCs that respond with 'none' should not contribute events."""
    call_num = 0

    class _SequentialClient(ModelClient):
        name = "seq"

        async def stream(self, messages, params):
            yield StreamChunk(delta="", finish_reason="stop")

        async def complete(self, messages, params):
            nonlocal call_num
            call_num += 1
            if call_num == 1:
                return '<npc_update name="none">无需补充</npc_update>', TokenUsage()
            return '<npc_update name="村民">惊讶地看着你</npc_update>', TokenUsage()

    npc1 = _FakeNpc(name="守卫")
    npc2 = _FakeNpc(name="村民")
    events = await run_npc_post_pass(
        narrative="你走进村子。",
        present_npcs=[npc1, npc2],
        user_action="我进村",
        client=_SequentialClient(),
    )
    assert len(events) == 1
    assert events[0].attrs.get("name") == "村民"
