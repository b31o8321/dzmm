# ============================================================
# 开放世界向导 - NPC 模板库生成（wizard_npc_templates.py）
# ============================================================
# 【开放世界 NPC 模板是什么？】
#   线性剧本模式里，NPC 是预先设计的固定角色。
#   开放世界模式里，NPC 是从"模板库"里实例化的：
#   - 模板定义了 NPC 的基本属性（性格、职业、常驻地点、所属势力）
#   - 游戏开始时，系统从模板创建实际 NPC 实例（存入数据库）
#   - PC 到达某个地点时，该地点的 NPC 就会出现
#
# 【contact_favor_threshold 和 contact_cooldown_turns】
#   这两个字段控制 NPC 何时主动联系 PC：
#   - contact_favor_threshold：PC 与该 NPC 的好感度达到这个值时，
#     NPC 会主动找 PC（Director 会收到提示"建议引入此 NPC"）
#   - contact_cooldown_turns：两次主动联系之间的最少回合数
#     （避免 NPC 每回合都来找 PC）
#
# 【home_location_name 的重要性】
#   这是 NPC 的常驻地点。PC 到达这个地点时才能"自然遇见"这个 NPC。
#   与剧本模式里的 primary_location 类似——防止 NPC 凭空出场。
#
# 【要求覆盖盟友/中立/敌对三类】
#   一个健康的开放世界需要各种关系类型的 NPC，
#   而不是全是友好的 NPC 或全是敌人。
# ============================================================
from dzmm.models.client import Message

_SYSTEM = """你是开放世界 TRPG 的角色设计师，负责设计 NPC 模板库。

输出严格为 JSON 数组：
[
  {
    "name": "NPC名",
    "gender": "male|female",
    "role": "职业/身份",
    "description_md": "2-3句外貌和性格",
    "motivation": "一句话动机",
    "home_location_name": "主要驻留地点名",
    "faction_name": "所属势力名或null",
    "contact_favor_threshold": 70,
    "contact_cooldown_turns": 10
  }
]

要求：8-12个NPC；覆盖多个势力；包含盟友/中立/潜在敌对三类。
"""


def build_npc_templates_messages(genre: str, world_brief_md: str, location_names: list[str], faction_names: list[str]) -> list[Message]:
    # location_names：地点名称列表（NPC 的 home_location_name 必须从这里取）
    # faction_names：势力名称列表（NPC 的 faction_name 必须从这里取，或为 null）
    # 用 ', '.join() 连接成逗号分隔的字符串供 LLM 参考
    return [
        Message(role="system", content=_SYSTEM),
        Message(role="user", content=f"类型：{genre}\n世界：{world_brief_md}\n地点：{', '.join(location_names)}\n势力：{', '.join(faction_names)}\n\n请生成NPC模板 JSON 数组。"),
    ]
