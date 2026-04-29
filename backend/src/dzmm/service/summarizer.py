import re
from datetime import datetime, UTC

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.db.models import (
    Message as MessageRow,
    Session as GameSession,
    StorySummary,
    Timeline,
)
from dzmm.models.client import GenerationParams, ModelClient
from dzmm.prompts.summarizer_template import (
    build_compression_messages,
    build_summarizer_messages,
)


SUMMARIZE_AFTER_TURNS = 10
SUMMARY_MAX_TOKENS = 1000
COMPRESSION_TRIGGER_CHARS = 3000  # ~1500 tokens for Chinese
COMPRESSED_TARGET_TOKENS = 600


_EVENT_RE = re.compile(r'<event\s+importance="(\d+)">([\s\S]*?)</event>', re.IGNORECASE)


async def _compress_summary(client: ModelClient, long_summary: str) -> tuple[str, list[dict]]:
    """Returns (new_summary, events). events is a list of {importance, text}."""
    msgs = build_compression_messages(long_summary)
    text, _usage = await client.complete(
        msgs, GenerationParams(temperature=0.2, max_tokens=COMPRESSED_TARGET_TOKENS + 200)
    )

    # Pull out events first
    events: list[dict] = []
    for m in _EVENT_RE.finditer(text):
        try:
            imp = int(m.group(1))
        except ValueError:
            continue
        events.append({"importance": max(1, min(3, imp)), "text": m.group(2).strip()})

    # New summary is everything before the first <event tag, OR the entire text if no events
    cut = text.find("<event")
    new_summary = text[:cut].strip() if cut >= 0 else text.strip()
    return new_summary, events


async def maybe_summarize(
    session: AsyncSession,
    session_id: int,
    client: ModelClient,
) -> bool:
    """Run a summarization pass if conditions are met. Returns True if executed."""
    sess = await session.get(GameSession, session_id)
    if sess is None or sess.turn_count < SUMMARIZE_AFTER_TURNS:
        return False

    summary_row = (
        await session.execute(
            select(StorySummary).where(StorySummary.session_id == session_id)
        )
    ).scalar_one_or_none()
    high_water = summary_row.last_summarized_msg_id if summary_row else 0

    new_msgs = (
        await session.execute(
            select(MessageRow)
            .where(MessageRow.session_id == session_id)
            .where(MessageRow.id > high_water)
            .order_by(MessageRow.id)
        )
    ).scalars().all()
    if len(new_msgs) < SUMMARIZE_AFTER_TURNS * 2:
        return False

    new_text = "\n\n".join(
        f"[{m.role}] {m.content}" for m in new_msgs
    )
    prev = summary_row.summary_text if summary_row else ""

    msgs = build_summarizer_messages(
        previous_summary=prev,
        new_messages_text=new_text,
        key_facts="",
    )

    summary_text, usage = await client.complete(
        msgs, GenerationParams(temperature=0.3, max_tokens=SUMMARY_MAX_TOKENS)
    )

    events_to_persist: list[dict] = []
    if len(summary_text) > COMPRESSION_TRIGGER_CHARS:
        summary_text, events_to_persist = await _compress_summary(client, summary_text)

    if summary_row is None:
        summary_row = StorySummary(session_id=session_id)
        session.add(summary_row)

    summary_row.summary_text = summary_text.strip()
    summary_row.last_summarized_msg_id = new_msgs[-1].id
    summary_row.summary_tokens = usage.output_tokens
    summary_row.updated_at = datetime.now(UTC).replace(tzinfo=None)

    for ev in events_to_persist:
        if ev["importance"] >= 2 and ev["text"]:
            session.add(Timeline(
                session_id=session_id,
                turn=sess.turn_count,
                event_text=ev["text"],
                importance=ev["importance"],
            ))

    return True
