"""Wizard suggest endpoint — generate 4 creative game scenario packages."""
from dzmm.models.client import Message

_SYSTEM = """你是一位资深 TRPG（桌面角色扮演）创意总监，擅长为玩家提供新颖的开局灵感。

# 任务
生成 4 个风格各异的 TRPG 故事方案供玩家选择。每个方案包含：
- genre：题材类型（2-8 字，如「赛博朋克」「克苏鲁恐怖」「武侠江湖」「末日求生」）
- theme：一句话主题（20-50 字，具体有画面感，直接点出最吸引人的核心矛盾或场景）
- archetype：主角原型（10-25 字，有个性有缺陷，能感受到具体的人物）

# 输出格式（严格 JSON，不要额外文字）
{
  "suggestions": [
    {"genre": "...", "theme": "...", "archetype": "..."},
    {"genre": "...", "theme": "...", "archetype": "..."},
    {"genre": "...", "theme": "...", "archetype": "..."},
    {"genre": "...", "theme": "...", "archetype": "..."}
  ]
}

# 质量要求
- 4 个方案必须风格明显不同（不能都是奇幻）
- theme 要有具体画面，不能是「英雄救世」「寻找自我」这种空洞描述
- archetype 要有具体缺陷或特殊情境，不能是「勇敢的战士」这种模板
- 优先中国玩家熟悉的文化语境和故事背景
"""


def build_suggest_messages(genre_hint: str = "") -> list[Message]:
    if genre_hint and genre_hint != "自定义":
        user = (
            f"玩家偏好的题材方向是「{genre_hint}」，"
            "请在此基础上给出 4 个有创意的故事方案（可以都在该题材内，也可以融合相邻题材）。"
            "\n\n现在输出 JSON。"
        )
    else:
        user = (
            "玩家还没有确定题材，请给出 4 个风格完全不同的故事方案来帮助选择。"
            "\n\n现在输出 JSON。"
        )
    return [
        Message(role="system", content=_SYSTEM),
        Message(role="user", content=user),
    ]
