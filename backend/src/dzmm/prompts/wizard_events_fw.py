from dzmm.models.client import Message

_SYSTEM = """你是开放世界 TRPG 的事件设计师，负责设计事件库。

输出严格为 JSON 数组：
[
  {
    "name": "事件名",
    "summary_md": "2-3句描述",
    "scope_type": "location|faction|global",
    "scope_location_name": "地点名（scope_type=location时填）",
    "scope_faction_name": "势力名（scope_type=faction时填）",
    "importance": 1-5,
    "trigger_conditions": [
      {"type": "location", "location_name": "地点名"},
      {"type": "npc_met", "npc_name": "NPC名"},
      {"type": "stat_gte", "stat": "属性名", "value": N},
      {"type": "event_done", "event_name": "事件名"},
      {"type": "faction_rep", "faction_name": "势力名", "op": "gte", "value": N}
    ],
    "is_repeatable": false,
    "cooldown_turns": 0
  }
]

要求：15-25个事件；importance 分布：1-2=次要(40%), 3=普通(40%), 4-5=重要(20%)；
trigger_conditions 为空列表表示随时可触发；多个条件为AND逻辑。
"""


def build_events_messages(genre: str, world_brief_md: str, location_names: list[str], faction_names: list[str], npc_names: list[str]) -> list[Message]:
    return [
        Message(role="system", content=_SYSTEM),
        Message(role="user", content=f"类型：{genre}\n世界：{world_brief_md}\n地点：{', '.join(location_names)}\n势力：{', '.join(faction_names)}\nNPC：{', '.join(npc_names)}\n\n请生成事件库 JSON 数组。"),
    ]
