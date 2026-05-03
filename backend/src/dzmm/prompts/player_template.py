from dzmm.models.client import Message

_TEMPLATE = """你是一名 TRPG 玩家 Agent，正在扮演角色 {character_name}。
根据最近的对话历史，决定你的下一个行动。

# 角色简介
{character_md}

# 最近对话（旧→新）
{recent_history}

# 行动要求
- 直接输出玩家行动（1-2 句话，第一人称）
- 行动要符合角色性格和当前情境
- 可以选择：探索/对话/战斗/使用物品/调查/等待 等类型
- 不要重复刚刚做过的行动
- 只输出行动本身，不要任何前缀或解释

输出："""


def build_player_messages(
    character_name: str,
    character_md: str,
    recent_history: list[tuple[str, str]],  # list of (player_action, gm_response)
) -> list[Message]:
    history_text = "\n\n".join(
        f"[玩家] {action}\n[GM] {response}"
        for action, response in recent_history[-5:]  # Last 5 exchanges
    ) or "（游戏刚开始）"

    return [
        Message(
            role="user",
            content=_TEMPLATE.format(
                character_name=character_name.strip() or "玩家",
                character_md=character_md.strip() or "（未设定）",
                recent_history=history_text,
            ),
        )
    ]
