# ============================================================
# 开放世界向导 - 势力体系生成（wizard_factions_fw.py）
# ============================================================
# 【开放世界中的势力（Faction）是什么？】
#   势力是开放世界的重要元素：玩家在世界中会接触各种势力，
#   与他们的关系（reputation）影响 NPC 的态度和可用事件。
#
#   每个势力有：
#   - 名称和介绍（包括目标和手段）
#   - 对立势力（rival_faction_names）：互相敌对，PC 帮 A 则 B 对 PC 更冷淡
#   - 盟友势力（ally_faction_names）：PC 和 A 关系好，B 也会好一些
#   - 紧张度规则（tension_rules）：
#       passive_gain_per_turn：每回合自动增加的紧张度（反映势力冲突在自然演化）
#       threshold_conflict：紧张度超过这个值时，两个敌对势力会爆发冲突
#
# 【"fw" 后缀是什么？】
#   "fw" = "framework"（框架），表示这是开放世界框架（open-world framework）
#   专用的生成器，区别于线性剧本向导里的类似功能。
#
# 【输出 JSON 数组的原因】
#   后端用 JSON 初始化势力数据库表，并在每回合追踪
#   各势力的紧张度和 PC 与各势力的声望值。
# ============================================================
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
    # location_names：地点名称列表（让势力与具体地点绑定，如某势力"控制北方港口"）
    # 用"、"连接成一个短句，供 LLM 参考
    locs = "、".join(location_names) if location_names else "无"
    return [
        Message(role="system", content=_SYSTEM),
        Message(role="user", content=f"类型：{genre}\n世界：{world_brief_md}\n主要地点：{locs}\n\n请生成势力 JSON 数组。"),
    ]
