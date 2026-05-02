"""Handler for <location_enter name="..." description="..." items="..."/> tag."""
import json
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

    # Parse items= attr (comma-separated names, no descriptions)
    items_attr = (attrs.get("items") or "").strip()
    new_items: list[dict] | None = None
    if items_attr:
        new_items = [{"name": n.strip(), "description": ""}
                     for n in items_attr.split(",") if n.strip()]

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
        # items= on revisit: only update if currently empty
        if new_items is not None:
            try:
                existing_items = json.loads(match.items_json or "[]")
            except (TypeError, ValueError):
                existing_items = []
            if not existing_items:
                match.items_json = json.dumps(new_items, ensure_ascii=False)
    else:
        session.add(Location(
            session_id=session_id,
            name=name,
            description=description,
            first_visited_turn=current_turn,
            last_visited_turn=current_turn,
            is_current=True,
            items_json=json.dumps(new_items, ensure_ascii=False) if new_items else "[]",
        ))
