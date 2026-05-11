# ============================================================
# 开放世界向导 - 主线剧情框架生成（wizard_campaign_fw.py）
# ============================================================
# 【开放世界的"主线"是什么？】
#   开放世界没有固定章节，但可以有一条"可选的主线"：
#   一个有多个阶段的目标链，玩家可以选择推进或无视。
#   这个主线框架（campaign）提供了游戏的"终点"可能性，
#   避免开放世界变成无目的的闲逛。
#
# 【阶段（phase）的设计】
#   每个阶段包含：
#   - phase_id：阶段编号（从 1 开始）
#   - name：阶段名称
#   - description：1-2句概述这个阶段的目标
#   - prerequisite_phase_ids：必须先完成哪些阶段才能解锁这个阶段
#     （支持非线性结构，如阶段 3 需要完成阶段 1 OR 阶段 2）
#   - key_event_names：推进这个阶段的关键事件列表（从事件库里选）
#   - required_count：需要完成多少个 key_event 才算完成这个阶段
#     （required_count ≤ len(key_event_names)，给玩家一些灵活性）
#
# 【与事件库的关系】
#   key_event_names 里的名字必须来自事件库（wizard_events_fw.py 生成的那些）。
#   这样主线进度就能通过"检查事件完成情况"自动推进，而不是靠 GM 手动判断。
#
# 【"fw" 后缀】
#   同 wizard_factions_fw.py，表示开放世界框架专用。
# ============================================================
from dzmm.models.client import Message

_SYSTEM = """你是开放世界 TRPG 的主线剧情设计师。生成可选的主线剧情框架。

输出严格为 JSON 对象：
{
  "name": "主线名称",
  "phases": [
    {
      "phase_id": 1,
      "name": "阶段名",
      "description": "1-2句阶段概述",
      "prerequisite_phase_ids": [],
      "key_event_names": ["关键事件名1", "关键事件名2"],
      "required_count": 1
    }
  ]
}

要求：3-5个阶段；每阶段 required_count ≤ len(key_event_names)；
key_event_names 只能使用提供的事件名列表中的名字。
"""


def build_campaign_messages(genre: str, world_brief_md: str, event_summaries: list[dict]) -> list[Message]:
    # event_summaries：事件库中所有事件的简要信息（只包含 name 和 importance）
    # 格式化成列表供 LLM 选择，约束 key_event_names 只能引用已存在的事件
    ev_list = "\n".join(f"  - {e['name']}（重要性={e.get('importance',2)}）" for e in event_summaries)
    return [
        Message(role="system", content=_SYSTEM),
        Message(role="user", content=f"类型：{genre}\n世界：{world_brief_md}\n\n可用事件：\n{ev_list}\n\n请生成主线框架 JSON。"),
    ]
