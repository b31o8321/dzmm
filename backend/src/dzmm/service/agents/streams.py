# ============================================================
# streams.py — Agent 私有对话历史的存储层
#
# 【为什么需要这个模块？】
# 系统里有多个 LLM agent：Director（导演）、NPC actor（NPC 演员）等。
# 每个 agent 都需要「记忆」自己和 GM/玩家之前的交流，才能保持连贯。
# 这个模块提供了 agent 专属的历史存储（不和玩家可见的聊天记录混用）：
#   - get_or_create_stream：获取或创建一条「对话历史流」
#   - append_message：向流里追加一条消息
#   - load_history：读取历史，构建发送给 LLM 的 messages 列表
#   - rollback_to_turn：随着游戏回滚，同步删除 agent 历史
#   - compress_if_needed：当历史太长时，用 LLM 压缩成摘要
#
# 【Scene agent 为什么不用这个模块？】
# Scene agent 的输出就是玩家看到的叙事文本，已经存在 messages 表里了。
# 只有 Director 和 NPC actor 有「内部私有对话」，需要单独存储。
# ============================================================
"""Stateful agent stream layer — CRUD + history loading + compression
+ rollback. Used by Director and per-NPC agents.

Scene agent does NOT use this module; it reuses the existing `messages`
table because its output is exactly what players see (no separate
storage). Only Director and NPCs have agent-internal histories.
"""
from __future__ import annotations

import logging

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession  # 异步数据库会话，不阻塞事件循环

from dzmm.db.models import AgentMessage, AgentStream
from dzmm.models.client import GenerationParams, Message, ModelClient

log = logging.getLogger(__name__)

# 压缩摘要时的 LLM 参数：低温度让摘要更客观，max_tokens 限制长度
_COMPRESS_PARAMS = GenerationParams(temperature=0.3, max_tokens=400)


# ────────────────────────────────────────────────────────────
# 获取或创建 AgentStream（对话历史流）
# ────────────────────────────────────────────────────────────

async def get_or_create_stream(
    s: AsyncSession,
    session_id: int,
    kind: str,   # 流的类型，如 "gm_director"、"npc"
    ref: str = "",  # 附加标识，NPC 流用 NPC 名字，Director 流用空字符串
) -> AgentStream:
    # AgentStream 是一条「会话内的 agent 专属对话频道」。
    # 每个 Director、每个 NPC 都有自己的频道，互不干扰。
    # 用 (session_id, kind, ref) 三元组唯一标识一条流。
    # 第一次调用时自动创建（幂等操作）。
    """Return the (session_id, kind, ref) stream, creating it on first call.
    Caller is responsible for the surrounding session.commit()."""
    existing = (await s.execute(
        select(AgentStream).where(
            AgentStream.session_id == session_id,
            AgentStream.kind == kind,
            AgentStream.ref == ref,
        )
    )).scalar_one_or_none()  # 查询一条记录，不存在返回 None
    if existing is not None:
        return existing  # 已存在，直接返回
    # 不存在，创建新的流
    row = AgentStream(session_id=session_id, kind=kind, ref=ref)
    s.add(row)
    await s.flush()  # flush 让数据库分配 ID，但不提交事务（commit 由调用者负责）
    return row


# ────────────────────────────────────────────────────────────
# 向流里追加一条消息
# ────────────────────────────────────────────────────────────

async def append_message(
    s: AsyncSession,
    stream_id: int,
    turn: int,
    role: str,        # "user"（agent 收到的输入）或 "assistant"（agent 的输出）
    content: str,
    is_summary: bool = False,  # True 表示这是压缩摘要，不是原始消息
    tokens_in: int = 0,        # 输入 token 数（用于统计）
    tokens_out: int = 0,       # 输出 token 数（用于统计）
) -> None:
    # 每回合 agent 运行后，把「输入（user）」和「输出（assistant）」都存起来，
    # 下次调用时通过 load_history 读回，让 agent 记住上次发生了什么
    s.add(AgentMessage(
        stream_id=stream_id,
        turn=turn,
        role=role,
        content=content,
        is_summary=is_summary,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
    ))
    # 注意：这里没有 commit，由调用者决定何时提交


