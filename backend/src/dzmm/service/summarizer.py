from datetime import datetime, UTC

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.db.models import (
    Message as MessageRow,
    Session as GameSession,
    StorySummary,
)
from dzmm.models.client import GenerationParams, ModelClient
from dzmm.prompts.summarizer_template import build_summarizer_messages


SUMMARIZE_AFTER_TURNS = 10
SUMMARY_MAX_TOKENS = 1000


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

    if summary_row is None:
        summary_row = StorySummary(session_id=session_id)
        session.add(summary_row)

    summary_row.summary_text = summary_text.strip()
    summary_row.last_summarized_msg_id = new_msgs[-1].id
    summary_row.summary_tokens = usage.output_tokens
    summary_row.updated_at = datetime.now(UTC).replace(tzinfo=None)

    return True
