import pytest

from dzmm.models.client import GenerationParams, Message, ModelClient, StreamChunk, TokenUsage
from dzmm.parsing.events import NarrativeDelta, TagComplete
from dzmm.prompts.scene_v2_template import build_scene_messages
from dzmm.service.agents.scene import run_scene


class _StubScene(ModelClient):
    name = "stub"
    def __init__(self, output: str):
        self._output = output
    async def stream(self, msgs, params):
        yield StreamChunk(delta=self._output, finish_reason="stop")
    async def complete(self, msgs, params):
        return self._output, TokenUsage()


def test_build_scene_messages_includes_directive_and_action():
    msgs = build_scene_messages(
        pc_name="Riku",
        plot_directive="<plot_directive>主推：救人</plot_directive>",
        world_md="赛博朋克",
        character_md="黑客 Riku",
        live_state_text='{"hp":12}',
        key_facts="第 3 回合",
        recent_messages=[],
        current_action="我冲进巷子",
    )
    assert msgs[0].role == "system"
    assert "Riku" in msgs[0].content
    assert "不写 NPC 对白" in msgs[0].content
    assert any("plot_directive" in m.content for m in msgs)
    assert msgs[-1].role == "user"
    assert "冲进巷子" in msgs[-1].content


@pytest.mark.asyncio
async def test_run_scene_streams_narrative_and_tags():
    output = (
        "<narrative>巷子潮湿，霓虹倒映在水洼里。</narrative>"
        '<dice category="stealth" outcome="success" dc="12" pc_roll="15" mod="+2">'
        "<scene>你贴墙挪步，脚下没声。</scene></dice>"
    )
    events = []
    async for ev in run_scene(
        client=_StubScene(output),
        pc_name="Riku",
        plot_directive="x",
        world_md="", character_md="",
        live_state_text="{}", key_facts="",
        recent_messages=[], current_action="潜行",
        params=GenerationParams(),
    ):
        events.append(ev)

    narratives = [e for e in events if isinstance(e, NarrativeDelta)]
    tags = [e for e in events if isinstance(e, TagComplete)]
    assert any("巷子" in n.text for n in narratives)
    assert any(t.name == "dice" for t in tags)


def test_scene_prompt_includes_npc_cue_schema():
    """v0.10.7: Scene prompt 应该明确说 npc_cue 标签和铁律。"""
    msgs = build_scene_messages(
        pc_name="x", plot_directive="x",
        world_md="", character_md="",
        live_state_text="{}", key_facts="",
        recent_messages=[], current_action="x",
    )
    sys_content = msgs[0].content
    assert "npc_cue" in sys_content
    assert "在场" in sys_content
    assert "speaker" in sys_content
