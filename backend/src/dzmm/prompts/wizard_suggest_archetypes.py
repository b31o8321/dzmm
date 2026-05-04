"""Wizard suggest archetypes — world-aware character archetype suggestions."""
from dzmm.models.client import Message

_SYSTEM = """你是 TRPG 角色设计师。

# 任务
根据已生成的世界设定，给出 4 个适合该世界的「主角原型」供玩家选择。

# 输出格式（严格 JSON，不加任何前后文字）
{
  "archetypes": [
    {"description": "...(10-25字，角色定位+核心特征，要具体)", "hook": "...(10-20字，这个角色最有戏剧潜力的一点)"},
    {"description": "...", "hook": "..."},
    {"description": "...", "hook": "..."},
    {"description": "...", "hook": "..."}
  ]
}

# 要求
- 4 个原型职业/背景/性格明显不同
- description 必须具体——有个人特征和处境，不能是「勇敢的战士」「神秘的刺客」
- hook 点出这个角色与世界冲突的戏剧性来源
- 紧扣世界设定，原型要在该世界里站得住脚
"""


def build_suggest_archetypes_messages(world_md: str) -> list[Message]:
    user = (
        f"# 世界设定\n{world_md.strip()[:1500]}\n\n"
        "现在给出 4 个适合该世界的主角原型。"
    )
    return [Message(role="system", content=_SYSTEM), Message(role="user", content=user)]
