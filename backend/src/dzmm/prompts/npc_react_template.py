from dzmm.models.client import Message

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
