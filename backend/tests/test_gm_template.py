from dzmm.models.client import Message
from dzmm.prompts.gm_template import build_gm_messages


def test_system_message_contains_world_and_character():
    msgs = build_gm_messages(
        world_md="赛博朋克末世，企业掌权。",
        character_md="姓名: Riku\n职业: 义体黑客",
        live_state={"hp": 18, "sanity": 12, "inventory": ["小刀"]},
        rules_mode="light",
        style="dark",
        story_summary="",
        key_facts="",
        recent_messages=[],
        current_action="环顾四周",
    )
    sys_msg = msgs[0]
    assert sys_msg.role == "system"
    assert "赛博朋克" in sys_msg.content
    assert "Riku" in sys_msg.content
    assert "义体黑客" in sys_msg.content
    assert "<narrative>" in sys_msg.content
    assert "不替 PC 做决定" in sys_msg.content


def test_user_message_is_current_action():
    msgs = build_gm_messages(
        world_md="x", character_md="y", live_state={},
        rules_mode="light", style="realistic",
        story_summary="", key_facts="",
        recent_messages=[], current_action="上前搭话",
    )
    last = msgs[-1]
    assert last.role == "user"
    assert "上前搭话" in last.content


def test_recent_messages_inserted_between_system_and_action():
    history = [
        Message(role="user", content="开门"),
        Message(role="assistant", content="<narrative>门打开了</narrative>"),
    ]
    msgs = build_gm_messages(
        world_md="x", character_md="y", live_state={},
        rules_mode="light", style="realistic",
        story_summary="", key_facts="",
        recent_messages=history, current_action="向前走",
    )
    roles = [m.role for m in msgs]
    assert roles == ["system", "user", "assistant", "user"]
    assert msgs[1].content == "开门"
    assert msgs[2].content == "<narrative>门打开了</narrative>"
    assert msgs[3].content == "向前走"


def test_summary_and_key_facts_included_when_present():
    msgs = build_gm_messages(
        world_md="x", character_md="y", live_state={},
        rules_mode="light", style="dark",
        story_summary="PC 已击败山猫，获得加密芯片。",
        key_facts="进行中任务：取回芯片",
        recent_messages=[], current_action="去酒吧",
    )
    sys = msgs[0].content
    assert "PC 已击败山猫" in sys
    assert "进行中任务" in sys


def test_opening_hint_when_no_history():
    msgs = build_gm_messages(
        world_md="x", character_md="y", live_state={},
        rules_mode="light", style="dark",
        story_summary="", key_facts="",
        recent_messages=[], current_action="(开始游戏)",
    )
    sys = msgs[0].content
    assert "开局" in sys


def test_rules_mode_light_disables_dice_requirement():
    msgs = build_gm_messages(
        world_md="x", character_md="y", live_state={},
        rules_mode="light", style="realistic",
        story_summary="", key_facts="",
        recent_messages=[], current_action="x",
    )
    sys = msgs[0].content
    assert "轻量化" in sys


def test_format_reinforcement_at_end():
    """Anthropic/OpenAI prompt-engineering best practice: the final line of the
    system prompt is the strongest priming. Verify the format reminder is the
    last meaningful line."""
    msgs = build_gm_messages(
        world_md="x", character_md="y", live_state={},
        rules_mode="light", style="dark",
        story_summary="", key_facts="",
        recent_messages=[], current_action="x",
    )
    sys = msgs[0].content.rstrip()
    last_paragraph = sys.split("\n\n")[-1]
    assert "<narrative>" in last_paragraph
    assert "必须" in last_paragraph or "立即" in last_paragraph
