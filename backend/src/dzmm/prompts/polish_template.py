from dzmm.models.client import Message

_TEMPLATE = """你是 TRPG 文学润色师。把下面的跑团 GM 叙事文本润色得更有文学质感，不改变任何情节内容、NPC 对话、或事件结果。

润色原则：
- 优化句式和节奏，避免平铺直叙
- 加强感官细节（视觉/听觉/触觉），但不添加新信息
- 保持原有语气和风格（暗黑/治愈/写实等）
- 保留所有专有名词（人名/地名）原样
- 不添加新角色、新道具、新剧情

# 原文
{narrative}

直接输出润色后的文本，不要任何解释。长度控制在原文的 90%-120% 之间。
"""


def build_polish_messages(narrative: str) -> list[Message]:
    return [
        Message(
            role="user",
            content=_TEMPLATE.format(narrative=narrative.strip()),
        )
    ]
