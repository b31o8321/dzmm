# ============================================================
# NPC 反应提示词（npc_react_template.py）
# ============================================================
# 【这个文件的历史背景】
#   这是更早期的"NPC 反应"实现，现在已被 npc_actor_template.py 取代。
#   文件里保留了两个版本：
#   1. 旧版（_TEMPLATE）：一次性处理多个 NPC，检查叙事里有没有遗漏的反应
#   2. 新版（_SINGLE_NPC_TEMPLATE）：单个 NPC 独立调用，人设更丰富
#
# 【为什么要解析 GM 的输出？】
#   GM 输出是一段混合了 XML 标签和自然文本的字符串。
#   我们需要从中提取出 NPC 的状态变化，更新数据库里的 NPC 档案。
#   如果 GM 漏写了某个 NPC 的反应，可以用这个 Agent 补充。
#
# 【这个文件现在的用途】
#   在不使用多 Agent 架构的简单模式下，可以用这里的函数
#   做轻量级的"NPC 反应补充"。完整的多 Agent 模式见 npc_actor_template.py。
# ============================================================

import json as _json

from dzmm.models.client import Message

# ── 旧版（多 NPC 列表，保留供参考） ─────────────────────────────
# 这个模板的设计：给 LLM 一段 GM 的叙事，让它检查有没有遗漏的 NPC 反应。
# 如果有，补充输出 <npc_update> 标签；如果叙事已经足够，输出 "none" 表示无需补充。
_TEMPLATE = """你是 TRPG NPC 行为顾问。根据本回合叙事，判断在场 NPC 是否有额外反应需要补充。

# 本回合叙事（GM 刚刚生成）
{narrative}

# 玩家行动
{user_action}

# 在场 NPC 列表
{npc_list}

# 任务
检查上面的叙事里是否有遗漏的 NPC 反应。如果有需要补充的 NPC 状态变化，
用 XML 格式输出（每个 NPC 一个标签）：
<npc_update name="NPC名字">新的状态描述</npc_update>

如果叙事已经足够完整，不需要补充，输出：
<npc_update name="none">无需补充</npc_update>

只输出 XML，不要其他说明。
"""


def build_npc_react_messages(
    narrative: str,
    present_npcs: list[str],  # 在场 NPC 的名字列表（字符串，不是 ORM 对象）
    user_action: str,
) -> list[Message]:
    # 把在场 NPC 列表格式化成 markdown 列表，方便 LLM 阅读
    # 如果没有在场 NPC，用"（无在场 NPC）"表示
    npc_list = "\n".join(f"- {npc}" for npc in present_npcs) if present_npcs else "（无在场 NPC）"
    return [
        Message(
            role="user",  # 这个旧版模板只用 user 消息，没有 system 消息
            content=_TEMPLATE.format(
                narrative=narrative.strip() or "（无叙事）",
                user_action=user_action.strip(),
                npc_list=npc_list,
            ),
        )
    ]


# ── 新版（单 NPC 独立调用，人设更丰富） ──────────────────────────
# 改进点：每次只处理一个 NPC，提供更详细的人设（性格原型、动机、当前情绪），
# 让 LLM 能生成更符合角色性格的反应，而不是通用的"NPC 反应"。
# 缺点：需要为每个在场 NPC 单独调用一次 LLM（更慢、更贵），
# 所以在完整的多 Agent 架构里被 npc_actor_template.py 取代了。
_SINGLE_NPC_TEMPLATE = """你正在扮演 TRPG 中的 NPC「{name}」。根据本回合叙事，决定你的反应。

# 角色设定
- 姓名：{name}
- 性格原型：{archetype}
- 人物简介：{description}
- 目的/动机：{purpose}
- 当前状态：{state}
- 当前情绪：{emotions}

# 本回合叙事（GM 刚刚生成）
{narrative}

# 玩家行动
{user_action}

# 任务
以「{name}」的性格和当前状态，判断这一刻是否需要补充反应。
你的反应必须符合「{archetype}」的性格特征，不能与其他角色混淆。

只输出 XML，不要其他说明：

如果需要补充（动作/台词/状态变化）：
<npc_update name="{name}">具体反应（1-2 句，符合人物性格）</npc_update>

如果叙事中已经完整描述了「{name}」的反应：
<npc_update name="none">无需补充</npc_update>
"""


def build_npc_single_react_messages(
    narrative: str,
    npc,  # NPC ORM 对象：有 .name、.archetype、.description、.state、.purpose、.emotion_json 属性
    user_action: str,
) -> list[Message]:
    # 从 NPC 的 emotion_json 字段解析当前情绪（JSON 字符串 → 字典 → 格式化文本）
    try:
        emotions_dict = _json.loads(npc.emotion_json or "{}")
        emotions_str = (
            ", ".join(f"{k}:{v}" for k, v in emotions_dict.items())
            if emotions_dict
            else "无"
        )
    except (ValueError, TypeError):
        emotions_str = "无"

    return [
        Message(
            role="user",
            content=_SINGLE_NPC_TEMPLATE.format(
                name=(npc.name or "未知").strip(),
                archetype=(npc.archetype or "普通人").strip() or "普通人",
                description=(npc.description or "（无简介）").strip()[:300],
                purpose=(npc.purpose or "（未知）").strip()[:200],
                state=(npc.state or "未知").strip(),
                emotions=emotions_str,
                narrative=narrative.strip() or "（无叙事）",
                user_action=user_action.strip(),
            ),
        )
    ]