# ────────────────────────────────────────────────────────────
# 加载 agent 的历史消息，构建 LLM 的 messages 列表
# ────────────────────────────────────────────────────────────

async def load_history(
    s: AsyncSession,
    stream_id: int,
    max_messages: int = 20,  # 最多加载多少条消息（防止 context 超长）
) -> list[Message]:
    # 【加载策略：摘要在前，近期消息在后】
    # LLM 的 context 长度有限，不能无限堆历史。
    # 解决方案：把老的历史压缩成摘要（is_summary=True），
    # 放在消息列表最前面，然后接上最近 N 条原始消息。
    # 这样 agent 既能「记得」遥远的过去（通过摘要），
    # 又能「清楚地看到」最近发生的事（通过原始消息）。
    """Build the agent's per-turn prompt history.

    Order is: every is_summary=True row first (at head, oldest summary first),
    then the latest (max_messages - n_summary) non-summary rows in chronological
    order. Truncating from the middle preserves the long-term memory while
    bounding token cost.
    """
    # 先加载所有摘要消息（按 ID 升序 = 按时间正序）
    summaries = (await s.execute(
        select(AgentMessage)
        .where(
            AgentMessage.stream_id == stream_id,
            AgentMessage.is_summary == True,  # noqa: E712
        )
        .order_by(AgentMessage.id.asc())
    )).scalars().all()

    n_summary = len(summaries)
    # 剩余配额给最近的原始消息
    keep = max(0, max_messages - n_summary)
    # Agent 原始历史按 user/assistant 成对写入。有摘要时剩余额度常为奇数，
    # 从尾部截取奇数条会以 assistant 开头，严格的聊天模板会拒绝该序列。
    if summaries and keep % 2:
        keep -= 1

    recents = []
    if keep > 0:
        # 取最近 keep 条原始消息（先倒序查，再翻转为正序）
        recents = (await s.execute(
            select(AgentMessage)
            .where(
                AgentMessage.stream_id == stream_id,
                AgentMessage.is_summary == False,  # noqa: E712
            )
            .order_by(AgentMessage.id.desc())  # 倒序取最近的
            .limit(keep)
        )).scalars().all()
        recents = list(reversed(recents))  # 翻转回正序（时间从早到晚）

    # 摘要在前，原始消息在后，拼成完整历史
    rows = list(summaries) + recents
    # 转换为 Message 对象（LLM 客户端接受的格式）
    return [Message(role=r.role, content=r.content) for r in rows]


# ────────────────────────────────────────────────────────────
# 回滚 agent 历史（配合游戏的「撤销上一回合」功能）
# ────────────────────────────────────────────────────────────

async def rollback_to_turn(
    s: AsyncSession,
    session_id: int,
    max_keep_turn: int,  # 保留到这个回合，之后的消息全部删除
) -> None:
    # 当玩家使用「撤销上一回合」功能时，
    # 不只要删玩家看到的消息，还要删掉 agent 内部历史里对应的记录。
    # 否则 Director/NPC 会「记得」一个已经被撤销的回合，导致记忆和叙事不一致。
    """Drop every AgentMessage with turn > max_keep_turn for any stream
    belonging to this session. Used by delete_last_turn to keep agent
    histories in sync with the player-facing rollback.

    Summary rows always live at turn=0 (or whatever turn they were
    written at — they're the *only* surviving rows when their range was
    compressed away), so this query naturally preserves them as long as
    they were written before the cutoff. Streams' last_run_turn is
    rewound to <= max_keep_turn for the same reason.
    """
    # 先找出这个游戏会话的所有 stream ID
    stream_ids = (await s.execute(
        select(AgentStream.id).where(AgentStream.session_id == session_id)
    )).scalars().all()
    if not stream_ids:
        return  # 没有 agent 历史，直接退出

    # 批量删除 turn > max_keep_turn 的所有消息（所有流）
    await s.execute(
        delete(AgentMessage).where(
            AgentMessage.stream_id.in_(stream_ids),  # IN 子句批量匹配
            AgentMessage.turn > max_keep_turn,
        )
    )
    # 同步更新每个流的 last_run_turn，防止 Director 误以为自己已经在未来的回合跑过了
    streams = (await s.execute(
        select(AgentStream).where(AgentStream.id.in_(stream_ids))
    )).scalars().all()
    for st in streams:
        if st.last_run_turn > max_keep_turn:
            st.last_run_turn = max_keep_turn  # 回退到保留的最大回合号


