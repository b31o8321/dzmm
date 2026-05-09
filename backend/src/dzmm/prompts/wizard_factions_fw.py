from dzmm.models.client import Message

_SYSTEM = """你是开放世界 TRPG 的世界设计师，负责设计势力体系。

输出严格为 JSON 数组：
[
  {
    "name": "势力名",
    "description_md": "2-3句介绍，包括目标和手段",
    "rival_faction_names": ["对立势力名"],
    "ally_faction_names": ["盟友势力名"],
    "tension_rules": {"passive_gain_per_turn": 0, "threshold_conflict": 80}
  }
]

要求：3-5个势力；至少有 1 对对立关系；tension_rules.passive_gain_per_turn 通常 0-2。
"""


def build_factions_messages(genre: str, world_brief_md: str, location_names: list[str]) -> list[Message]:
    locs = "、".join(location_names) if location_names else "无"
    return [
        Message(role="system", content=_SYSTEM),
        Message(role="user", content=f"类型：{genre}\n世界：{world_brief_md}\n主要地点：{locs}\n\n请生成势力 JSON 数组。"),
    ]
