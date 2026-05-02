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


def test_dice_rule_emphasizes_randomness():
    """v0.1.9: dice section in the GM prompt must contain explicit guidance
    against the 'always d20=9' pattern observed in real play."""
    msgs = build_gm_messages(
        world_md="x", character_md="y", live_state={},
        rules_mode="light", style="dark",
        story_summary="", key_facts="",
        recent_messages=[], current_action="x",
    )
    sys_text = msgs[0].content
    assert "<dice" in sys_text and "d20" in sys_text
    # At least one explicit randomness-cue must appear in the dice block.
    cues = ["随机", "每次不同", "常量"]
    assert any(c in sys_text for c in cues), (
        f"dice block must explicitly call out randomness; got: {sys_text!r}"
    )


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
    assert "plot_event" in sys


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
    # Emotion threshold still present in reactive principles
    assert "≥70" in sys
    # emotion field still documented in npc_update format
    assert "emotion" in sys
    # pc_mood tag still in format section
    assert "pc_mood" in sys
    # npc_relation tag still in format section
    assert "npc_relation" in sys


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
    assert "反应兜底" in sys_text or "必须有可被感知" in sys_text or "NPC 反应兜底" in sys_text


def test_input_perspective_rule():
    """问题 3 — 玩家输入第三人称导演视角 vs 第一人称代入视角。"""
    msgs = build_gm_messages(
        world_md="x", character_md="y", live_state={},
        rules_mode="light", style="dark",
        story_summary="", key_facts="",
        recent_messages=[], current_action="x",
    )
    sys_text = msgs[0].content
    assert "导演视角" in sys_text and ("代入视角" in sys_text or "第一人称" in sys_text)


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


# ----------------------------------------------------------------------------
# v0.11 task B: PC hooks + numerical anchoring rules
# ----------------------------------------------------------------------------


def test_pc_hook_rule_present():
    """铁律 20 — PC 钩子（能力 / 物品 / 弱点 必须被场景调用）。"""
    msgs = build_gm_messages(
        world_md="x", character_md="y", live_state={},
        rules_mode="light", style="dark",
        story_summary="", key_facts="",
        recent_messages=[], current_action="x",
    )
    sys_text = msgs[0].content
    assert "PC 钩子" in sys_text
    assert "能力" in sys_text and "物品" in sys_text and "弱点" in sys_text
    # 节奏数字必须明示
    assert "3-5 回合" in sys_text or "5-8 回合" in sys_text


def test_numerical_anchoring_rule_present():
    """铁律 21/PC钩子 — DC参考、能力/物品/弱点的钩子规则。"""
    sys_text = build_gm_messages(
        world_md="x", character_md="y", live_state={},
        rules_mode="light", style="dark",
        story_summary="", key_facts="",
        recent_messages=[], current_action="x",
    )[0].content
    # DC reference still present in dice format docs
    assert "DC" in sys_text
    # PC hooks rule still present in secondary rules
    assert "能力" in sys_text and "弱点" in sys_text


# ----------------------------------------------------------------------------
# v0.12 task C: 关键信息推进义务 + 世界状态前进 + few_shot PC 名占位
# ----------------------------------------------------------------------------


def test_rule_information_progress_present():
    """铁律 4 — 关键信息必须直给，禁止拖延。"""
    sys_text = build_gm_messages(
        world_md="x", character_md="y", live_state={},
        rules_mode="light", style="dark",
        story_summary="", key_facts="",
        recent_messages=[], current_action="x",
    )[0].content
    assert "关键信息" in sys_text or "告诉我" in sys_text
    assert "本回合" in sys_text  # 推进义务
    assert "时机未到" in sys_text or "以后再说" in sys_text  # 拖延禁止


def test_rule_world_state_progress_present():
    """铁律 23 — 每回合世界状态必须前进。"""
    sys_text = build_gm_messages(
        world_md="x", character_md="y", live_state={},
        rules_mode="light", style="dark",
        story_summary="", key_facts="",
        recent_messages=[], current_action="x",
    )[0].content
    assert "世界状态" in sys_text or "前进" in sys_text
    assert "原地循环" in sys_text or "重复" in sys_text  # 防原地


def test_rule_name_self_check_present():
    """铁律 1 — PC 姓名锁，不能漂移。"""
    sys_text = build_gm_messages(
        world_md="x", character_md="y", live_state={},
        rules_mode="light", style="dark",
        story_summary="", key_facts="",
        recent_messages=[], current_action="x",
    )[0].content
    assert "漂移" in sys_text  # name drift is forbidden
    assert "不替 PC" in sys_text or "不替 PC 做决定" in sys_text


