"""Wizard suggest NPCs — world+character-aware NPC concept suggestions."""
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
    user = (
        f"# 世界设定\n{world_md.strip()[:1000]}\n\n"
        f"# 主角\n{character_md.strip()[:800]}\n\n"
        "现在给出 4 个 NPC 概念。"
    )
    return [Message(role="system", content=_SYSTEM), Message(role="user", content=user)]
