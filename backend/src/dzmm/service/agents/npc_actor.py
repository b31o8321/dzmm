# ============================================================
# npc_actor.py — NPC 演员 Agent
#
# 【NPC actor 是什么？】
# NPC actor 是一个针对单个 NPC 的 LLM agent。
# 每回合 Scene（场景 agent）生成叙事文本后，
# 每个「在场」的 NPC 都会有自己的 actor 被调用，
# 独立决定这个 NPC 本回合说什么、情绪/好感度如何变化。
#
# 【NPC actor 和 GM 的区别】
# GM（Scene agent）：以「全知旁白」视角描述整个场景，
#   包括环境、行动、多个 NPC 的集体反应。输出是玩家直接看到的叙事文字。
# NPC actor：以单个 NPC 的「第一人称」视角决策，
#   有自己的私有历史（记得之前和玩家的交流），
#   输出 <say> 标签（台词）和 <npc_update> 标签（内部状态更新如好感度变化）。
#   这些标签由 apply_tags 函数处理，更新数据库并插入到叙事里。
#
# 【为什么 NPC actor 有「私有历史流」？】
# 同一个 NPC 在多个回合里出现，需要记住「我之前和玩家说过什么、
# 好感度是怎么变化的」。这份记忆存在 AgentStream 里，
# 每次调用前 load_history 读出来放进 prompt。
# ============================================================
"""Per-NPC stateful actor — produces <say> + <npc_update> for one NPC."""
from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession  # 异步数据库会话

from dzmm.models.client import GenerationParams, ModelClient
from dzmm.parsing.events import ParseEvent, TagComplete
from dzmm.parsing.stream_parser import StreamingTagParser  # 流式 XML 解析器
from dzmm.prompts.npc_actor_template import build_npc_actor_messages  # 构建 NPC prompt
from dzmm.service.agents.streams import (
    append_message,      # 追加历史消息
    get_or_create_stream,  # 获取或创建历史流
    load_history,        # 加载历史消息
)

log = logging.getLogger(__name__)

STREAM_KIND_NPC = "npc"   # AgentStream 的种类标识，ref 是 NPC 名字
NPC_HISTORY_MAX = 8       # 1 条长期摘要 + 最近约 3-4 次互动

# NPC actor 的 LLM 参数：温度 0.75（比 Director 更有创意，让 NPC 更生动）
# max_tokens=300（NPC 一次不需要说太多，避免生成冗长台词）
_PARAMS = GenerationParams(temperature=0.75, max_tokens=300)
# 只保留这两种 XML 标签：说话和状态更新
_KEPT_TAGS = {"say", "npc_update"}


# ════════════════════════════════════════════════════════════
# 核心函数：运行单个 NPC 的 actor agent
# ════════════════════════════════════════════════════════════

