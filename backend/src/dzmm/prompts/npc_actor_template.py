"""Per-NPC stateful actor prompt.

Each major NPC has its own agent_stream. This prompt is character-locked
(archetype/gender/purpose pinned in system) and history-aware (past
turns from this NPC's stream injected as message pairs). Output: <say>
+ optional <npc_update> for emotion delta.
"""
# ============================================================
# NPC Actor 提示词（每个重要 NPC 独立的 Agent）
# ============================================================
# 【为什么每个 NPC 要有自己的 Agent？】
#   传统 GM 模式：GM 一个人扮演所有 NPC。但这会导致：
#   - NPC 的性格/口吻"漂移"（忘记了 NPC A 说过什么，导致前后矛盾）
#   - 两个 NPC 同时在场时，GM 要记住两套性格，容易混淆
#
#   NPC Actor 模式：每个主要 NPC 有自己独立的 Agent（即独立的对话历史）。
#   - 每个 NPC 的 system prompt 写死了他/她的性格、动机、当前情绪
#   - 这个 NPC 过去说过的话都在自己的历史消息里（不会和别人混）
#   - 本回合输入是 Scene 写好的叙事 + Scene 给的 cue intent（方向提示）
#   - 输出：这个 NPC 说的话（<say>）和情绪变化（<npc_update>）
#
# 【有状态（Stateful）是什么意思？】
#   普通 LLM 调用是无状态的（每次调用互不相关）。
#   "有状态"意味着：上一回合 NPC 说了"我不会告诉你"，
#   这一回合的历史消息里包含那段历史，NPC 不会假装没说过。
#   实现方式：每个 NPC 维护自己的 history（list[Message]），
#   每次调用都把历史消息传进去，形成连续的对话上下文。
#
# 【cue_intent（本回合方向）】
#   Scene 在生成叙事后，会发出 <npc_cue speaker="XXX" intent="具体做什么"/>。
#   NPC Actor 读到这个 intent，优先按这个方向反应（再结合自己的性格微调）。
#   这样 Scene 和 NPC Actor 协作，而不是各自为政。
# ============================================================
from __future__ import annotations

import json as _json

from dzmm.models.client import Message


# NPC Actor 系统提示词模板
# 包含多个 {占位符}，在 build_npc_actor_messages() 里用实际 NPC 数据替换
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

**铁律（重复强调）**：
- 最多 1 条 `<say>`，最多 1 条 `<npc_update>`，最多 1 条 `<noop>`。不要重复输出同类标签。
- `<npc_update>` 里数字**不加正号**（写 `5` 不写 `+5`，写 `-10` 即可），避免 JSON 解析失败。
"""


def build_npc_actor_messages(
    *,
    npc,  # ORM 对象，有 .name .gender .archetype .description .state .purpose .emotion_json 等属性
    history: list[Message],           # 这个 NPC 的历史对话（有状态的核心）
    plot_directive: str,              # Director 的本回合指令（NPC 只作参考）
    scene_narrative: str,             # Scene 写好的本回合叙事（NPC 读了才知道发生了什么）
    user_action: str,                 # 玩家的本回合输入
    scene_context: str = "",          # 地点 + 在场 NPC + 世界时间（可选）
    recent_dialogue: str = "",        # 最近 4 回合压缩的对话摘要（温故知新）
    relationship_summary: str = "",   # v0.10.6: 当前 PC↔NPC 关系描述
    cue_intent: str = "",             # v0.10.7: Scene 给本 NPC 的本回合方向提示
) -> list[Message]:
    # 从 NPC 的 emotion_json（JSON 字符串）解析情绪字典
    # 例如 '{"anger": 30, "love": 70}' → 解析成 {"anger": 30, "love": 70}
    try:
        emotions_dict = _json.loads(npc.emotion_json or "{}")
        emotions_str = (
            ", ".join(f"{k}:{v}" for k, v in emotions_dict.items())
            if emotions_dict else "无"
        )
    except (ValueError, TypeError):
        # json.loads 可能抛出 ValueError（无效 JSON）或 TypeError（非字符串输入）
        # 都兜底为"无"，不让异常崩溃整个请求
        emotions_str = "无"

    # 把英文 gender 值转成中文（供提示词使用）
    # .get() 第二参数是默认值，找不到时返回"未知"
    gender_cn = {"male": "男", "female": "女"}.get(
        (getattr(npc, "gender", "") or "").lower(), "未知"
    )

    # 关系摘要：如果没有提供，用"初次接触"兜底（让 NPC 不要表现得太熟）
    rel_summary = (relationship_summary or "").strip() or "（无明确历史 — 当作初次接触）"

    # 用 NPC 的实际数据替换系统提示词里的占位符
    system = _NPC_ACTOR_SYSTEM.format(
        name=(npc.name or "未知").strip(),
        gender=gender_cn,
        archetype=(npc.archetype or "普通人").strip() or "普通人",
        description=(npc.description or "（无简介）").strip()[:300],  # 简介最多 300 字
        purpose=(npc.purpose or "（未知）").strip()[:200],             # 动机最多 200 字
        state=(npc.state or "未知").strip(),
        emotions=emotions_str,
        relationship_summary=rel_summary,
    )

    # 构建用户消息：把本回合所有相关信息拼到一起
    parts = [
        f"# 本回合剧情指令（Director，仅参考）\n{plot_directive}",
    ]
    # 如果 Scene 给了这个 NPC 的具体方向提示，优先级很高，单独强调
    if cue_intent.strip():
        parts.append(
            f"# 🎯 GM 给你的本回合方向（高优先级）\n{cue_intent}\n\n"
            "（Scene 写完场景之后明确点了你这一刻该做什么。优先按这个方向反应，"
            "再结合关系/情绪微调。）"
        )
    if scene_context.strip():
        parts.append(f"# 当前场景\n{scene_context}")
    if recent_dialogue.strip():
        parts.append(f"# 近期对话（最近几回合，给你温故知新）\n{recent_dialogue}")
    parts.append(f"# 本回合 GM 已写好的场景\n{scene_narrative or '（无）'}")
    parts.append(f"# PC 玩家本回合输入\n{user_action}")
    # 用两个换行分隔各段落，使其在提示词里清晰可读
    turn_input = "\n\n".join(parts)

    # 组装消息列表：[system NPC 设定] + [这个 NPC 的历史对话] + [本回合输入]
    # history 是这个 NPC 过去所有回合的 say/npc_update 记录，
    # 保证 NPC 的行为与过去一致（有状态的核心机制）
    msgs: list[Message] = [Message(role="system", content=system)]
    msgs.extend(history)   # 这个 NPC 自己的历史记忆
    msgs.append(Message(role="user", content=turn_input))
    return msgs
