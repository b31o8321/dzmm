from dzmm.models.client import Message

_TEMPLATE = """你是 TRPG 规则顾问。分析玩家行动，输出规则预处理指令（仅 GM 看，不出现在叙事里）。

# 当前关键情境
{key_facts}

# 玩家行动
{current_action}

# 输出格式（严格三行，不要其他说明）
行动类型：战斗/社交/探索/潜行/施法/其他（选一个）
技能检定：无 | 或 [技能名] DC[数字]（如：力量检定 DC12）
叙事指令：一句话，本回合应该发生的核心事件

示例输出：
行动类型：战斗
技能检定：力量检定 DC12
叙事指令：PC 奋力推开厚重的铁门，身后的追兵越来越近。
"""


def build_rules_messages(key_facts: str, current_action: str) -> list[Message]:
    return [
        Message(
            role="user",
            content=_TEMPLATE.format(
                key_facts=key_facts.strip() or "（暂无）",
                current_action=current_action.strip(),
            ),
        )
    ]
