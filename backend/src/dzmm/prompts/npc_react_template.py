import json as _json

from dzmm.models.client import Message

# ── 旧版（多 NPC 列表，保留供参考） ─────────────────────────────
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
    present_npcs: list[str],
    user_action: str,
) -> list[Message]:
    npc_list = "\n".join(f"- {npc}" for npc in present_npcs) if present_npcs else "（无在场 NPC）"
    return [
        Message(
            role="user",
            content=_TEMPLATE.format(
                narrative=narrative.strip() or "（无叙事）",
                user_action=user_action.strip(),
                npc_list=npc_list,
            ),
        )
    ]


# ── 新版（单 NPC 独立调用，人设更丰富） ──────────────────────────
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
    npc,  # NPC ORM object: .name, .archetype, .description, .state, .purpose, .emotion_json
    user_action: str,
) -> list[Message]:
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
