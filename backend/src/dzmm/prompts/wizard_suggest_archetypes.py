"""Wizard suggest archetypes — world-aware character archetype suggestions."""
# ============================================================
# 世界创建向导 - 角色原型建议（wizard_suggest_archetypes.py）
# ============================================================
# 【角色原型（Archetype）是什么？】
#   TRPG 里的"角色原型"是对 PC 类型的简短描述，如：
#   - "失忆的前特工"（背景+能力+戏剧张力一句话说清）
#   - "反抗腐败体制的前线记者"
#   - "被科技公司抛弃的 AI 研究员"
#
#   不是"战士/法师/盗贼"这种游戏职业分类，
#   而是包含"处境 + 性格 + 与世界的张力"的立体角色定位。
#
# 【这一步做什么？】
#   根据世界观，推荐 4 个适合的主角原型供玩家选择。
#   玩家可以选一个作为 PC 的基础，再自定义细节。
#
# 【hook 字段】
#   每个原型有一个 hook：这个角色"最有戏剧潜力的一点"。
#   例如："她曾经亲手处决过自己的搭档，而那个人可能还活着。"
#   hook 是吸引玩家选择这个原型的"卖点"。
#
# 【输出 JSON 的原因】
#   同 wizard_suggest_npcs.py——前端需要用 JSON 渲染选择卡片。
# ============================================================
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
    # 只需要世界观作为输入（不需要角色卡，因为这一步是在帮玩家选角色原型，
    # 还没有角色卡）
    user = (
        f"# 世界设定\n{world_md.strip()[:1500]}\n\n"
        "现在给出 4 个适合该世界的主角原型。"
    )
    return [Message(role="system", content=_SYSTEM), Message(role="user", content=user)]
