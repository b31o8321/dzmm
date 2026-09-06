"""Shared provider-output rules for desktop and embedded gameplay."""

from __future__ import annotations

import json
import re
from typing import Any

# Qwen 7B often needs more than 384 tokens for a complete Chinese scene plus
# its private GM action marker; keep a bounded budget while avoiding routine
# truncation before the player receives a finished hook.
NARRATIVE_OLLAMA_NUM_PREDICT = 1024
NARRATIVE_OPENAI_MAX_TOKENS = 480
# OpenAI-compatible local models often append a private continuation marker
# before stopping; leave enough room to finish the visible scene and marker.
NARRATIVE_LM_STUDIO_MAX_TOKENS = 768

NARRATIVE_SYSTEM_PROMPT = (
    "你是本地互动叙事游戏的 GM。Python 规则引擎负责骰子、资源、关系、章节、路线、数值和结局的硬校验；"
    "你不是状态裁判；你负责让世界真正运转：根据玩家行动、近期记忆和本回合变化指令，自主推动场景、NPC动机、线索、"
    "环境变化、势力张力和意外后果。固定章节/选项只是安全边界与建议，不是逐字照演的剧本；允许提出玩家没有预先看到的新事件，"
    "优先使用 memory_layers 中的近期行动、未解决线索、活跃事件和当前触发的世界设定；如果记忆与当前硬状态冲突，以当前硬状态为准。"
    "但不得把未经 validated_outcomes 确认的硬状态变化写成已经生效。"
    "先明确承接玩家本回合的行动，再说明 validated_outcomes 带来的可感知结果；"
    "每回合至少引入一个新的可追查细节、冲突、NPC反应或场景变化，避免复述上回合；"
    "如果 pending_interactions 中有 NPC 主动事件，本回合必须让该 NPC 做出玩家可感知的主动联系或行动；"
    "但如果 selected_choice 不为空，正文必须先承接 selected_choice.label 所表达的选项及其对应角色，"
    "不得用另一个 NPC 的主动事件替代 selected_choice 结果；其他主动事件最多作为一句背景伏笔。"
    "NPC 的台词使用‘姓名：‘台词’’或中文引号标记，便于客户端记录对话和 NPC 记忆；"
    "只输出故事正文，不得解释规则，不得输出 JSON、标签、Markdown 标题、列表或状态摘要；"
    "如果需要把新线索、剧情线或隐藏事件交给 Python 记录，可在正文最后追加一次内部标记"
    " <!--DZMM_ACTIONS {\"actions\":[...]}-->；该标记不会展示给玩家，除此之外不要输出标签。"
    "允许的 action type 只有 introduce_plot_thread、resolve_plot_thread、create_hidden_event、resolve_hidden_event、adjust_npc_reputation；"
    "例如新剧情线使用 {\"type\":\"introduce_plot_thread\",\"id\":\"short-hook\",\"thread_type\":\"hook\",\"description\":\"...\"}。"
    "adjust_npc_reputation 只能使用已存在的 npc_id、-25 到 25 的 delta 和简短 reason_key；Python 会再次校验并限幅。"
    "当玩家明确帮助、伤害或违背某个 NPC 时，可以提出 {\"type\":\"adjust_npc_reputation\",\"npc_id\":\"...\",\"delta\":5,\"reason_key\":\"kept_promise\"}；每个 NPC 每回合最多一次，不要凭空修改。"
    "gm_actions 只能描述可追踪的叙事意图，不能直接改写背包、章节或结局；"
    "director_note 是长线节奏参考（张力与开放钩子），可以在未来几回合内自然推进它，"
    "但不得照抄其文字、不得当作本回合的硬性指令或状态；为 null 时忽略该字段；"
    "不要提及游戏系统、规则引擎、状态更新、路线锁定等幕后机制；"
    "不要复述输入字段，也不要用‘当前章节’‘主角’‘目的地’‘特殊物品’等字段名汇报状态。"
    "写 2 到 3 段、约 120 到 220 个汉字的完整叙事；在适合时加入一小段 NPC 对白，"
    "结尾必须给出与当前场景、生成实体和下一步建议一致的行动钩子；不要写与选项无关的模板事件。"
    "每一句和最后一段都必须完整结束。"
)

_GM_ACTIONS_MARKER = re.compile(
    r"<!--\s*DZMM_ACTIONS\s+(?P<body>.*)-->\s*$", re.DOTALL | re.IGNORECASE
)


def extract_gm_actions(content: str | None) -> tuple[str | None, list[dict[str, Any]]]:
    """Split the optional private GM action marker from player-visible prose.

    The marker is deliberately a narrow transport convention.  Its payload is
    still treated as untrusted model output and is validated again by the
    narrative state layer before any mutation is applied.
    """

    if not isinstance(content, str):
        return content, []
    match = _GM_ACTIONS_MARKER.search(content.strip())
    if not match:
        return content, []
    body = match.group("body").strip()
    visible = content[: match.start()].rstrip()
    if len(body) > 6000:
        return visible, []
    try:
        payload = json.loads(body)
    except (TypeError, ValueError):
        return visible, []
    actions = payload.get("actions") if isinstance(payload, dict) else None
    if not isinstance(actions, list):
        return visible, []
    return visible, [action for action in actions[:8] if isinstance(action, dict)]

