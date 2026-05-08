"""Stateful agent stream layer — CRUD + history loading + compression
+ rollback. Used by Director and per-NPC agents.

Scene agent does NOT use this module; it reuses the existing `messages`
table because its output is exactly what players see (no separate
storage). Only Director and NPCs have agent-internal histories.
"""
from __future__ import annotations

import logging

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.db.models import AgentMessage, AgentStream
from dzmm.models.client import GenerationParams, Message, ModelClient

log = logging.getLogger(__name__)

_COMPRESS_PARAMS = GenerationParams(temperature=0.3, max_tokens=400)


async def get_or_create_stream(
    s: AsyncSession,
    session_id: int,
    kind: str,
    ref: str = "",
) -> AgentStream:
    """Return the (session_id, kind, ref) stream, creating it on first call.
    Caller is responsible for the surrounding session.commit()."""
    existing = (await s.execute(
        select(AgentStream).where(
            AgentStream.session_id == session_id,
            AgentStream.kind == kind,
            AgentStream.ref == ref,
        )
    )).scalar_one_or_none()
    if existing is not None:
        return existing
    row = AgentStream(session_id=session_id, kind=kind, ref=ref)
    s.add(row)
    await s.flush()
    return row


async def append_message(
    s: AsyncSession,
    stream_id: int,
    turn: int,
    role: str,
    content: str,
    is_summary: bool = False,
    tokens_in: int = 0,
    tokens_out: int = 0,
) -> None:
    s.add(AgentMessage(
        stream_id=stream_id,
        turn=turn,
        role=role,
        content=content,
        is_summary=is_summary,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
    ))


async def load_history(
    s: AsyncSession,
    stream_id: int,
    max_messages: int = 20,
) -> list[Message]:
    """Build the agent's per-turn prompt history.

    Order is: every is_summary=True row first (at head, oldest summary first),
    then the latest (max_messages - n_summary) non-summary rows in chronological
    order. Truncating from the middle preserves the long-term memory while
    bounding token cost.
    """
    summaries = (await s.execute(
        select(AgentMessage)
        .where(
            AgentMessage.stream_id == stream_id,
            AgentMessage.is_summary == True,  # noqa: E712
        )
        .order_by(AgentMessage.id.asc())
    )).scalars().all()

    n_summary = len(summaries)
    keep = max(0, max_messages - n_summary)

    recents = []
    if keep > 0:
        recents = (await s.execute(
            select(AgentMessage)
            .where(
                AgentMessage.stream_id == stream_id,
                AgentMessage.is_summary == False,  # noqa: E712
            )
            .order_by(AgentMessage.id.desc())
            .limit(keep)
        )).scalars().all()
        recents = list(reversed(recents))

    rows = list(summaries) + recents
    return [Message(role=r.role, content=r.content) for r in rows]


async def rollback_to_turn(
    s: AsyncSession,
    session_id: int,
    max_keep_turn: int,
) -> None:
    """Drop every AgentMessage with turn > max_keep_turn for any stream
    belonging to this session. Used by delete_last_turn to keep agent
    histories in sync with the player-facing rollback.

    Summary rows always live at turn=0 (or whatever turn they were
    written at — they're the *only* surviving rows when their range was
    compressed away), so this query naturally preserves them as long as
    they were written before the cutoff. Streams' last_run_turn is
    rewound to <= max_keep_turn for the same reason.
    """
    stream_ids = (await s.execute(
        select(AgentStream.id).where(AgentStream.session_id == session_id)
    )).scalars().all()
    if not stream_ids:
        return
    await s.execute(
        delete(AgentMessage).where(
            AgentMessage.stream_id.in_(stream_ids),
            AgentMessage.turn > max_keep_turn,
        )
    )
    streams = (await s.execute(
        select(AgentStream).where(AgentStream.id.in_(stream_ids))
    )).scalars().all()
    for st in streams:
        if st.last_run_turn > max_keep_turn:
            st.last_run_turn = max_keep_turn


async def compress_if_needed(
    s: AsyncSession,
    stream_id: int,
    summarizer_client: ModelClient,
    threshold: int = 30,
    keep_recent: int = 10,
) -> None:
    """If the stream has > threshold non-summary messages, summarize the
    oldest (count - keep_recent) into a single is_summary row and delete
    the originals.

    Best-effort: any LLM error swallows and leaves the stream as-is.
    Caller commits.
    """
    rows = (await s.execute(
        select(AgentMessage)
        .where(
            AgentMessage.stream_id == stream_id,
            AgentMessage.is_summary == False,  # noqa: E712
        )
        .order_by(AgentMessage.id.asc())
    )).scalars().all()
    if len(rows) <= threshold:
        return

    cut = len(rows) - keep_recent
    to_compress = rows[:cut]
    transcript = "\n".join(
        f"[{r.role}] {r.content}" for r in to_compress
    )

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
        log.warning("agent_streams: compress failed for stream %d: %s",
                    stream_id, exc)
        return

    summary_text = (text or "").strip()
    if not summary_text:
        return

    # Append the summary first, then drop the originals.
    s.add(AgentMessage(
        stream_id=stream_id,
        turn=to_compress[-1].turn,
        role="system",
        content=summary_text,
        is_summary=True,
    ))
    await s.execute(
        delete(AgentMessage).where(
            AgentMessage.id.in_([r.id for r in to_compress])
        )
    )
