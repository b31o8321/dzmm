# ============================================================
# Director（导演）提示词模板
# ============================================================
# 【Director 是什么？】
#   在多 Agent 架构里，"GM"角色太复杂——既要写叙事，又要管剧情节奏，
#   又要跟踪 NPC 状态。Director 是从 GM 里分出来的"上层规划者"：
#   它只看当前关键事实 + 玩家行动，然后给 GM 一条简短的"本回合应该发生什么"
#   的指令。GM 再照着这个指令写具体叙事。
#
# 【为什么要分开？】
#   分开有两个好处：
#   1. 减轻 GM 的"认知负担"：GM 只管按指令写好叙事，不用同时规划节奏。
#   2. 可替换：Director 可以换成更小的模型（因为它只输出两行文字），
#      GM 用更大的模型（因为它要写长篇叙事）。
#
# 【这个文件是"旧版 Director"（线性剧本模式）】
#   对应有剧本（screenplay）的游戏。开放世界模式有另一个文件：
#   director_open_world_template.py
# ============================================================

from dzmm.models.client import Message

# Director 的提示词：任务非常明确——只输出两行
# 第一行：本回合核心事件（GM 应该让什么发生）
# 第二行：情绪节点（叙事底色）
# 这样简短的输出比让 GM 自己判断更可控，也更省 token
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
    # 构建给 Director LLM 的消息列表。
    # 注意：Director 只用一条 user 消息，不需要 system 消息。
    # 因为它的任务很简单（两行输出），不需要复杂的角色设定。
    # key_facts.strip() or "（暂无）"：如果 key_facts 是空字符串，
    # Python 的 or 会返回右侧的默认值"（暂无）"。
    return [
        Message(
            role="user",
            content=_TEMPLATE.format(
                key_facts=key_facts.strip() or "（暂无）",
                current_action=current_action.strip(),
            ),
        )
    ]