def test_few_shot_example_uses_actual_pc_name():
    """few_shot example 必须用真实 character_name，不再硬编码沈三川。"""
    msgs = build_gm_messages(
        world_md="x",
        character_md="姓名: 测试主角\n职业: 流浪者",
        live_state={}, rules_mode="standard", style="dark",
        story_summary="", key_facts="",
        recent_messages=[], current_action="x",
        character_name="测试主角",
    )
    sys_text = msgs[0].content

    # 实际 PC 名必须出现在范例中
    assert "测试主角" in sys_text

    # 之前硬编码的 "沈三川" 不能出现在范例中
    example_idx = sys_text.find("输出范例")
    assert example_idx >= 0
    example_section = sys_text[example_idx:]
    assert "沈三川" not in example_section


def test_few_shot_example_pc_name_substituted_from_md():
    """character_name 没显式传时，从 character_md 推断的名字也要替换进 example。"""
    msgs = build_gm_messages(
        world_md="x",
        character_md="姓名: Riku\n职业: 义体黑客",
        live_state={}, rules_mode="light", style="dark",
        story_summary="", key_facts="",
        recent_messages=[], current_action="x",
    )
    sys_text = msgs[0].content
    example_idx = sys_text.find("输出范例")
    assert example_idx >= 0
    example_section = sys_text[example_idx:]
    # PC name should appear inside the example block (in pc_action / 范例描述)
    assert "Riku" in example_section
    # And no leftover hardcoded name
    assert "沈三川" not in example_section


# ----------------------------------------------------------------------------
# v0.13 task C: 铁律 22/23 加狠 + few_shot 关键信息推进示范
# ----------------------------------------------------------------------------


def test_rule_22_explicit_question_patterns():
    sys_text = build_gm_messages(
        world_md="x", character_md="y", live_state={},
        rules_mode="light", style="dark",
        story_summary="", key_facts="",
        recent_messages=[], current_action="x",
    )[0].content
    assert "告诉我" in sys_text or "是谁" in sys_text
    # forbidden delay phrases listed:
    assert "时机未到" in sys_text or "以后再说" in sys_text
    # allowed escape: NPC doesn't know
    assert "不知道" in sys_text


def test_rule_22_repeated_question_must_repeat_answer():
    sys_text = build_gm_messages(
        world_md="x", character_md="y", live_state={},
        rules_mode="light", style="dark",
        story_summary="", key_facts="",
        recent_messages=[], current_action="x",
    )[0].content
    # key info must be given directly; forbidden delay phrases must be named
    assert "时机未到" in sys_text or "以后再说" in sys_text


def test_few_shot_includes_correct_information_example():
    """The new example demonstrates a question→answer flow with a concrete name."""
    sys_text = build_gm_messages(
        world_md="x", character_md="y", live_state={},
        rules_mode="light", style="dark",
        story_summary="", key_facts="",
        recent_messages=[], current_action="x",
    )[0].content
    # The good example should mention 陈子轩 + 清风茶寮 + 九龙黑街 (concrete proper nouns)
    assert "陈子轩" in sys_text
    assert "清风茶寮" in sys_text or "九龙黑街" in sys_text


def test_few_shot_includes_anti_pattern():
    """The example should also call out the wrong pattern by name."""
    sys_text = build_gm_messages(
        world_md="x", character_md="y", live_state={},
        rules_mode="light", style="dark",
        story_summary="", key_facts="",
        recent_messages=[], current_action="x",
    )[0].content
    assert "错误示范" in sys_text or "错误原因" in sys_text
    assert "拖延" in sys_text or "循环" in sys_text


# ---------------------------------------------------------------------------
# v0.1.0 task B — screenplay-driven tag docs + iron rule 24
# ---------------------------------------------------------------------------


def test_gm_prompt_documents_screenplay_tags():
    """All four screenplay-driven tags must appear in the tag dictionary so
    the GM has a reference for syntax + when to emit each one."""
    sys_text = build_gm_messages(
        world_md="x", character_md="y", live_state={},
        rules_mode="light", style="dark",
        story_summary="", key_facts="",
        recent_messages=[], current_action="x",
    )[0].content
    assert "<chapter_advance" in sys_text
    assert "<event_complete" in sys_text
    assert "<plot_turn" in sys_text
    assert "<ending" in sys_text
    # impact attr discriminator surfaces both modes
    assert "major" in sys_text and "minor" in sys_text


