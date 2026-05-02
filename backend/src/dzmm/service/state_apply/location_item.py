"""Handler for <location_item name="..." description="..." action="add|remove"/> tag.

Modifies the items list of the current location (is_current=True).
Silently no-ops if no current location is set.
"""
import json
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from dzmm.db.models import Location


async def _apply_location_item(
    session: AsyncSession,
    session_id: int,
    current_turn: int,
    attrs: dict,
    content: str,
) -> None:
    name = (attrs.get("name") or "").strip()
    if not name:
        return
    action = (attrs.get("action") or "add").strip().lower()
    description = (attrs.get("description") or content or "").strip()

    loc = (await session.execute(
        select(Location).where(
            Location.session_id == session_id,
            Location.is_current == True,  # noqa: E712
        )
    )).scalar_one_or_none()
    if loc is None:
        return

    try:
        items: list[dict] = json.loads(loc.items_json or "[]")
        if not isinstance(items, list):
            items = []
    except (TypeError, ValueError):
        items = []

    if action == "remove":
        items = [i for i in items if i.get("name", "").lower() != name.lower()]
    else:  # "add" (default)
        existing = next((i for i in items if i.get("name", "").lower() == name.lower()), None)
        if existing:
            if description:
                existing["description"] = description
        else:
            items.append({"name": name, "description": description})

    loc.items_json = json.dumps(items, ensure_ascii=False)
