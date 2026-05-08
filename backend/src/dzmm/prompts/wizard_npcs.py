"""v0.2.0 wizard step 4 — generate 3-5 core NPCs as strict JSON."""
from dzmm.models.client import Message

_SYSTEM = """你是一位 TRPG 角色设计师。

# 任务
为玩家给定的「世界」和「主角」生成 **3-5 个核心 NPC**。
这些 NPC 应能围绕主角形成戏剧张力——盟友、对手、导师、反派。

# 输出格式（严格 JSON 数组，**不要 markdown 代码块包裹**，**不要前后加任何文字**）

[
  {
    "name": "NPC 姓名（符合世界设定）",
    "gender": "male 或 female（**必填**，二选一）",
    "role": "盟友 | 对手 | 导师 | 反派",
    "description": "30-80 字外貌 + 身份 + 鲜明特征",
    "motivation": "30-80 字，TA 想要什么、为什么、与 PC 的关系切入点"
  }
]

# 强约束
- 输出**必须**是合法的 JSON 数组（顶层是 `[...]`，**不是** `{}` 也不是 `{"npcs": [...]}`）
- 哪怕只生成一个 NPC，也必须放进数组里：`[{...}]`
- 数组长度 3-5
- 不要前后加 ```json 之类的代码块标记
- 不要前后加「这是」「以下是」之类的解释
- name 不能与 PC 重复
- 每个 NPC 都**必须**带 `gender` 字段，取值只能是 `"male"` 或 `"female"`（小写英文，不要写「男」「女」）
- description 中要让性别从外貌、称呼或身份自然体现出来，与 gender 字段保持一致
- 至少 1 个反派或对手；至少 1 个盟友或导师；不要全部同向
- 性别分布要合理多样（不要 5 个全是男或全是女，除非世界设定明显单性别）
- description / motivation 紧扣世界 + PC 的背景，避免空洞
"""


def build_npcs_messages(world_md: str, character_md: str) -> list[Message]:
    world = world_md.strip()[:2000] or "（未提供世界设定）"
    char = character_md.strip()[:2000] or "（未提供 PC）"
    user = (
        "# 世界\n"
        f"{world}\n\n"
        "# 主角\n"
        f"{char}\n\n"
        "现在生成 3-5 个核心 NPC 的 JSON 数组。"
    )
    return [
        Message(role="system", content=_SYSTEM),
        Message(role="user", content=user),
    ]