_STATE_LABELS = "当前章节|主角|目的地|特殊物品|状态版本|库存|路线"
_STATE_BULLET = re.compile(rf"(?:^|\s)[\-*•]\s*(?:{_STATE_LABELS})\s*[：:]", re.MULTILINE)
_STATE_HEADING = re.compile(r"(?:^|\n)[^\n。！？.!?]{0,30}(?:浏览器|状态|摘要|信息|概览)[：:]\s*$")
_TECHNICAL_PARAGRAPH = re.compile(
    r"(?:游戏系统|规则引擎|状态(?:已|被)?更新|(?:Flag|location_id|route_id|ending_id)\b)",
    re.IGNORECASE,
)
_MARKDOWN_HEADING = re.compile(r"^\s*#{1,6}\s*")
_CHOICE_META_HEADING = re.compile(
    r"^(?:可能的选择与结果|现在[，,]?请(?:选择|决定你的行动)|选择(?:你的行动)?|选择与结果|"
    r"后续行动|结果|具体行动|接下来的故事进展|下一章预告|下一次行动)\s*[：:]?\s*$"
)
_ACTION_HOOK_HEADING = re.compile(r"^行动钩子\s*[：:]?\s*$")
_LIST_ITEM = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+")
_PLAIN_HEADING = re.compile(
    r"^(?:NPC 反应|与.+的互动|接下来的发展|紧急事件触发|结语|情节推进)\s*[：:]?\s*$"
)


_MODEL_CONTINUATION_HEADING = re.compile(
    r"^(?:response|question|answer|续写)\s*[：:]?$", re.IGNORECASE
)
_MODEL_META_PARAGRAPH = re.compile(
    r"(?:行动钩子|choice_id|chapter_id|motivation|\\boxed|根据(?:故事|情境|对话|之前的情节)"
    r".{0,24}(?:逻辑|分析|选择|发展)|接下来的(?:情节|情景)|因此[，,]?我选择|可以预测|"
    r"状态描述为|请回答[，,]?(?:你们|接下来)|根据(?:语境|已知信息|叙述).{0,80}(?:选择|答案|理由|分析)|"
    r"在转述中|作为答案|理由如下|因此[，,]?答案是|答案是[：:])",
    re.IGNORECASE,
)


def _remove_model_choice_sections(value: str) -> str:
    """Drop Qwen's duplicate choice/meta sections while retaining scene prose."""

    lines = value.splitlines()
    kept: list[str] = []
    skip_until_heading = False
    skip_to_end = False
    hook_section = False
    for raw_line in lines:
        line = raw_line.strip()
        if skip_to_end:
            continue
        heading = _MARKDOWN_HEADING.sub("", line).strip()
        if _CHOICE_META_HEADING.fullmatch(heading):
            skip_until_heading = True
            hook_section = False
            continue
        if line.startswith("#") or _PLAIN_HEADING.fullmatch(heading):
            if _ACTION_HOOK_HEADING.fullmatch(heading):
                hook_section = True
                skip_until_heading = False
                continue
            if skip_until_heading:
                skip_until_heading = False
            # Keep story headings as plain text; raw Markdown markers are not
            # useful in the mobile card and are frequently emitted by Qwen.
            kept.append(heading)
            continue
        if skip_until_heading:
            continue
        if hook_section:
            # A hook emitted as a list is a duplicate of the app's options.
            if not line or _LIST_ITEM.match(line):
                continue
            hook_section = False
        kept.append(raw_line)
    return "\n".join(kept)


def _remove_model_continuation(value: str) -> str:
    """Stop at prompt-like continuation headings emitted after the scene."""

    lines = value.splitlines()
    for index, raw_line in enumerate(lines):
        if _MODEL_CONTINUATION_HEADING.fullmatch(raw_line.strip()):
            return "\n".join(lines[:index]).rstrip()
    return value


def _is_model_meta_paragraph(paragraph: str) -> bool:
    if _MODEL_META_PARAGRAPH.search(paragraph):
        return True
    lines = [line.strip() for line in paragraph.splitlines() if line.strip()]
    if not lines or not all(_LIST_ITEM.match(line) for line in lines):
        return False
    return any(
        re.search(r"(?:角色|负责|被称为|答案|choice_id|chapter_id|motivation)", line, re.IGNORECASE)
        for line in lines
    )


def clean_narrative_output(content: str | None) -> str | None:
    """Remove provider wrappers and accidental technical summaries from prose."""

    if not isinstance(content, str):
        return None
    content, _actions = extract_gm_actions(content)
    if not isinstance(content, str):
        return None
    value = content.strip()
    if value.startswith("<think>") and "</think>" not in value:
        return None
    if "</think>" in value:
        value = value.split("</think>", maxsplit=1)[1].strip()
    if "### TRPG Narrative:" in value:
        value = value.split("### TRPG Narrative:", maxsplit=1)[1]
    if "### JSON:" in value:
        value = value.split("### JSON:", maxsplit=1)[0]
    value = _remove_model_continuation(value.strip())
    value = _remove_model_choice_sections(value.strip())
    value = re.sub(r"^#+\s*", "", value.strip())
    value = re.sub(r"\*{1,2}([^*\n]+)\*{1,2}", r"\1", value)
    value = re.sub(r"^\s*[-*_]{3,}\s*$", "", value, flags=re.MULTILINE)

    state_bullets = list(_STATE_BULLET.finditer(value))
    if len(state_bullets) >= 2:
        prose = value[: state_bullets[0].start()].rstrip()
        prose = _STATE_HEADING.sub("", prose).rstrip()
        value = prose
    paragraphs = re.split(r"\n\s*\n", value)
    value = "\n\n".join(
        paragraph
        for paragraph in paragraphs
        if not _TECHNICAL_PARAGRAPH.search(paragraph)
        and not _is_model_meta_paragraph(paragraph)
    )
    return value.strip() or None


def model_response_was_truncated(provider_type: str, payload: Any) -> bool:
    """Read provider completion metadata instead of guessing from punctuation."""

    if not isinstance(payload, dict):
        return False
    if provider_type == "ollama":
        return payload.get("done_reason") in {"length", "max_tokens"}
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        return False
    return choices[0].get("finish_reason") in {"length", "max_tokens"}
