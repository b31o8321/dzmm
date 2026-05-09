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
    ev_list = "\n".join(f"  - {e['name']}（重要性={e.get('importance',2)}）" for e in event_summaries)
    return [
        Message(role="system", content=_SYSTEM),
        Message(role="user", content=f"类型：{genre}\n世界：{world_brief_md}\n\n可用事件：\n{ev_list}\n\n请生成主线框架 JSON。"),
    ]
