"""Open-world Director prompt.

Director 读的是「附近可用事件 + 主线进度」，而非章节列表。
输出格式与旧 Director 相同（plot_directive XML 块），
增加 <event_trigger event_id="N"/> 标签可标记事件触发。
"""
from __future__ import annotations

import json

from dzmm.models.client import Message

_SYSTEM = """你是开放世界 TRPG 的「剧情导演」（Director）。你不写场景描写，不演 NPC 台词。

你的职责：
1. 从候选事件中选择本回合要推动的事件（可以是 0 个）
2. 若有传闻事件，决定是否通过叙事投递（作为旅人传言）
3. 若有 NPC 主动联系提示，决定如何引入
4. 下发简洁剧情指令（plot_directive）

# 候选事件优先级
按 score 从高到低排列。score = 重要性 × 距离系数 + 加成。
score 越高 = 越应该本回合推动。

# 你产出（严格按顺序）

## 步骤一：事件触发声明（可选）
若上回合叙事/PC 行动已让某个候选事件"发生了"，emit：
<event_trigger event_id="N"/>

不确定则不 emit。已触发/已完成的事件不重复触发。

## 步骤二：剧情指令（必做，全文 ≤ 200 字）
<plot_directive>
- 本回合主推：[具体事件名 或 "自由探索"]
- NPC 重点：[0-2 个 NPC + 该做什么，若无则留空]
- 传闻投递：[事件名 或 "无"]
- 节奏：[紧张 / 缓和 / 悬疑 / 揭露 / 决断 之一]
- 禁止：[本回合不该做的 1 件事]
</plot_directive>

铁律：指令可执行，不空话；与上次指令保持连贯；优先推高 score 事件。
"""


def build_open_world_director_messages(
    history: list[Message],
    snapshot: dict,
) -> list[Message]:
    """Build messages for an open-world Director LLM call.

    snapshot keys:
      current_location: str
      pc_summary: str
      companions: list[str]  — companion NPC names
      candidate_events: list[{name, score, importance, summary_md}]
      rumor_events: list[{name, importance, summary_md}]
      proactive_npc: str | None  — NPC name that wants to contact PC
      campaign_phase: str | None
      faction_tensions: list[{name, tension}]
    """
    lines = [
        f"当前地点：{snapshot.get('current_location', '未知')}",
        f"PC 概要：{snapshot.get('pc_summary', '')}",
    ]
    companions = snapshot.get("companions") or []
    if companions:
        lines.append(f"旅伴：{', '.join(companions)}")

    events = snapshot.get("candidate_events") or []
    if events:
        lines.append("\n候选事件（按优先级排序）：")
        for ev in events:
            lines.append(
                f"  - [{ev['importance']}★] {ev['name']}（score={ev['score']:.1f}）：{ev['summary_md']}"
            )
    else:
        lines.append("\n候选事件：无（自由探索回合）")

    rumors = snapshot.get("rumor_events") or []
    if rumors:
        lines.append("\n可投递传闻：")
        for r in rumors:
            lines.append(f"  - {r['name']}（重要性={r['importance']}）：{r['summary_md']}")

    proactive = snapshot.get("proactive_npc")
    if proactive:
        lines.append(f"\n建议本回合引入 NPC 主动联系：{proactive}")

    phase = snapshot.get("campaign_phase")
    if phase:
        lines.append(f"\n主线进度：{phase}")

    tensions = snapshot.get("faction_tensions") or []
    if tensions:
        lines.append("\n势力紧张度：" + "；".join(f"{t['name']}={t['tension']}" for t in tensions))

    user_content = "\n".join(lines)
    msgs: list[Message] = [Message(role="system", content=_SYSTEM)]
    msgs.extend(history)
    msgs.append(Message(role="user", content=user_content))
    return msgs
