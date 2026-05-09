"""Per-NPC stateful actor prompt.

Each major NPC has its own agent_stream. This prompt is character-locked
(archetype/gender/purpose pinned in system) and history-aware (past
turns from this NPC's stream injected as message pairs). Output: <say>
+ optional <npc_update> for emotion delta.
"""
from __future__ import annotations

import json as _json

from dzmm.models.client import Message


_NPC_ACTOR_SYSTEM = """你正在扮演 TRPG 中的 NPC「{name}」。你**只**为这一个 NPC 说话，不是 GM、不是其他 NPC。

# 角色档案（永不破坏）
- 姓名：{name}
- 性别：{gender}
- 性格原型：{archetype}
- 人物简介：{description}
- 核心动机：{purpose}
- 当前状态：{state}
- 当前情绪：{emotions}

# 你和 PC 的关系（核心 — 反应必须基于当前关系，不是 archetype）
{relationship_summary}

**铁律**：你对 PC 的反应**首先**取决于这个关系状态，archetype 只是性格底色。如果你跟 PC 关系冷淡/敌对，即使你 archetype 是"热情商人"，对这个 PC 也不会热情；如果跟 PC 已建立信任，即使你 archetype 是"冷酷军人"，也会比对陌生人柔和。

# 你看到什么
- 你**自己**过去几回合说过 / 经历过的事（在你的对话历史里）
- Director 给的本回合剧情指令（plot_directive）
- Scene 刚刚写好的本回合 narrative + PC 行动
- PC 的玩家输入

# 你做什么
本回合，作为「{name}」，决定你的反应：
1. 说话 → emit `<say speaker="{name}" mood="...">「具体台词，1-3 句」</say>`
2. 关系/情绪变化 → emit `<npc_update name="{name}">{{"emotion": {{"anger": +5}}, "favor_delta": -10, "affinity": {{"信任": -2}} }}</npc_update>`

   **何时改 favor_delta**:
   - PC 救了你 / 帮你脱险 / 兑现承诺 → +5..+15
   - PC 信任你 / 透露秘密 / 寻求帮助 → +3..+8
   - PC 撒谎被识破 / 失约 / 漠视你的困境 → -5..-15
   - PC 直接伤害你 / 背叛 → -15..-30
   - 普通对话且无关系性事件 → 不需要 favor_delta（省略此键）
   - 单次 ±15 是合理上限；后端会 clamp。

   **affinity 多维**: 信任 / 羁绊 / 恋慕 / 敬畏 / 敌意 / 警戒 等中文 key，单维度 ±5 合理。
3. 都不需要（GM narrative 已经把你的反应写完了 / 你不在场）→ emit `<noop/>`

# 铁律
1. **完全符合你的 archetype** — 「{archetype}」的人会怎么说话？语气、用词、停顿都要像。不要漂移成"通用 NPC 腔"。
2. **PC 直接对你说话或问你 → 你必须给可被 PC 感知的反馈**（言语 / 动作 / 沉默 / 转身）。沉默要明确写出"她沉默不语"这样的反馈。
3. **不要写第三人称叙述**（"她笑了笑"是 GM 的活）。你只产出 say 和 npc_update。
4. **不要演别的 NPC** — 别人的 say 不是你写的。
5. **性别 / 称谓一致** — 按 {gender} 处理代词、亲属称谓、关系语言。
6. **看你自己的历史** — 如果你之前承诺过 / 撂过狠话 / 透露过秘密，本回合的反应要前后一致。

# 输出
只输出 XML 标签（say / npc_update / noop），不要任何说明文字。每条 say 限 1-3 句。
"""


def build_npc_actor_messages(
    *,
    npc,  # ORM with .name .gender .archetype .description .state .purpose .emotion_json
    history: list[Message],
    plot_directive: str,
    scene_narrative: str,
    user_action: str,
    scene_context: str = "",      # 地点 + 在场 NPC + 世界时间
    recent_dialogue: str = "",    # 最近 4 回合压缩对话
    relationship_summary: str = "",  # v0.10.6: 当前 PC↔NPC 关系
) -> list[Message]:
    try:
        emotions_dict = _json.loads(npc.emotion_json or "{}")
        emotions_str = (
            ", ".join(f"{k}:{v}" for k, v in emotions_dict.items())
            if emotions_dict else "无"
        )
    except (ValueError, TypeError):
        emotions_str = "无"

    gender_cn = {"male": "男", "female": "女"}.get(
        (getattr(npc, "gender", "") or "").lower(), "未知"
    )

    rel_summary = (relationship_summary or "").strip() or "（无明确历史 — 当作初次接触）"

    system = _NPC_ACTOR_SYSTEM.format(
        name=(npc.name or "未知").strip(),
        gender=gender_cn,
        archetype=(npc.archetype or "普通人").strip() or "普通人",
        description=(npc.description or "（无简介）").strip()[:300],
        purpose=(npc.purpose or "（未知）").strip()[:200],
        state=(npc.state or "未知").strip(),
        emotions=emotions_str,
        relationship_summary=rel_summary,
    )

    parts = [
        f"# 本回合剧情指令（Director，仅参考）\n{plot_directive}",
    ]
    if scene_context.strip():
        parts.append(f"# 当前场景\n{scene_context}")
    if recent_dialogue.strip():
        parts.append(f"# 近期对话（最近几回合，给你温故知新）\n{recent_dialogue}")
    parts.append(f"# 本回合 GM 已写好的场景\n{scene_narrative or '（无）'}")
    parts.append(f"# PC 玩家本回合输入\n{user_action}")
    turn_input = "\n\n".join(parts)

    msgs: list[Message] = [Message(role="system", content=system)]
    msgs.extend(history)
    msgs.append(Message(role="user", content=turn_input))
    return msgs
