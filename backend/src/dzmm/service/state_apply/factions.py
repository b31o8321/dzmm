"""<faction_create> and <faction_change> handlers."""
import json
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.db.models import Faction


async def _apply_faction_create(
    session: AsyncSession,
    session_id: int,
    attrs: dict,
    content: str,
) -> None:
    name = (attrs.get("name") or "").strip()
    if not name:
        return
    existing = (await session.execute(
        select(Faction).where(
            Faction.session_id == session_id,
            Faction.name == name,
        )
    )).scalar_one_or_none()
    if existing is not None:
        return  # idempotent: don't duplicate

    # hostile_to / allied_to attrs are JSON-array strings
    hostile = attrs.get("hostile_to") or "[]"
    allied = attrs.get("allied_to") or "[]"
    # Validate JSON; on failure, fall back to empty list
    try:
        hostile_parsed = json.loads(hostile)
        if not isinstance(hostile_parsed, list):
            hostile = "[]"
    except (TypeError, ValueError):
        hostile = "[]"
    try:
        allied_parsed = json.loads(allied)
        if not isinstance(allied_parsed, list):
            allied = "[]"
    except (TypeError, ValueError):
        allied = "[]"

    f = Faction(
        session_id=session_id,
        name=name,
        ideology=str(attrs.get("ideology") or "")[:200],
        description=(content or "").strip()[:500],
        hostile_to_json=hostile,
        allied_to_json=allied,
    )
    session.add(f)


async def _apply_faction_change(
    session: AsyncSession,
    session_id: int,
    attrs: dict,
) -> None:
    name = (attrs.get("name") or "").strip()
    if not name:
        return
    f = (await session.execute(
        select(Faction).where(
            Faction.session_id == session_id,
            Faction.name == name,
        )
    )).scalar_one_or_none()
    if f is None:
        return
    rd = attrs.get("rep_delta")
    if rd is not None:
        try:
            f.pc_reputation = max(-100, min(100, f.pc_reputation + int(rd)))
        except ValueError:
            pass
