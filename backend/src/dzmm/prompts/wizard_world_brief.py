"""v0.2.0 wizard step 1 — base world brief (returned as strict JSON)."""
from dzmm.models.client import Message

_SYSTEM = """你是一位经验丰富的 TRPG 世界观设计师。

# 任务
根据玩家提供的「故事类型」和「主题」生成一份**简短的基础世界设定**，
作为后续详细设定 / 角色 / 剧本的种子。

# 输出格式（严格 JSON，**不要 markdown 代码块**，**不要前后加任何文字**）

{
  "name": "世界 / 故事的名字（6-20 字，一行）",
  "setting": "80-150 字：时代背景、地理空间、独有特征——例如：「2089 年的香港九龙城寨」「魔法已枯竭三百年的北方大陆」",
  "conflict": "80-150 字：本世界正在发生 / 即将爆发的最关键矛盾——派系战争 / 神权坍塌 / 灾后求生 / ..."
}

# 强约束
- 输出**必须**是合法 JSON，顶层是 `{...}`
- 必须包含 name / setting / conflict 三个字段，**字段名一字不差**
- 不要 ```json 代码块包裹
- 不要前后加「这是」「以下是」之类的解释
- 风格紧扣 genre 和 theme，不要写成空泛的奇幻
"""


def build_world_brief_messages(genre: str, theme: str) -> list[Message]:
    user = (
        f"# 故事类型\n{genre.strip() or '悬疑探案'}\n\n"
        f"# 主题\n{theme.strip() or '（玩家未指定）'}\n\n"
        "现在生成基础世界设定的 JSON。"
    )
    return [
        Message(role="system", content=_SYSTEM),
        Message(role="user", content=user),
    ]
