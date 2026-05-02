"""NPC initiative: find which NPC (if any) should proactively contact PC this turn."""
import json
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.db.models import NPC

log = logging.getLogger(__name__)

_INACTIVE_TURNS_MIN = 2   # NPC must have been absent at least this many turns
_COOLDOWN_TURNS = 4       # Minimum turns between two initiatives from same NPC


def _eagerness(npc: NPC) -> int:
    """Compute initiative eagerness score (higher = more likely to initiate)."""
    score = 10 if npc.pinned else 0
    score += max(0, npc.favor // 5)
    try:
        emotion = json.loads(npc.emotion_json or "{}")
        if emotion:
            score += max(emotion.values()) // 10
    except (TypeError, ValueError):
        pass
    return score


async def find_initiative_npc(
    session: AsyncSession,
    session_id: int,
    current_turn: int,
) -> NPC | None:
    """Return the best NPC to initiate contact this turn, or None.

    Eligibility requires:
    - NPC was seen at least once (last_seen_turn > 0)
    - Inactive for >= _INACTIVE_TURNS_MIN turns
    - Not in cooldown (current_turn - last_initiative_turn >= _COOLDOWN_TURNS)
    - Eagerness score > 0
    """
    npcs = (await session.execute(
        select(NPC).where(NPC.session_id == session_id)
    )).scalars().all()

    eligible: list[tuple[int, NPC]] = []
    for npc in npcs:
        if npc.last_seen_turn == 0:
            continue
        turns_inactive = current_turn - npc.last_seen_turn
        if turns_inactive < _INACTIVE_TURNS_MIN:
            continue
        turns_since_initiative = current_turn - npc.last_initiative_turn
        if turns_since_initiative < _COOLDOWN_TURNS:
            continue
        score = _eagerness(npc)
        if score <= 0:
            continue
        eligible.append((score, npc))

    if not eligible:
        return None

    eligible.sort(key=lambda x: (-x[0], -x[1].favor, -x[1].last_seen_turn))
    return eligible[0][1]
