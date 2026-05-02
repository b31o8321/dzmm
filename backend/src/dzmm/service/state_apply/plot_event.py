"""<plot_event> handler + dedup helpers."""

import logging
import re
from difflib import SequenceMatcher

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.db.models import PlotThread

log = logging.getLogger(__name__)

# Similarity threshold for plot_event dedup (new_quest / hook_introduced /
# major_event / location_entered).
# v0.13: lowered 0.7 -> 0.6 after a 9-turn play session where 5 near-identical
# rows still slipped through despite ratios ~0.79-0.95 between them. Root
# cause was a mix of un-normalized whitespace and incidentally-low ratio after
# the GM rephrased entire clauses. 0.6 still rejects clearly-distinct quests
# (e.g. "调查重力场异常" vs "寻找解药救小菱" → ratio 0.0) so false-collapse
# risk is low; the empirical user pair scores 0.79 → safely caught.
_PLOT_DEDUP_RATIO = 0.45

# Plot-event types that create a *new* thread row. Any tag whose type is in
# this set goes through dedup against existing active threads; types not
# listed (e.g. hook_resolved) take a separate path. We deliberately include
# major_event and location_entered: in practice the GM also restates these
# across turns and they end up as duplicate panel entries.
_THREAD_CREATING_TYPES = frozenset(
    {"new_quest", "hook_introduced", "major_event", "location_entered"}
)


def _normalize_for_dedup(text: str) -> str:
    """Aggressive normalize before similarity comparison.

    The GM frequently emits visually-similar descriptions that the raw
    SequenceMatcher under-rates because they differ in punctuation width,
    whitespace, or letter case. We:
      - replace full-width spaces (U+3000) and NBSP (U+00A0) with ASCII space
      - collapse runs of any whitespace to a single space
      - strip leading/trailing whitespace
      - normalize a few common CJK punctuation marks to ASCII
      - lowercase (helps when GM mixes English locale words)
    """
    if not text:
        return ""
    # Full-width space (U+3000) + NBSP (U+00A0) -> ASCII space
    text = text.replace("　", " ").replace(" ", " ")
    # Collapse all whitespace runs (also handles tabs, line breaks)
    text = re.sub(r"\s+", " ", text)
    text = text.strip()
    # Punctuation: CJK forms -> ASCII so "A，B" and "A,B" compare equal
    text = (
        text.replace("，", ",")
        .replace("。", ".")
        .replace("！", "!")
        .replace("？", "?")
        .replace("：", ":")
        .replace("；", ";")
    )
    return text.lower()


def _is_duplicate_thread(
    new_desc: str, existing_threads: list[PlotThread]
) -> int | None:
    """If `new_desc` is substantially the same as an existing active thread's
    description (SequenceMatcher ratio >= _PLOT_DEDUP_RATIO after
    normalization), return its id; else None. Empty descriptions never match.
    Exact post-normalization equality short-circuits to a hit."""
    new_norm = _normalize_for_dedup(new_desc)
    if not new_norm:
        return None
    for t in existing_threads:
        old_norm = _normalize_for_dedup(t.description or "")
        if not old_norm:
            continue
        if new_norm == old_norm:
            return t.id
        ratio = SequenceMatcher(None, new_norm, old_norm).ratio()
        if ratio >= _PLOT_DEDUP_RATIO:
            return t.id
    return None


async def _apply_plot_event(
    session: AsyncSession,
    session_id: int,
    current_turn: int,
    attrs: dict[str, str],
    content: str,
) -> None:
    event_type = attrs.get("type", "major_event")
    try:
        importance = int(attrs.get("importance", "2"))
    except ValueError:
        importance = 2
    importance = max(1, min(3, importance))

    description = content.strip()
    if not description:
        return

    if event_type == "hook_resolved":
        thread_id_str = attrs.get("thread_id", "").strip()
        target = None
        if thread_id_str.isdigit():
            target = await session.get(PlotThread, int(thread_id_str))
        if target is None:
            target = (
                await session.execute(
                    select(PlotThread)
                    .where(
                        PlotThread.session_id == session_id,
                        PlotThread.status == "active",
                    )
                    .order_by(PlotThread.introduced_turn.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
        if target is not None:
            target.status = "resolved"
            target.resolution = description
        return

    # Dedup against existing *active* threads for any thread-creating type —
    # GM frequently re-emits the same quest description across turns with
    # minor wording tweaks, which previously inflated the plot_threads table.
    # v0.13: extended from {new_quest, hook_introduced} to also cover
    # major_event + location_entered (same problem in production logs).
    # Resolved threads are intentionally NOT considered (a re-opened version
    # of an old quest deserves a fresh row).
    if event_type in _THREAD_CREATING_TYPES:
        existing = list(
            (
                await session.execute(
                    select(PlotThread).where(
                        PlotThread.session_id == session_id,
                        PlotThread.status == "active",
                    )
                )
            ).scalars()
        )
        dup_id = _is_duplicate_thread(description, existing)
        if dup_id is not None:
            log.info(
                "plot_event dedup: skip new %r (matches existing thread #%d, turn %d)",
                description[:60],
                dup_id,
                current_turn,
            )
            return

    thread = PlotThread(
        session_id=session_id,
        type=event_type,
        description=description,
        introduced_turn=current_turn,
        importance=importance,
        status="active",
    )
    session.add(thread)
    await session.flush()