# ────────────────────────────────────────────────────────────
# 按需压缩历史（防止 agent 历史无限增长导致 context 超限）
# ────────────────────────────────────────────────────────────

async def compress_if_needed(
    s: AsyncSession,
    stream_id: int,
    summarizer_client: ModelClient,  # 用于生成摘要的 LLM 客户端
    threshold: int = 30,   # 超过多少条原始消息时触发压缩
    keep_recent: int = 10, # 保留最近多少条原始消息（不压缩）
) -> None:
    # 【为什么需要压缩？】
    # Agent 的历史随游戏进行不断增长，如果不压缩，
    # 发给 LLM 的 prompt 会越来越长，直到超出 context 窗口限制。
    # 解决方案：把最老的（count - keep_recent）条消息
    # 压缩成一条摘要（is_summary=True），删掉原始消息。
    # 这样历史总数量保持可控，同时关键信息不丢失。
    """If the stream has > threshold non-summary messages, summarize the
    oldest (count - keep_recent) into a single is_summary row and delete
    the originals.

    Best-effort: any LLM error swallows and leaves the stream as-is.
    Caller commits.
    """
    # 查询所有非摘要消息，按 ID 正序（从最早到最新）
    rows = (await s.execute(
        select(AgentMessage)
        .where(
            AgentMessage.stream_id == stream_id,
            AgentMessage.is_summary == False,  # noqa: E712
        )
        .order_by(AgentMessage.id.asc())
    )).scalars().all()
    if len(rows) <= threshold:
        return  # 还没超阈值，不需要压缩

    # 计算要压缩的消息数量（保留最近 keep_recent 条不压缩）
    cut = len(rows) - keep_recent
    to_compress = rows[:cut]  # 要压缩的旧消息
    prior_summaries = (await s.execute(
        select(AgentMessage)
        .where(
            AgentMessage.stream_id == stream_id,
            AgentMessage.is_summary == True,  # noqa: E712
        )
        .order_by(AgentMessage.id.asc())
    )).scalars().all()
    # 把要压缩的消息拼成对话文本
    transcript = "\n".join(
        f"[{r.role}] {r.content}" for r in [*prior_summaries, *to_compress]
    )

    # 构建压缩 prompt，让 LLM 生成摘要
    prompt = (
        "你是 TRPG 长期记忆压缩助手。把下面这一段 agent 私下对话历史"
        "浓缩成不超过 200 字的中文摘要，保留：关键剧情节点、情绪转折、"
        "未解的承诺/疑问。**保持中性叙述视角**，不要带新评价。\n\n"
        f"{transcript}"
    )
    try:
        text, _ = await summarizer_client.complete(
            [Message(role="user", content=prompt)], _COMPRESS_PARAMS,
        )
    except Exception as exc:  # noqa: BLE001
        # 压缩失败不影响主流程，只是历史不会被清理
        log.warning("agent_streams: compress failed for stream %d: %s",
                    stream_id, exc)
        return

    summary_text = (text or "").strip()
    if not summary_text:
        return  # LLM 返回空内容，放弃压缩

    # 先写入摘要消息（is_summary=True），再删除原始消息
    # 顺序很重要：先写后删，防止数据丢失
    s.add(AgentMessage(
        stream_id=stream_id,
        turn=to_compress[-1].turn,  # 摘要的 turn 设为被压缩范围的最后一个 turn
        role="system",   # 摘要用 system role，区别于 user/assistant
        content=summary_text,
        is_summary=True,  # 标记为摘要，load_history 会把它放在消息列表最前面
    ))
    # 旧摘要也并入新摘要，确保每条流始终至多一个长期摘要，避免百回合后
    # load_history 虽限制近期消息却仍把所有历史摘要带回 prompt。
    delete_ids = [r.id for r in prior_summaries] + [r.id for r in to_compress]
    await s.execute(
        delete(AgentMessage).where(
            AgentMessage.id.in_(delete_ids)
        )
    )
