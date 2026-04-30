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


def test_reactivity_principles_present():
    msgs = build_gm_messages(
        world_md="x", character_md="y", live_state={},
        rules_mode="light", style="dark",
        story_summary="", key_facts="",
        recent_messages=[], current_action="x",
    )
    sys = msgs[0].content
    assert "反应性原则" in sys
    # 关键提示词必须出现
    assert "情绪" in sys
    assert "≥ 70" in sys or "≥70" in sys
    assert "PC 心情" in sys
    assert "关系" in sys


def test_reactivity_addresses_pc_goals():
    msgs = build_gm_messages(
        world_md="x", character_md="y", live_state={},
        rules_mode="light", style="dark",
        story_summary="", key_facts="",
        recent_messages=[], current_action="x",
    )
    sys = msgs[0].content
    # 反应性原则那一节应该说到 PC 目标
    reactivity_section_idx = sys.find("反应性原则")
    assert reactivity_section_idx >= 0
    section_after = sys[reactivity_section_idx:]
    assert "PC 的活跃目标" in section_after or "PC 目标" in section_after


def test_reactivity_emphasizes_action_not_telling():
    """反应性原则要点之一：用动作传达，不要直接说'她愤怒'。"""
    msgs = build_gm_messages(
        world_md="x", character_md="y", live_state={},
        rules_mode="light", style="dark",
        story_summary="", key_facts="",
        recent_messages=[], current_action="x",
    )
    sys = msgs[0].content
    # 关键约束：show don't tell
    assert "用动作和对话" in sys or "show don" in sys.lower() or "动作" in sys


# ----------------------------------------------------------------------------
# v0.10 task B: 6 fixes from live-play feedback
# ----------------------------------------------------------------------------


def test_pc_name_lock_in_system_prompt():
    """问题 4 — PC 角色名漂移。System prompt 中必须显式锁定 PC 姓名。"""
    msgs = build_gm_messages(
        world_md="赛博朋克",
        character_md="姓名: 沈三川\n职业: 流浪医生",
        live_state={}, rules_mode="light", style="dark",
        story_summary="", key_facts="",
        recent_messages=[], current_action="x",
        character_name="沈三川",
    )
    sys_text = msgs[0].content
    assert "沈三川" in sys_text
    # 强约束词：永远 / 不可改 至少一个出现
    assert "永远" in sys_text or "不可改" in sys_text


def test_pc_name_lock_via_character_md_extraction():
    """没有显式 character_name 也能从 character_md 推断 PC 姓名。"""
    msgs = build_gm_messages(
        world_md="x",
        character_md="姓名: 沈三川\n职业: 流浪医生",
        live_state={}, rules_mode="light", style="dark",
        story_summary="", key_facts="",
        recent_messages=[], current_action="x",
    )
    sys_text = msgs[0].content
    assert "沈三川" in sys_text


def test_npc_reactivity_baseline_rule():
    """问题 2 — NPC 反应阈值过高。PC 直接搭话时 NPC 必须本回合回应。"""
    msgs = build_gm_messages(
        world_md="x", character_md="y", live_state={},
        rules_mode="light", style="dark",
        story_summary="", key_facts="",
        recent_messages=[], current_action="x",
    )
    sys_text = msgs[0].content
    assert "搭话" in sys_text or "提问" in sys_text
    assert "必须有回应" in sys_text or "必须回应" in sys_text


def test_input_perspective_rule():
    """问题 3 — 玩家输入第三人称导演视角 vs 第一人称代入视角。"""
    msgs = build_gm_messages(
        world_md="x", character_md="y", live_state={},
        rules_mode="light", style="dark",
        story_summary="", key_facts="",
        recent_messages=[], current_action="x",
    )
    sys_text = msgs[0].content
    assert "导演视角" in sys_text and "代入视角" in sys_text


def test_say_tag_documented():
    """问题 9 — 引入 <say speaker="..."> 与 <pc_action> 区分对白主体。"""
    sys_text = build_gm_messages(
        world_md="x", character_md="y", live_state={},
        rules_mode="light", style="dark",
        story_summary="", key_facts="",
        recent_messages=[], current_action="x",
    )[0].content
    assert "<say speaker" in sys_text
    assert "pc_action" in sys_text


def test_hidden_event_tag_documented():
    """问题 10 — <hidden_event> 隐性事件标签必须被文档化。"""
    sys_text = build_gm_messages(
        world_md="x", character_md="y", live_state={},
        rules_mode="light", style="dark",
        story_summary="", key_facts="",
        recent_messages=[], current_action="x",
    )[0].content
    assert "hidden_event" in sys_text
    assert "consequence" in sys_text
    assert "玩家" in sys_text and (
        "不应直接看到" in sys_text or "不展示" in sys_text or "不要" in sys_text
    )


def test_narrative_length_guidance():
    """问题 5 — narrative 描写过短。必须明示字数与丰度要求。"""
    sys_text = build_gm_messages(
        world_md="x", character_md="y", live_state={},
        rules_mode="light", style="dark",
        story_summary="", key_facts="",
        recent_messages=[], current_action="x",
    )[0].content
    assert "200" in sys_text or "300" in sys_text or "400" in sys_text
    assert "钩子" in sys_text or "线索" in sys_text or "推" in sys_text


def test_npc_update_first_mention_rule():
    """问题 7 — NPC 首次提名必须 emit npc_update 自动登记档案。"""
    sys_text = build_gm_messages(
        world_md="x", character_md="y", live_state={},
        rules_mode="light", style="dark",
        story_summary="", key_facts="",
        recent_messages=[], current_action="x",
    )[0].content
    assert (
        "首次提名" in sys_text
        or "首次提到" in sys_text
        or "首次出现" in sys_text
    )


def test_output_order_rule_present():
    """问题 9 — 输出顺序：narrative → pc_action → say 自然交错。"""
    sys_text = build_gm_messages(
        world_md="x", character_md="y", live_state={},
        rules_mode="light", style="dark",
        story_summary="", key_facts="",
        recent_messages=[], current_action="x",
    )[0].content
    assert "发生顺序" in sys_text or "顺序" in sys_text
    # 至少一处明确说 narrative + pc_action + say 三种共存
    assert "pc_action" in sys_text and "<say" in sys_text and "<narrative>" in sys_text


def test_few_shot_uses_new_tags():
    """范例必须升级到使用 say / pc_action / hidden_event 等新标签。"""
    sys_text = build_gm_messages(
        world_md="x", character_md="y", live_state={},
        rules_mode="standard", style="dark",
        story_summary="", key_facts="",
        recent_messages=[], current_action="x",
    )[0].content
    # 范例段中包含至少一个 say / pc_action / hidden_event
    example_idx = sys_text.find("输出范例")
    assert example_idx >= 0
    example_section = sys_text[example_idx:]
    assert "<say speaker" in example_section
    assert "<pc_action>" in example_section
    assert "<hidden_event" in example_section
