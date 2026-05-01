"""v0.2.0 wizard step 2 — expand brief into a full 600-1200 字 world markdown."""
from dzmm.models.client import Message

_SYSTEM = """你是一位经验丰富的 TRPG 世界观设计师。

# 任务
玩家已经审阅过基础设定（brief）。现在把它**扩展**为一份完整、可玩的世界观文档。
最终输出 600-1200 字的 markdown，作为 GM 的常驻参考。

# 输出格式（严格 markdown，4 个二级标题，按顺序）

## 地理与环境
（150-300 字：地形 / 气候 / 文明分布 / 自然异象。具体到能让 GM 描写场景）

## 社会与势力
（150-300 字：3-5 个主要势力或阶层，列出名字 + 立场 + 利益冲突。可用 markdown 列表）

## 风俗
（80-200 字：信仰 / 禁忌 / 节庆 / 日常生活习惯——给场景增添异质感）

## 关键地点
（150-300 字：3-5 个有名称的地点，每个一行短描述，**不要长段**。GM 可以让 PC 立刻去到。
推荐用 markdown 列表 `- **名字**：一句描述`）

# 强约束
- 严格 4 个 ## 标题，文字必须是上述四个，不要变体
- 不要 markdown 代码块包裹整体输出
- 不要前后寒暄
- 必须基于玩家已确认的 brief，不要扩写出与 brief 矛盾的内容
"""


def build_world_details_messages(brief_md: str) -> list[Message]:
    brief = brief_md.strip()[:2000] or "（玩家未提供 brief）"
    user = (
        "# 已确认的基础设定（brief）\n"
        f"{brief}\n\n"
        "现在扩展为完整世界观。"
    )
    return [
        Message(role="system", content=_SYSTEM),
        Message(role="user", content=user),
    ]
