"""Wizard suggest NPCs — world+character-aware NPC concept suggestions."""
# ============================================================
# 世界创建向导 - NPC 概念建议（wizard_suggest_npcs.py）
# ============================================================
# 【这一步做什么？】
#   根据已有的世界观和玩家角色卡，为玩家推荐 4 个适合加入游戏的 NPC 概念。
#   玩家可以选择其中一部分、全部，或者完全自定义 NPC。
#
# 【为什么需要 NPC 建议？】
#   设计有戏剧张力的 NPC 对新手玩家来说很困难。
#   好的 NPC 需要：
#   1. 与世界观一致（如中世纪奇幻世界不要出现赛博格刺客）
#   2. 与主角有关联（至少有一个盟友、一个对手）
#   3. 有具体的动机（而不是"他是个坏人"这种空泛设定）
#   4. 性别多样（避免全是男性或全是女性）
#
# 【输出 JSON 的原因】
#   4 个 NPC 概念以 JSON 数组返回，前端可以渲染成卡片供玩家选择。
#   如果是纯文本，就很难让玩家点选特定 NPC 加入游戏。
# ============================================================
from dzmm.models.client import Message

_SYSTEM = """你是 TRPG NPC 设计师。

# 任务
根据世界设定和主角卡，给出 4 个适合该故事的 NPC 概念供玩家选择添加。

# 输出格式（严格 JSON，不加任何前后文字）
{
  "npcs": [
    {
      "name": "...(2-6字中文名)",
      "gender": "male 或 female（**必填**，二选一）",
      "role": "...(2-6字角色定位，如：神秘线人 / 昔日对手 / 地下医生)",
      "description": "...(20-40字，外形+性格+处境，具体有辨识度)",
      "motivation": "...(10-20字，核心驱动力)"
    }
  ]
}

# 要求
- 4 个 NPC 彼此关系定位不同（至少有 1 个盟友、1 个潜在对手、1 个中立/功能性角色）
- name 要符合世界观风格
- gender 字段**必填**，只能是 `"male"` 或 `"female"`；4 个之间性别要有多样性
- description 要具体有画面感，不能是「神秘的老人」；外形/称谓与 gender 一致
- motivation 要能驱动故事冲突或推进
- 紧扣已有世界设定和主角特点
"""


def build_suggest_npcs_messages(world_md: str, character_md: str) -> list[Message]:
    # world_md：完整世界观 Markdown（第 2 步的输出）
    # character_md：玩家角色卡 Markdown
    # 两者都截断到合理长度（1000/800 字），避免 token 超限
    user = (
        f"# 世界设定\n{world_md.strip()[:1000]}\n\n"
        f"# 主角\n{character_md.strip()[:800]}\n\n"
        "现在给出 4 个 NPC 概念。"
    )
    return [Message(role="system", content=_SYSTEM), Message(role="user", content=user)]
