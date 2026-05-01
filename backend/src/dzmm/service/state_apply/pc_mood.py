"""<pc_mood> handler — accumulate mood deltas into Session.pc_mood_json."""

import json

from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.db.models import Session as GameSession
from dzmm.parsing.repair import parse_loose_json


async def _apply_pc_mood(
    session: AsyncSession,
    session_id: int,
    raw: str,
) -> None:
    """Accumulate PC mood deltas into Session.pc_mood_json.

    Mood is a free-form keyword→int map (GM picks keywords like 紧张/兴奋/疲惫).
    Values clamp to [0, 100]. Missing keys start at 0."""
    payload = parse_loose_json(raw)
    if not isinstance(payload, dict):
        return
    sess = await session.get(GameSession, session_id)
    if sess is None:
        return
    moods = json.loads(sess.pc_mood_json or "{}")
    if not isinstance(moods, dict):
        moods = {}
    for axis, delta in payload.items():
        if not isinstance(delta, (int, float)):
            continue
        axis_key = str(axis)
        new_val = int(moods.get(axis_key, 0) + delta)
        moods[axis_key] = max(0, min(100, new_val))
    sess.pc_mood_json = json.dumps(moods, ensure_ascii=False)
