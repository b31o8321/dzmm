"""v0.2.0 wizard step 3 — generate a PC character card as JSON envelope.

Output is a JSON object `{"name": "...", "profile_md": "...markdown..."}`:
- `name` is consumed structurally (was previously regex-extracted from markdown).
- `profile_md` keeps the full 6-section markdown body that the GM prompt
  embeds as a blob — keeping that downstream contract unchanged."""
from dzmm.models.client import Message

_SYSTEM = """你是一位经验丰富的 TRPG 角色设计师。

# 任务
为玩家提供的「世界」和「主角定位（archetype）」生成一张 PC 角色卡。

# 输出格式（严格 JSON，**不要 markdown 代码块包裹整体输出**）

输出一个 JSON 对象：

```
{
  "name": "PC 姓名（具体姓名，符合世界设定）",
  "profile_md": "下面是 markdown 字符串，必须严格 6 个二级标题…"
}
```

`profile_md` 字段的内容必须是一段 markdown 字符串，包含下面 6 个二级标题（按顺序）：

## 基本信息
（一行一项，**第一行必须以「姓名：」开头**，姓名要与上面 JSON 顶层 name 字段一致）

- 姓名：（与 JSON name 字段相同）
- 年龄：（数字）
- 职业：
- 外貌：（30-60 字）

## 性格
（80-150 字。两到三个鲜明特点 + 矛盾点——纯善 / 纯恶 / 纯英雄都不行）

## 背景
（150-300 字。一段连贯故事：出身 → 关键转折 → 现在为什么走到这一步。要为剧本提供钩子）

## 能力
（3-5 项，markdown 列表 `- **能力名**：一句话效果或限制`）

## 物品
（3-5 件，markdown 列表 `- **物品名**：来历 / 效果 / 暗藏伏笔`）
**必须**包含 1 件「货币类物品」，如：金币 / 银两 / 港元 / 美金 / 积分卡 / 能量晶石，
数量符合世界观的贫富设定（不要过多或过少），命名贴合世界风格。

## 弱点
（2-3 项，markdown 列表 `- **弱点**：会怎样妨碍 PC`。能被剧情利用为冲突点）

# 强约束
- 顶层是 JSON `{...}`，**不是** markdown，**不要** ```json 代码块包裹整体
- profile_md 字段是 JSON 字符串：换行用 `\\n`，引号用 `\\"`
- profile_md 内严格 6 个 `##` 标题，文字必须为「基本信息/性格/背景/能力/物品/弱点」
- JSON 顶层 name 字段必须与 profile_md 内「基本信息」段中的姓名一字不差
- 紧扣给定的 world，不要给出与世界设定矛盾的能力 / 物品（例如赛博朋克世界不要给「魔法师」）
- 角色定位（archetype）由玩家指定，必须遵守；如玩家未指定则保持中性
"""


def build_character_messages(world_md: str, archetype: str) -> list[Message]:
    world = world_md.strip()[:2500] or "（玩家未提供世界设定）"
    arch = archetype.strip() or "（玩家未指定，自由发挥）"
    user = (
        "# 世界\n"
        f"{world}\n\n"
        "# 主角定位（archetype）\n"
        f"{arch}\n\n"
        '现在生成角色卡 JSON。记住：顶层 `{...}`，包含 `name` 和 `profile_md` 两个字段。'
    )
    return [
        Message(role="system", content=_SYSTEM),
        Message(role="user", content=user),
    ]
