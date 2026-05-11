# ============================================================
# 玩家 Agent 提示词（player_template.py）
# ============================================================
# 【这是什么？】
#   在自动评测（eval）模式下，没有真实玩家操作游戏。
#   需要用一个 LLM 来"模拟玩家"，自动生成玩家的行动输入。
#   这个文件定义了"玩家 Agent"的提示词。
#
# 【为什么需要模拟玩家？】
#   评测 GM 质量时，需要跑很多回合才能发现问题（如剧情停滞、规则违反等）。
#   让真人玩 20 回合来评测太耗时，所以用 LLM 自动扮演玩家，
#   全程无人干预地完成几十回合的游戏，再让评判 Agent 打分。
#   这叫"自动化评测"（Automated Evaluation）。
#
# 【玩家 Agent 的设计原则】
#   - 符合角色性格：不同性格的角色会有不同的行动倾向
#   - 不重复行动：避免陷入"我继续等待 → GM 没事可做"的死循环
#   - 简短输出：1-2 句话，像真实玩家输入一样简洁
#   - 第一人称：像真人玩家一样用"我"来描述行动
#
# 【recent_history 参数说明】
#   传入最近 5 回合的对话对（玩家行动, GM 回复），
#   让玩家 Agent 知道剧情进展到哪里，避免重复刚做过的事。
# ============================================================
from dzmm.models.client import Message

# 玩家 Agent 的提示词：角色 + 最近对话 + 行动要求
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
    recent_history: list[tuple[str, str]],  # 格式：[(玩家行动, GM回复), ...]
) -> list[Message]:
    # 把对话历史格式化成易读的文本
    # recent_history[-5:]：只取最近 5 回合（太多的历史 token 消耗大，且旧的对话对当前决策影响小）
    # 如果历史为空（游戏刚开始），显示"（游戏刚开始）"
    history_text = "\n\n".join(
        f"[玩家] {action}\n[GM] {response}"
        for action, response in recent_history[-5:]  # 只取最近 5 回合
    ) or "（游戏刚开始）"

    return [
        Message(
            role="user",  # 玩家 Agent 用 user 消息（无需 system 消息，任务简单）
            content=_TEMPLATE.format(
                character_name=character_name.strip() or "玩家",
                character_md=character_md.strip() or "（未设定）",
                recent_history=history_text,
            ),
        )
    ]
