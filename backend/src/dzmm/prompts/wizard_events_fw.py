# ============================================================
# 开放世界向导 - 事件库生成（wizard_events_fw.py）
# ============================================================
# 【开放世界事件库是什么？】
#   开放世界没有固定剧本，但有"事件库"：
#   预先设计好的 15-25 个事件，每个事件有触发条件。
#   Director 每回合从这个库里选取最合适的事件推给 GM 执行。
#
# 【事件触发条件（trigger_conditions）】
#   trigger_conditions 是一个列表，多个条件是"AND"逻辑（全部满足才触发）：
#   - type: "location"：PC 在指定地点
#   - type: "npc_met"：PC 已经认识某个 NPC
#   - type: "stat_gte"：PC 的某项属性 ≥ 某个值
#   - type: "event_done"：另一个事件已经完成
#   - type: "faction_rep"：PC 与某个势力的声望满足条件
#   空列表 [] 表示"任何时候都可以触发"
#
# 【scope_type 字段】
#   事件影响的范围：
#   - location：只影响特定地点（如"小屋里发现日记"）
#   - faction：与特定势力相关（如"商会要求协助"）
#   - global：影响整个世界（如"大灾难爆发"）
#
# 【importance 分布要求】
#   1-2=次要（40%）、3=普通（40%）、4-5=重要（20%）
#   这个分布确保世界有足够的"日常小事"，不是每回合都是大事件。
#
# 【is_repeatable 和 cooldown_turns】
#   is_repeatable：false=每局游戏只触发一次，true=可以重复
#   cooldown_turns：重复触发之间需要间隔多少回合
# ============================================================
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
    "trigger_conditions": <v0.15 谓词，见下>,
    "is_repeatable": false,
    "cooldown_turns": 0
  }
]

# trigger_conditions 格式（v0.15 谓词）

trigger_conditions 是单个谓词对象（不是数组），支持以下格式：

单条件（直接使用 type 字段）：
  {"type": "location_reached", "location_name": "圣殿"}
  {"type": "npc_state", "npc_template_name": "李影", "state": "dead"}
  {"type": "stat_threshold", "stat": "hp", "op": "lte", "value": 5}
  {"type": "item_owned", "item_name": "古老地图", "min_qty": 1}
  {"type": "faction_tension", "faction_name": "暗夜公会", "op": "gte", "value": 70}

AND 组合（所有子条件同时满足才触发）：
  {"type": "all", "children": [{"type": "location_reached", "location_name": "地点A"}, {"type": "stat_threshold", "stat": "hp", "op": "lte", "value": 10}]}

OR 组合（任一子条件满足即触发）：
  {"type": "any", "children": [{...}, {...}]}

空触发（任何时候都可以触发）：
  {"type": "all", "children": []}

注意：
- 用 _name 后缀（location_name、npc_template_name、faction_name）填写名字，Python 会自动解析为 ID
- op 支持：gte / lte / gt / lt / eq
- stat 支持：hp / sanity / stamina / doom_score
- state 支持：dead / alive / contacted

要求：15-25个事件；importance 分布：1-2=次要(40%), 3=普通(40%), 4-5=重要(20%)；
trigger_conditions 不可为 null，无条件事件用 {{"type": "all", "children": []}}；单条件直接用对应 type，不要包成 all/any。
"""


def build_events_messages(genre: str, world_brief_md: str, location_names: list[str], faction_names: list[str], npc_names: list[str]) -> list[Message]:
    # 传入地点名、势力名、NPC 名，让 LLM 生成的触发条件引用真实的名字
    # 避免 LLM 发明不存在的地点/势力/NPC 名称
    return [
        Message(role="system", content=_SYSTEM),
        Message(role="user", content=f"类型：{genre}\n世界：{world_brief_md}\n地点：{', '.join(location_names)}\n势力：{', '.join(faction_names)}\nNPC：{', '.join(npc_names)}\n\n请生成事件库 JSON 数组。"),
    ]
