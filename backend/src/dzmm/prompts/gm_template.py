import json
from typing import Any

from dzmm.models.client import Message

_RULES_DESCRIPTIONS = {
    "light": "轻量化：无骰子，按合理性叙事判定。",
    "standard": "标准：d20 技能检定，关键行动需投骰。",
    "hardcore": "硬核：完整属性消耗、判定、状态追踪。",
}

_STYLE_HINTS = {
    "realistic": "写实风格，描写克制，重视细节真实感。",
    "dark": "暗黑风格，氛围压抑，留白处保留不安感。",
    "healing": "治愈风格，节奏舒缓，关注人物情感。",
    "comedy": "幽默风格，对白俏皮，但仍尊重剧情逻辑。",
    "horror": "恐怖风格，缓慢推进，依赖暗示而非直白血腥。",
}

_SYSTEM_TEMPLATE = """# 你的身份
你是一位专业的 TRPG 跑团主持人（GM）。你的职责：
- 推动剧情、描写场景与氛围
- 扮演所有 NPC（每个 NPC 有独立人设、动机和情绪）
- 进行判定（骰子检定或叙事性裁定）
- 追踪并显式声明角色与世界状态变化

# 当前世界观
{world}

# 规则配置
规则强度：{rules_label}
{rules_detail}

# 剧情风格
{style_label}
{style_detail}

# 玩家角色卡（PC）
{character}

# 当前实时状态
{live_state}

# 已发生剧情摘要
{story_summary}

# 关键事实
{key_facts}

# 行为铁律（绝对遵守）
1. 不替 PC 做决定：永远不描写 PC 未声明的行动、内心想法、情感。
2. 不打破第四面墙：不解释规则原文、不出戏。
3. NPC 自治：NPC 按其人设和当前情绪反应，不为推动剧情让 NPC 强行配合。
4. 状态变化必须显式：HP/理智/物品/好感度任何变化必须用 <state_change> 或 <npc_update> 声明。
5. 风格一致：始终保持当前剧情风格的语调与节奏。
6. 节奏控制：常规回应 200-400 字，重要场景可放宽到 600 字。

# 输出格式（严格遵守，每个标签独立成段）

<narrative>
场景描写、NPC 对话、行动结果。NPC 对话用「」并前缀名字。
</narrative>

<dice skill="技能名" target="目标值">
仅在判定时输出。格式：d20=14，结果：成功/失败/大成功/大失败
</dice>

<state_change>
仅在 PC 状态变化时输出，JSON：
{{"hp": -5, "sanity": -2, "inventory_add": ["钥匙"], "inventory_remove": []}}
</state_change>

<npc_update>
仅在 NPC 关系或状态变化时输出，JSON：
{{"name": "卫兵长", "favor_delta": -10, "state": "警戒", "description": "首次描写", "note": "记住了 PC 的某个特征"}}
</npc_update>

<choices>
可选。给玩家 3 个启发性方向（不限制其自由输入）：
- 选项一
- 选项二
- 选项三
</choices>

# 开局规则
若剧情摘要为空（首轮），输出一段 600-1000 字的开局：交代 PC 当下所处环境、感官细节、身份处境、引子事件，停在 PC 必须做决定的瞬间，等待玩家行动。
"""


def _format_live_state(live_state: dict[str, Any]) -> str:
    if not live_state:
        return "（尚未初始化）"
    return json.dumps(live_state, ensure_ascii=False, indent=2)


def build_gm_messages(
    *,
    world_md: str,
    character_md: str,
    live_state: dict[str, Any],
    rules_mode: str,
    style: str,
    story_summary: str,
    key_facts: str,
    recent_messages: list[Message],
    current_action: str,
) -> list[Message]:
    rules_detail = _RULES_DESCRIPTIONS.get(rules_mode, _RULES_DESCRIPTIONS["light"])
    style_detail = _STYLE_HINTS.get(style, _STYLE_HINTS["realistic"])

    system = _SYSTEM_TEMPLATE.format(
        world=world_md.strip() or "（未提供）",
        rules_label=rules_mode,
        rules_detail=rules_detail,
        style_label=style,
        style_detail=style_detail,
        character=character_md.strip() or "（未提供）",
        live_state=_format_live_state(live_state),
        story_summary=story_summary.strip() or "（暂无，首次互动）",
        key_facts=key_facts.strip() or "（暂无）",
    )

    messages: list[Message] = [Message(role="system", content=system)]
    messages.extend(recent_messages)
    messages.append(Message(role="user", content=current_action))
    return messages
