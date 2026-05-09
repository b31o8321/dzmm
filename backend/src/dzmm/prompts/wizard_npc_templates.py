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
    return [
        Message(role="system", content=_SYSTEM),
        Message(role="user", content=f"类型：{genre}\n世界：{world_brief_md}\n地点：{', '.join(location_names)}\n势力：{', '.join(faction_names)}\n\n请生成NPC模板 JSON 数组。"),
    ]
