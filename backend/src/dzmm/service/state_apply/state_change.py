"""<state_change> handler — mutate CharState stats / inventory."""

import json
from datetime import datetime, UTC

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.db.models import CharState
from dzmm.parsing.repair import parse_loose_json


# Vital stats — these represent "life/mind/stamina" and clamp at 0 on the
# low side. Letting them drop arbitrarily negative (e.g. HP=-250) hides
# game-over conditions: the GM kept narrating combat / torment but the
# panel just kept incrementing damage. A 0 floor surfaces the dead-or-down
# state cleanly, and game.py injects a bad-ending hint when the floor is
# hit (see _critical_vitals_hint).
_VITAL_STATS = frozenset({"hp", "sanity", "stamina"})


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
            new_val = stats.get(key, 0) + val
            if key in _VITAL_STATS and new_val < 0:
                new_val = 0
            stats[key] = new_val

    cs.stats_json = json.dumps(stats, ensure_ascii=False)
    cs.inventory_json = json.dumps(inventory, ensure_ascii=False)
    cs.updated_at = datetime.now(UTC).replace(tzinfo=None)
