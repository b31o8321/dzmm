"""Open-world Director prompt.

Director 读的是「附近可用事件 + 主线进度」，而非章节列表。
输出格式与旧 Director 相同（plot_directive XML 块），
增加 <event_trigger event_id="N"/> 标签可标记事件触发。
"""
# ============================================================
# 开放世界 Director 提示词
# ============================================================
# 【开放世界 vs 线性剧本】
#   线性剧本模式（director_template.py）：GM 按照预定章节顺序推进剧情，
#     事件是预先写好的，Director 只是提示"本回合推进哪个事件"。
#
#   开放世界模式（本文件）：没有固定剧本，世界里有很多候选事件，
#     PC 可以自由探索。Director 根据 PC 当前位置、候选事件的得分（优先级）、
#     势力紧张度等，动态决定"本回合应该让什么事情发生"。
#
# 【事件得分（score）】
#   每个候选事件有一个 score 值，计算公式是：
#     score = 重要性 × 距离系数 + 加成
#   score 越高 = 越应该本回合触发。Director 优先推高分事件。
#
# 【为什么要分两步（Director + GM）】
#   见 director_template.py 的注释。总结：Director 做规划，GM 做叙事，分工合作。
# ============================================================
from __future__ import annotations

from dzmm.models.client import Message

# Director 的系统角色设定：明确它做什么、不做什么
_SYSTEM = """你是开放世界 TRPG 的「剧情导演」（Director）。你不写场景描写，不演 NPC 台词。

你的职责：
1. 从候选事件中选择本回合要推动的事件（可以是 0 个）
2. 若有传闻事件，决定是否通过叙事投递（作为旅人传言）
3. 若有 NPC 主动联系提示，决定如何引入
4. 下发简洁剧情指令（plot_directive）

# 候选事件优先级
按 score 从高到低排列。score = 重要性 × 距离系数 + 加成。
score 越高 = 越应该本回合推动。

# 事件生命周期
每个开放世界事件经历两个阶段：
- **触发（triggered）**：事件在叙事中开始发生（战斗爆发、危机显现、NPC 出场等）
- **完成（completed）**：事件的核心冲突/目标已解决，PC 取得了明确的结果

两个阶段对应两种标签，各自独立 emit：
1. `<event_trigger event_id="N"/>` — 事件刚刚"发生了"（已触发但尚未结束）
2. `<event_complete event_id="N"/>` — 事件已彻底解决/完成（才 emit 此标签）

**不要把两个标签放在同一回合**（除非事件在一回合内从触发到结束）。
已触发/已完成的事件不重复 emit 同一标签。
候选事件会明确标出状态：`pending` 只能 emit `event_trigger`；`triggered`
绝不能再次 emit `event_trigger`，只有最近真实回合已给出明确解决结果时才 emit
`event_complete`，否则不 emit 状态标签。

完成判断针对当前这个原子事件，而不是整条主线：若事件摘要中的局部事实、
问题或冲突已被最近真实回合明确验证/解决，并留下可继续追查的结果或线索，
就应 complete；不要仅因更大的谜团尚未解决而让同一事件永久停在 triggered。
若最近真实回合仍只有尝试、猜测或失败结果，则不要 complete。

# 你产出（严格按顺序）

## 步骤一：事件状态声明（可选）
状态声明与“本回合主推哪个事件”彼此独立。必须先逐个审核候选列表中所有
`triggered` 事件：对照最近真实回合和该事件的完成判据；已经满足就 emit
`event_complete`，即使玩家已离开原地点、或步骤二准备主推另一个事件也不能漏掉。

若上回合叙事/PC 行动已让某个候选事件"发生了"（触发），emit：
<event_trigger event_id="N"/>

若某个已触发的事件在最近真实回合已满足完成判据，emit：
<event_complete event_id="N"/>

不确定则不 emit。

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
      candidate_events: list[{id, name, score, importance, summary_md}]
      rumor_events: list[{name, importance, summary_md}]
      proactive_npc: str | None  — NPC name that wants to contact PC
      campaign_phase: str | None
      faction_tensions: list[{name, tension}]
    """
    # 把 snapshot 字典里的各种数据拼成一段用户消息文本，
    # 交给 Director LLM 阅读后决定本回合推哪个事件。

    lines = [
        f"当前地点：{snapshot.get('current_location', '未知')}",
        f"PC 概要：{snapshot.get('pc_summary', '')}",
        f"玩家本回合行动：{snapshot.get('current_action', '')}",
    ]

    recent_scene_facts = snapshot.get("recent_scene_facts")
    if recent_scene_facts:
        lines.append(f"最近真实回合：\n{recent_scene_facts}")

    # 旅伴列表：如果有，拼成"旅伴：A, B"格式
    companions = snapshot.get("companions") or []
    if companions:
        lines.append(f"旅伴：{', '.join(companions)}")

    # 候选事件列表：按 score 排序（调用方已排好序），格式化每个事件
    events = snapshot.get("candidate_events") or []
    if events:
        lines.append("\n候选事件（按优先级排序）：")
        for ev in events:
            completion = ev.get("completion_criteria_md") or "（未显式设置）"
            lines.append(
                f"  - [id={ev['id']}/{ev['importance']}★/"
                f"{ev.get('status', 'pending')}] "
                f"{ev['name']}（score={ev['score']:.1f}）：{ev['summary_md']}；"
                f"完成判据：{completion}"
            )
        lines.append(
            "状态规则：pending 事件只可 trigger；triggered 事件禁止再次 trigger，"
            "若最近真实回合已得到明确解决结果则 complete，否则不输出事件标签。"
        )
    else:
        lines.append("\n候选事件：无（自由探索回合）")  # 没有候选事件时提示"自由探索"

    # 传闻事件：PC 还没遇到、可以作为"旅人传言"间接投递的事件
    rumors = snapshot.get("rumor_events") or []
    if rumors:
        lines.append("\n可投递传闻：")
        for r in rumors:
            lines.append(f"  - {r['name']}（重要性={r['importance']}）：{r['summary_md']}")

    # 是否有 NPC 主动想联系 PC（如 NPC 的 contact_favor_threshold 被满足）
    proactive = snapshot.get("proactive_npc")
    if proactive:
        lines.append(f"\n建议本回合引入 NPC 主动联系：{proactive}")

    # 主线进度（开放世界也可以有可选的主线任务链）
    phase = snapshot.get("campaign_phase")
    if phase:
        lines.append(f"\n主线进度：{phase}")

    # 势力紧张度：影响 Director 判断哪个派系事件更紧迫
    tensions = snapshot.get("faction_tensions") or []
    if tensions:
        lines.append("\n势力紧张度：" + "；".join(f"{t['name']}={t['tension']}" for t in tensions))

    user_content = "\n".join(lines)

    # 消息列表：[system 角色设定] + [历史对话（上几回合 Director 给的指令）] + [本回合状态]
    # 包含历史是为了让 Director 的指令前后连贯，不会每回合都推同一件事
    msgs: list[Message] = [Message(role="system", content=_SYSTEM)]
    msgs.extend(history)   # 历史 Director 对话（让它知道上回合推了什么）
    msgs.append(Message(role="user", content=user_content))
    return msgs