async def run_npc_actor(
    s: AsyncSession,
    npc,                     # NPC 数据库对象（含 name、favor、emotion_json 等）
    session_id: int,
    plot_directive: str,     # Director 给出的本回合剧情指令
    scene_narrative: str,    # Scene agent 生成的本回合叙事文本（NPC 的「听觉/视觉」）
    user_action: str,        # 玩家本回合的行动输入
    client: ModelClient,     # 用于生成 NPC 反应的 LLM 客户端
    current_turn: int,
    scene_context: str = "",       # 当前地点 + 同台 NPC 列表（场景背景）
    recent_dialogue: str = "",     # 最近几轮的对话摘要（纯文本，无 XML 标签）
    relationship_summary: str = "", # 这个 NPC 和玩家的关系摘要（好感度 + 近期互动）
    cue_intent: str = "",          # Scene 在 <npc_cue> 里给出的意图提示（如「紧张询问」）
) -> tuple[list[ParseEvent], int, int]:
    # 【整体流程】
    # 1. 加载这个 NPC 的私有历史流（如果第一次出现就自动创建）
    # 2. 构建 prompt（历史 + 当前场景信息 + 玩家行动）
    # 3. 调用 LLM，获取 NPC 的反应文本
    # 4. 把输入/输出存入历史流（下次调用时能记住）
    # 5. 解析输出里的 <say> 和 <npc_update> 标签
    # 6. 去重（避免 LLM 重复生成相同标签），返回事件列表
    """Run one NPC's stateful agent. Returns (events, tokens_in, tokens_out).
    Events are parsed <say> + <npc_update> (or [] for noop/failure/empty).
    Persists this turn into the NPC's stream regardless — even noop is signal."""
    # 获取这个 NPC 的专属历史流（kind="npc", ref=NPC名字）
    stream = await get_or_create_stream(s, session_id, STREAM_KIND_NPC, npc.name)
    # 加载历史消息（最多 8 条，按「摘要在前、近期在后」策略）
    history = await load_history(s, stream.id, max_messages=NPC_HISTORY_MAX)

    # 构建发给 LLM 的消息列表（prompt 模板由 npc_actor_template.py 定义）
    msgs = build_npc_actor_messages(
        npc=npc, history=history,
        plot_directive=plot_directive,
        scene_narrative=scene_narrative,
        user_action=user_action,
        scene_context=scene_context,
        recent_dialogue=recent_dialogue,
        relationship_summary=relationship_summary,
        cue_intent=cue_intent,
    )

    # 调用 LLM，获取 NPC 反应
    try:
        output, usage = await client.complete(msgs, _PARAMS)
    except Exception as exc:  # noqa: BLE001
        log.warning("npc_actor(%s): LLM failed: %s", npc.name, exc)
        return [], 0, 0  # LLM 调用失败，返回空（NPC 本回合沉默）

    text = (output or "").strip()
    if not text:
        return [], 0, 0  # LLM 返回空内容，NPC 沉默

    # ── 构建存档快照 ──────────────────────────────────────────
    # 把本回合的输入信息浓缩成结构化文本，存入历史流。
    # 下次调用时，NPC 能通过历史流「回忆」上次发生了什么。
    snapshot_parts = []
    if cue_intent:
        snapshot_parts.append(f"# cue\n{cue_intent[:120]}")
    # 关系、地点、近期对话和 Director 指令在下一次调用时都会从实时状态重建；
    # 历史只保留本 NPC 当时真正看到的场景与玩家行动，避免过期快照重复膨胀。
    snapshot_parts.append(f"# scene\n{scene_narrative[:240]}")
    snapshot_parts.append(f"# user\n{user_action[:200]}")
    turn_input = "\n\n".join(snapshot_parts)

    tok_in = usage.input_tokens if usage else 0
    tok_out = usage.output_tokens if usage else 0
    # 存储本回合输入快照（role="user"）
    await append_message(s, stream.id, current_turn, "user", turn_input,
                         tokens_in=tok_in)
    # 存储 NPC 的反应输出（role="assistant"）
    await append_message(s, stream.id, current_turn, "assistant", text,
                         tokens_out=tok_out)
    stream.last_run_turn = current_turn  # 更新 NPC 上次发言的回合号

    # ── 处理 <noop> 标签 ──────────────────────────────────────
    # 如果 LLM 判断这个 NPC 本回合不需要发言，会输出 <noop/>
    # 虽然返回空事件列表，但历史已经存储了（「沉默」也是一种信号）
    if "<noop" in text:
        return [], tok_in, tok_out  # NPC 主动选择沉默，返回空事件

    # ── 解析 XML 标签 ─────────────────────────────────────────
    # StreamingTagParser 是流式 XML 解析器，可以处理不完整的 XML 输出
    # 它把文本流里的 <say>、<npc_update> 等标签提取成 TagComplete 事件
    parser = StreamingTagParser()
    raw_events: list[ParseEvent] = []
    # feed() 处理文本，返回可迭代的解析事件
    for ev in parser.feed(text):
        if isinstance(ev, TagComplete) and ev.name in _KEPT_TAGS:
            if ev.name == "say":
                # <say> 标签如果没有 speaker 属性，自动填入 NPC 名字
                ev.attrs.setdefault("speaker", npc.name)
            elif ev.name == "npc_update":
                # <npc_update> 标签必须有 name 属性，
                # 这样 apply_tags 才知道是哪个 NPC 的状态要更新
                ev.attrs["name"] = npc.name
            raw_events.append(ev)
    # finish() 处理缓冲区里可能残留的最后一个标签（解决边界问题）
    for ev in parser.finish():
        if isinstance(ev, TagComplete) and ev.name in _KEPT_TAGS:
            if ev.name == "say":
                ev.attrs.setdefault("speaker", npc.name)
            elif ev.name == "npc_update":
                ev.attrs["name"] = npc.name
            raw_events.append(ev)

    # ── 去重：每种标签只保留第一个 ───────────────────────────
    # LLM 有时会把同一类型的标签生成多次（如 3 个 <npc_update> 块），
    # 这会导致好感度被叠加应用多次、台词重复显示。
    # 策略：每种标签类型只保留第一次出现的（其余丢弃）。
    events: list[ParseEvent] = []
    seen_types: set[str] = set()
    for ev in raw_events:
        if isinstance(ev, TagComplete) and ev.name in _KEPT_TAGS:
            if ev.name not in seen_types:
                events.append(ev)          # 第一次出现，保留
                seen_types.add(ev.name)    # 标记这种类型已经见过
            # else: 重复出现，静默丢弃
        else:
            events.append(ev)  # 非 _KEPT_TAGS 的事件（如 NarrativeDelta）直接保留
    return events, tok_in, tok_out
