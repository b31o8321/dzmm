from dzmm.models.client import Message

_TEMPLATE = """你是 TRPG 导演助理。当前跑团即将开始新的一回合，你的任务是给 GM 一条简短的方向性预处理指令。

# 当前关键事实
{key_facts}

# 玩家行动
{current_action}

# 输出要求（严格）
两行，不超过 80 字：
第一行：本回合核心事件（GM 应该让什么事情发生或推进）
第二行：推荐情绪节点（本回合的情绪底色：紧张/温情/悬疑/对峙/喘息…）

格式示例：
核心事件：NPC 小翠揭露她知道凶手身份，但要求 PC 先帮她完成一件事。
情绪节点：紧绷与期待交织，有一丝希望。

直接输出两行，不要其他说明。
"""


def build_director_messages(key_facts: str, current_action: str) -> list[Message]:
    return [
        Message(
            role="user",
            content=_TEMPLATE.format(
                key_facts=key_facts.strip() or "（暂无）",
                current_action=current_action.strip(),
            ),
        )
    ]
