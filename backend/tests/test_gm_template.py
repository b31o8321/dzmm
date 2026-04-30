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


def test_plot_event_format_in_prompt():
    msgs = build_gm_messages(
        world_md="x", character_md="y", live_state={},
        rules_mode="light", style="dark",
        story_summary="", key_facts="",
        recent_messages=[], current_action="x",
    )
    sys = msgs[0].content
    assert "<plot_event" in sys
    assert "显式登记剧情事件" in sys


def test_standard_rules_emits_dice_instructions():
    msgs = build_gm_messages(
        world_md="x", character_md="y", live_state={},
        rules_mode="standard", style="realistic",
        story_summary="", key_facts="",
        recent_messages=[], current_action="x",
    )
    sys = msgs[0].content
    assert "d20" in sys
    assert "DC" in sys


def test_light_rules_explicitly_no_dice():
    msgs = build_gm_messages(
        world_md="x", character_md="y", live_state={},
        rules_mode="light", style="realistic",
        story_summary="", key_facts="",
        recent_messages=[], current_action="x",
    )
    sys = msgs[0].content
    assert "不要输出 <dice>" in sys


def test_character_xp_documented():
    msgs = build_gm_messages(
        world_md="x", character_md="y", live_state={},
        rules_mode="light", style="dark",
        story_summary="", key_facts="",
        recent_messages=[], current_action="x",
    )
    sys = msgs[0].content
    # Tag is documented in the format spec
    assert "<character_xp" in sys
    # And mentioned in the behavior rules
    assert "经验值" in sys


def test_era_begin_documented():
    msgs = build_gm_messages(
        world_md="x", character_md="y", live_state={},
        rules_mode="light", style="dark",
        story_summary="", key_facts="",
        recent_messages=[], current_action="x",
    )
    sys = msgs[0].content
    assert "<era_begin" in sys
    assert "章节切换" in sys


def test_pc_goal_documented():
    msgs = build_gm_messages(
        world_md="x", character_md="y", live_state={},
        rules_mode="light", style="dark",
        story_summary="", key_facts="",
        recent_messages=[], current_action="x",
    )
    sys = msgs[0].content
    assert "<pc_goal" in sys
    assert "PC 目标" in sys or "玩家明确表达意图" in sys


def test_pc_mood_documented():
    msgs = build_gm_messages(
        world_md="x", character_md="y", live_state={},
        rules_mode="light", style="dark",
        story_summary="", key_facts="",
        recent_messages=[], current_action="x",
    )
    sys = msgs[0].content
    assert "<pc_mood>" in sys
    assert "PC 心情" in sys


def test_npc_relation_documented():
    msgs = build_gm_messages(
        world_md="x", character_md="y", live_state={},
        rules_mode="light", style="dark",
        story_summary="", key_facts="",
        recent_messages=[], current_action="x",
    )
    sys = msgs[0].content
    assert "<npc_relation" in sys
    assert "NPC 关系" in sys


def test_npc_emotion_field_documented():
    msgs = build_gm_messages(
        world_md="x", character_md="y", live_state={},
        rules_mode="light", style="dark",
        story_summary="", key_facts="",
        recent_messages=[], current_action="x",
    )
    sys = msgs[0].content
    # The npc_update emotion field is documented with the 5 axes.
    assert "anger" in sys
    assert "love" in sys
    assert "fear" in sys
    assert "respect" in sys
    assert "jealousy" in sys


def test_emotion_mood_relation_behavior_rules_present():
    msgs = build_gm_messages(
        world_md="x", character_md="y", live_state={},
        rules_mode="light", style="dark",
        story_summary="", key_facts="",
        recent_messages=[], current_action="x",
    )
    sys = msgs[0].content
    # Rule 11 (情绪追踪)
    assert "NPC 情绪追踪" in sys
    assert "≥70" in sys
    # Rule 12 (PC 心情)
    assert "重大情绪事件" in sys
    # Rule 13 (NPC 关系)
    assert "NPC 关系" in sys
    assert "世界观持续性" in sys


def test_few_shot_example_present():
    msgs = build_gm_messages(
        world_md="x", character_md="y", live_state={},
        rules_mode="standard", style="dark",
        story_summary="", key_facts="",
        recent_messages=[], current_action="x",
    )
    sys = msgs[0].content
    assert "输出范例" in sys
    assert "</narrative>" in sys
    assert "</state_change>" in sys
    assert "</npc_update>" in sys
    assert "</choices>" in sys