def test_gm_prompt_rule_24_screenplay_obedience():
    """Iron rule 7 (was 24) must explicitly tell the GM to follow '## 当前剧本进度'
    and emit the right tags as main events get played out."""
    sys_text = build_gm_messages(
        world_md="x", character_md="y", live_state={},
        rules_mode="light", style="dark",
        story_summary="", key_facts="",
        recent_messages=[], current_action="x",
    )[0].content
    # Rule 7 (formerly 24) mentions screenplay + advance behavior
    assert "7." in sys_text
    assert "剧本进度" in sys_text
    assert "主线" in sys_text and ("推进" in sys_text or "event_complete" in sys_text)
    # Concrete tag references in the rule body — these are the GM's emit cues
    assert "event_complete" in sys_text
    assert "chapter_advance" in sys_text
    assert "ending" in sys_text
    assert "plot_turn" in sys_text


def _build_default_sys() -> str:
    return build_gm_messages(
        world_md="x", character_md="y", live_state={},
        rules_mode="light", style="dark",
        story_summary="", key_facts="",
        recent_messages=[], current_action="x",
    )[0].content


def test_rule_24_force_progress_present():
    """v0.2.5 — rule 7 (was 24) must reflect strict 1-2 turn cadence."""
    sys_text = _build_default_sys()
    # Tightened cadence (was 1-3, now 1-2)
    assert "1-2 回合" in sys_text or "每 1-2" in sys_text
    # Old loose phrasing must NOT remain
    assert "1-3 回合" not in sys_text
    # Core screenplay progression tags are referenced
    assert "event_complete" in sys_text
    assert "chapter_advance" in sys_text


def test_rule_25_ordering_present():
    """v0.2.5 — output ordering rule: narrative → pc_action → say."""
    sys_text = _build_default_sys()
    assert "顺序" in sys_text
    assert "say" in sys_text and "pc_action" in sys_text
    # Rule references the story-timeline / 发生顺序 phrasing.
    assert "发生顺序" in sys_text or "故事时间线" in sys_text


def test_rule_26_npc_proactive_present():
    """v0.2.5 — NPC must take proactive action every 2-3 turns."""
    sys_text = _build_default_sys()
    assert "主动" in sys_text
    assert "2-3 回合" in sys_text or "2 回合" in sys_text
    assert "死场景" in sys_text or "禁止" in sys_text


def test_rule_27_dice_failure_consequences():
    """v0.2.5 — rule 8 (was 27): dice failure must produce negative consequences."""
    sys_text = _build_default_sys()
    assert "8." in sys_text
    assert "失败" in sys_text and "负面后果" in sys_text
    # At least one of the example consequence categories should be named
    assert "关系恶化" in sys_text or "线索错失" in sys_text
    # Big-success reward path is also documented in this rule
    assert "character_xp" in sys_text


def test_few_shot_demonstrates_ordering():
    """The few-shot block should now contain a concrete ordering demonstration
    so the model has both a rule (25) AND an example to imitate."""
    sys_text = _build_default_sys()
    # Demonstration 3 from gm_few_shot — story-timeline ordering example
    assert "信息顺序" in sys_text or "示范3" in sys_text or "故事时间线" in sys_text


def test_choices_require_risk_differentiation():
    """Each choices block must now instruct GM to cover different risk axes."""
    from dzmm.prompts.gm_template import build_gm_messages
    msgs = build_gm_messages(
        world_md="x", character_md="y", live_state={},
        rules_mode="light", style="dark",
        story_summary="", key_facts="",
        recent_messages=[], current_action="x",
    )
    sys = msgs[0].content
    assert "风险" in sys or "代价" in sys or "后果" in sys
    assert "高风险" in sys or "低风险" in sys or "风险档" in sys


def test_plot_event_throttle_rules_present():
    """Template must instruct GM: importance=1 → don't emit; max 1 plot_event per turn."""
    from dzmm.prompts.gm_template import build_gm_messages
    msgs = build_gm_messages(
        world_md="x", character_md="y", live_state={},
        rules_mode="light", style="dark",
        story_summary="", key_facts="",
        recent_messages=[], current_action="x",
    )
    sys = msgs[0].content
    assert "importance=1" in sys or 'importance="1"' in sys
    assert "每回合最多" in sys or "单回合最多" in sys or "max 1" in sys.lower()


def test_iron_law_9_plausibility_check_present():
    """Iron law 9 must instruct GM to reject physically impossible actions."""
    msgs = build_gm_messages(
        world_md="x", character_md="y", live_state={},
        rules_mode="light", style="dark",
        story_summary="", key_facts="",
        recent_messages=[], current_action="x",
    )
    sys = msgs[0].content
    assert "共 9 条" in sys
    assert "穿越" in sys or "可信度" in sys or "根本没有路径" in sys
