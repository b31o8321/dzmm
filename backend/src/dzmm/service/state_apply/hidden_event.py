"""<hidden_event> handler — implicit story state with a fuse."""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.db.models import HiddenEvent
from dzmm.parsing.repair import parse_loose_json

log = logging.getLogger(__name__)


async def _apply_hidden_event(
    session: AsyncSession,
    session_id: int,
    current_turn: int,
    attrs: dict[str, str],
    content: str,
) -> None:
    """Process <hidden_event> tag — implicit story state with a fuse.

    Two modes:
      1. Create: requires `kind` in attrs (or in JSON body). Subject/severity/
         description/consequence are optional; defaults applied.
      2. Resolve: attrs has `resolve` (any value) or `type="resolve"`. Marks
         all currently-active rows for the given subject as resolved.

    Tolerant input: payload may live in attrs OR be JSON in body. Body wins
    on conflict because GM tends to be more deliberate when emitting JSON.
    """
    payload: dict = {}
    payload.update({k: v for k, v in (attrs or {}).items()})
    body = (content or "").strip()
    if body:
        parsed = parse_loose_json(body)
        if isinstance(parsed, dict):
            payload.update(parsed)

    is_resolve = (
        "resolve" in payload
        or str(payload.get("type", "")).strip().lower() == "resolve"
    )
    if is_resolve:
        subject = str(payload.get("subject", "")).strip()
        if not subject:
            return
        stmt = select(HiddenEvent).where(
            HiddenEvent.session_id == session_id,
            HiddenEvent.subject == subject,
            HiddenEvent.status == "active",
        )
        rows = (await session.execute(stmt)).scalars().all()
        if not rows:
            return  # silent skip — non-existent subject is not an error
        resolution = str(payload.get("resolution", "")).strip()
        for ev in rows:
            ev.status = "resolved"
            ev.resolved_turn = current_turn
            if resolution:
                ev.resolution = resolution
        return

    kind = str(payload.get("kind", "")).strip()
    if not kind:
        return  # invalid create — kind is required

    try:
        severity = int(payload.get("severity", 2) or 2)
    except (TypeError, ValueError):
        severity = 2
    severity = max(1, min(3, severity))

    subject = str(payload.get("subject", "")).strip()[:120]
    kind = kind[:60]
    description = str(payload.get("description", ""))[:1000]
    consequence = str(payload.get("consequence", ""))[:1000]

    # v0.1.9 dedup: same (subject, kind) already active → update instead of
    # inserting a new row. Fixes GM repeating the same hidden_event 6 times in a
    # single playthrough and polluting the implicit-state injection list.
    existing = (await session.execute(
        select(HiddenEvent).where(
            HiddenEvent.session_id == session_id,
            HiddenEvent.subject == subject,
            HiddenEvent.kind == kind,
            HiddenEvent.status == "active",
        )
    )).scalars().first()
    if existing is not None:
        if description:
            existing.description = description
        if consequence:
            existing.consequence = consequence
        log.info(
            "hidden_event dedup: updating existing #%d (%s/%s) instead of inserting",
            existing.id, subject, kind,
        )
        return

    ev = HiddenEvent(
        session_id=session_id,
        subject=subject,
        kind=kind,
        severity=severity,
        description=description,
        consequence=consequence,
        introduced_turn=current_turn,
        status="active",
    )
    session.add(ev)
