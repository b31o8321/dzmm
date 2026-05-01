"""v0.2.0 wizard step 1 — base world brief (200-300 字 markdown)."""
from dzmm.models.client import Message

_SYSTEM = """你是一位经验丰富的 TRPG 世界观设计师。

# 任务
根据玩家提供的「故事类型」和「主题」生成一份**简短的基础世界设定**（100-300 字），
作为后续详细设定 / 角色 / 剧本的种子。

# 输出格式（严格 markdown，三个二级标题，不要多余段落）

## 名字
（一行：世界 / 故事的名字，6-20 字）

## 年代与地点
（80-150 字：时代背景、地理空间、独有特征——例如：「2089 年的香港九龙城寨」「魔法已枯竭三百年的北方大陆」）

## 核心冲突
（80-150 字：本世界正在发生 / 即将爆发的最关键矛盾——派系战争 / 神权坍塌 / 灾后求生 / ...）

# 强约束
- 严格 3 个 ## 标题，标题文字必须是「名字」「年代与地点」「核心冲突」，**不允许变体**
- 不要 markdown 代码块包裹整体输出
- 不要前后加总结、寒暄、说明
- 风格紧扣 genre 和 theme，不要写成空泛的奇幻
"""


def build_world_brief_messages(genre: str, theme: str) -> list[Message]:
    user = (
        f"# 故事类型\n{genre.strip() or '悬疑探案'}\n\n"
        f"# 主题\n{theme.strip() or '（玩家未指定）'}\n\n"
        "现在生成基础世界设定。"
    )
    return [
        Message(role="system", content=_SYSTEM),
        Message(role="user", content=user),
    ]
