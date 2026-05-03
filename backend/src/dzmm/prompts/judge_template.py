from dzmm.models.client import Message

_TEMPLATE = """你是 TRPG 质量评审 Agent。评估以下游戏对话（最近 {n_turns} 回合）的质量。

# 世界观摘要
{world_summary}

# 最近对话记录
{recent_history}

# 评分维度
1. **剧情推进速度**（plot_speed, 0-10）：主线事件是否有推进？每2-3回合是否有明显进展？
2. **铁律违反次数**（rule_violations, 整数）：GM 明显规则违反次数（0=完美）
3. **RP 沉浸感**（rp_immersion, 0-10）：叙事是否生动？NPC 是否有个性？
4. **骰子规则准确性**（dice_accuracy, 0-10）：骰子判定是否合理？失败是否有实质后果？（无骰子记 7）

# 输出格式（严格 JSON，不要其他内容）
{{
  "plot_speed": 数字,
  "rule_violations": 整数,
  "rp_immersion": 数字,
  "dice_accuracy": 数字,
  "reasoning": "一句话总体评价（50字以内）"
}}"""


def build_judge_messages(
    world_summary: str,
    recent_history: list[tuple[str, str]],  # list of (player_action, gm_response)
    n_turns: int,
) -> list[Message]:
    history_text = "\n\n".join(
        f"[回合 {i+1}]\n玩家：{action}\nGM：{response[:300]}{'...' if len(response) > 300 else ''}"
        for i, (action, response) in enumerate(recent_history)
    ) or "（无对话记录）"

    return [
        Message(
            role="user",
            content=_TEMPLATE.format(
                world_summary=(world_summary or "（未提供）")[:500],
                recent_history=history_text,
                n_turns=n_turns,
            ),
        )
    ]
