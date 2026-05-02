"""v0.1.0 screenplay-driven tag handlers.

Four lightweight handlers that mutate the session's *active* Screenplay row
in response to <chapter_advance/>, <event_complete/>, <plot_turn/>,
<ending/>. All four share the same "lookup active screenplay then mutate"
shape; if no active screenplay exists they no-op silently (legacy sessions
created before v0.1.0 simply never see these tags applied).

attrs is a string→string dict from XML attribute parsing — chapter / event
indices need explicit int conversion with try/except since the GM may emit
them as decorative text.
"""

import json
from datetime import datetime, UTC

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.db.models import Character, Screenplay, ScreenplayRevision
from dzmm.db.models import Session as GameSession

_XP_MAIN = 50
_XP_OPTIONAL = 20


async def _get_active_screenplay(
    session: AsyncSession, session_id: int
) -> Screenplay | None:
    """Return the highest-version active Screenplay for the session, or None."""
    return (
        await session.execute(
            select(Screenplay)
            .where(
                Screenplay.session_id == session_id,
                Screenplay.status == "active",
            )
            .order_by(Screenplay.version.desc())
        )
    ).scalars().first()


async def _apply_chapter_advance(
    session: AsyncSession,
    session_id: int,
    attrs: dict[str, str],
    current_turn: int,
) -> None:
    """<chapter_advance/> → bump current_chapter by 1, clamped to total chapters
    (last chapter is a no-op so we don't go past the planned outline)."""
    sp = await _get_active_screenplay(session, session_id)
    if sp is None:
        return
    try:
        chapters = json.loads(sp.chapters_json or "[]")
    except (TypeError, ValueError):
        chapters = []
    if not isinstance(chapters, list):
        chapters = []
    if sp.current_chapter < len(chapters):
        sp.current_chapter += 1


async def _apply_event_complete(
    session: AsyncSession,
    session_id: int,
    attrs: dict[str, str],
    current_turn: int,
) -> None:
    """<event_complete chapter=N event=M type=main|optional/> →
    append {"chapter": N, "event_idx": M, "type": "main|optional"} to
    completed_events_json. Idempotent: re-emitting same triple is a no-op."""
    sp = await _get_active_screenplay(session, session_id)
    if sp is None:
        return

    try:
        chapter = int(attrs.get("chapter", ""))
        event_idx = int(attrs.get("event", ""))
    except (TypeError, ValueError):
        return  # attrs missing or non-numeric — silently skip

    type_ = (attrs.get("type") or "main").strip().lower()
    if type_ not in ("main", "optional"):
        type_ = "main"

    try:
        completed = json.loads(sp.completed_events_json or "[]")
    except (TypeError, ValueError):
        completed = []
    if not isinstance(completed, list):
        completed = []

    # Idempotency key matches on (chapter, event_idx, type) only — turn is
    # metadata for v0.2.2 P1.2 progress-stuck detection (key_facts uses the
    # max turn among completed events of the current chapter to estimate
    # turns_since_progress). Re-emit of the same triple is still a no-op
    # so we don't bump the recorded turn artificially.
    already = any(
        isinstance(c, dict)
        and c.get("chapter") == chapter
        and c.get("event_idx") == event_idx
        and (c.get("type") or "main") == type_
        for c in completed
    )
    if not already:
        rec = {
            "chapter": chapter,
            "event_idx": event_idx,
            "type": type_,
            "turn": current_turn,
        }
        completed.append(rec)
        sp.completed_events_json = json.dumps(completed, ensure_ascii=False)

        # Auto-award XP on event completion so the LLM doesn't need to track it.
        xp_delta = _XP_MAIN if type_ == "main" else _XP_OPTIONAL
        sess = await session.get(GameSession, session_id)
        if sess is not None:
            char = await session.get(Character, sess.character_id)
            if char is not None:
                char.xp = max(0, char.xp + xp_delta)

        # Completing a main event reduces doom pressure.
        if type_ == "main":
            sess = await session.get(GameSession, session_id)
            if sess is not None:
                sess.doom_score = max(0, sess.doom_score - 10)


async def _apply_plot_turn(
    session: AsyncSession,
    session_id: int,
    attrs: dict[str, str],
    current_turn: int,
) -> None:
    """<plot_turn impact=major|minor description=...> → only major creates a
    ScreenplayRevision row. The actual rewrite (after_chapters_json + diff_summary)
    is left to a later async outliner pass; we just stash the trigger and the
    *before* snapshot so the chain has provenance. minor is observational and
    intentionally a no-op here (we may pipe it into messages.events_json later).
    """
    impact = (attrs.get("impact") or "minor").strip().lower()
    if impact != "major":
        return

    sp = await _get_active_screenplay(session, session_id)
    if sp is None:
        return

    description = str(attrs.get("description", ""))[:500]

    rev = ScreenplayRevision(
        screenplay_id=sp.id,
        revision_num=1,
        trigger_turn=current_turn,
        trigger_description=description,
        before_chapters_json=sp.chapters_json or "[]",
        after_chapters_json=sp.chapters_json or "[]",
        diff_summary="(pending outliner rewrite)",
    )
    session.add(rev)


async def _apply_ending(
    session: AsyncSession,
    session_id: int,
    attrs: dict[str, str],
    current_turn: int,
) -> None:
    """<ending/> → mark active screenplay status="concluded" + concluded_at=now.
    Player can later launch a fresh chapter from the same session if desired."""
    sp = await _get_active_screenplay(session, session_id)
    if sp is None:
        return
    sp.status = "concluded"
    sp.concluded_at = datetime.now(UTC).replace(tzinfo=None)
