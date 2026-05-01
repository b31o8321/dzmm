"""Handler for <location_enter name="..." description="..."/> tag."""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from dzmm.db.models import Location


async def _apply_location_enter(
    session: AsyncSession,
    session_id: int,
    current_turn: int,
    attrs: dict,
    content: str,
) -> None:
    name = (attrs.get("name") or "").strip()
    if not name:
        return
    description = (attrs.get("description") or content or "").strip()

    # Clear is_current on all existing locations
    existing = (await session.execute(
        select(Location).where(Location.session_id == session_id)
    )).scalars().all()
    for loc in existing:
        loc.is_current = False

    # Upsert: find by name (case-insensitive match)
    match = next((l for l in existing if l.name.lower() == name.lower()), None)
    if match:
        match.last_visited_turn = current_turn
        match.is_current = True
        if description and not match.description:
            match.description = description
    else:
        session.add(Location(
            session_id=session_id,
            name=name,
            description=description,
            first_visited_turn=current_turn,
            last_visited_turn=current_turn,
            is_current=True,
        ))
