import json
from datetime import datetime, UTC

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.db.models import CharState, NPC
from dzmm.parsing.events import TagComplete
from dzmm.parsing.repair import parse_loose_json


async def apply_tags(
    session: AsyncSession,
    session_id: int,
    current_turn: int,
    tags: list[TagComplete],
) -> None:
    """Mutate CharState and NPC rows based on parsed tags. Caller commits."""
    for tag in tags:
        if tag.name == "state_change":
            await _apply_state_change(session, session_id, tag.content)
        elif tag.name == "npc_update":
            await _apply_npc_update(session, session_id, current_turn, tag.content)


async def _apply_state_change(
    session: AsyncSession, session_id: int, raw: str
) -> None:
    payload = parse_loose_json(raw)
    if not payload:
        return

    cs = (
        await session.execute(
            select(CharState).where(CharState.session_id == session_id)
        )
    ).scalar_one_or_none()
    if cs is None:
        cs = CharState(session_id=session_id, stats_json="{}", inventory_json="[]")
        session.add(cs)

    stats = json.loads(cs.stats_json or "{}")
    inventory = json.loads(cs.inventory_json or "[]")

    for key, val in payload.items():
        if key == "inventory_add" and isinstance(val, list):
            inventory.extend(str(x) for x in val)
        elif key == "inventory_remove" and isinstance(val, list):
            for item in val:
                if item in inventory:
                    inventory.remove(item)
        elif isinstance(val, (int, float)):
            stats[key] = stats.get(key, 0) + val

    cs.stats_json = json.dumps(stats, ensure_ascii=False)
    cs.inventory_json = json.dumps(inventory, ensure_ascii=False)
    cs.updated_at = datetime.now(UTC).replace(tzinfo=None)


async def _apply_npc_update(
    session: AsyncSession, session_id: int, current_turn: int, raw: str
) -> None:
    payload = parse_loose_json(raw)
    name = payload.get("name")
    if not name:
        return

    npc = (
        await session.execute(
            select(NPC).where(NPC.session_id == session_id, NPC.name == name)
        )
    ).scalar_one_or_none()
    if npc is None:
        npc = NPC(
            session_id=session_id,
            name=name,
            description=payload.get("description", ""),
            favor=0,
            state=payload.get("state", "未知"),
            last_seen_turn=current_turn,
            notes_json="[]",
        )
        session.add(npc)

    favor_delta = payload.get("favor_delta", 0)
    if isinstance(favor_delta, (int, float)):
        npc.favor += int(favor_delta)
    if "state" in payload:
        npc.state = str(payload["state"])
    if "description" in payload and not npc.description:
        npc.description = str(payload["description"])
    note = payload.get("note")
    if note:
        notes = json.loads(npc.notes_json or "[]")
        notes.append({"turn": current_turn, "text": str(note)})
        npc.notes_json = json.dumps(notes, ensure_ascii=False)
    npc.last_seen_turn = current_turn
