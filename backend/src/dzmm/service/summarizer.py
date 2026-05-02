import re
from datetime import datetime, UTC

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.db.models import (
    Message as MessageRow,
    Session as GameSession,
    StorySummary,
)
from dzmm.models.client import GenerationParams, ModelClient
from dzmm.prompts.summarizer_template import (
    build_compression_messages,
    build_summarizer_messages,
)


SUMMARIZE_AFTER_TURNS = 10
# v0.2.1 — long-context fix. Trigger every 10 turns of new material (the old
# constant happened to be 10 already, but keep the alias spelled out so the
# intent is explicit and tests can pin to either name).
SUMMARIZE_TRIGGER_TURNS = 10
# Number of recent turns to leave un-summarized so the GM keeps verbatim
# context for the immediate scene. (Implementation note: actual recency
# windowing happens in service.messages._load_recent_messages; this constant
# documents the intended overlap so future maintainers can tune both knobs in
# concert.)
SUMMARIZE_KEEP_RECENT = 6
SUMMARY_MAX_TOKENS = 1500      # increased for key-facts section
COMPRESSION_TRIGGER_CHARS = 4000  # allow larger before compressing
COMPRESSED_TARGET_TOKENS = 800


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
    if sess is None or sess.turn_count < SUMMARIZE_TRIGGER_TURNS:
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
    # v0.2.1 — trigger every SUMMARIZE_TRIGGER_TURNS turns of new material
    # (each turn is one user + one assistant message → 2 rows). Previously the
    # threshold was 20 messages which meant in practice nothing got compressed
    # until turn 20+; long-context play tests at turn 30+ saw replies degrade.
    if len(new_msgs) < SUMMARIZE_TRIGGER_TURNS * 2:
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

    return True
