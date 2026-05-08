"""NPC initiative: find which NPC (if any) should proactively contact PC this turn."""
import json
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.db.models import Message as MessageRow, NPC

log = logging.getLogger(__name__)

# v0.10.2: was 2 with last_seen_turn, but v0.10 bumps last_seen_turn whenever
# an NPC name appears in narrative even if the NPC stays silent. We now use
# last_spoke_turn (real <say> emits) which is more conservative, so the
# inactivity threshold drops to 1 — an NPC who was on stage but didn't speak
# last turn gets a chance to make a delayed reaction this turn.
_INACTIVE_TURNS_MIN = 1
_COOLDOWN_TURNS = 4       # Minimum turns between two initiatives from same NPC
_LOOKBACK_TURNS = 8       # how many recent assistant messages to scan for <say>


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


async def _last_spoke_turn(
    session: AsyncSession,
    session_id: int,
    npc_name: str,
    current_turn: int,
) -> int:
    """Return the most recent turn at which `npc_name` actually emitted a
    <say> tag. Falls back to 0 if never. Scans only the most recent
    `_LOOKBACK_TURNS` assistant messages for cooldown purposes."""
    if not npc_name:
        return 0
    rows = (await session.execute(
        select(MessageRow.turn, MessageRow.events_json)
        .where(
            MessageRow.session_id == session_id,
            MessageRow.role == "assistant",
            MessageRow.turn >= max(1, current_turn - _LOOKBACK_TURNS),
        )
        .order_by(MessageRow.turn.desc())
    )).all()
    for turn, events_json in rows:
        if not events_json:
            continue
        try:
            events = json.loads(events_json)
        except (TypeError, ValueError):
            continue
        if not isinstance(events, list):
            continue
        for ev in events:
            if not isinstance(ev, dict):
                continue
            if ev.get("type") != "say":
                continue
            payload = ev.get("payload") or {}
            speaker = payload.get("speaker", "") if isinstance(payload, dict) else ""
            if speaker == npc_name:
                return int(turn)
    return 0


async def find_initiative_npc(
    session: AsyncSession,
    session_id: int,
    current_turn: int,
) -> NPC | None:
    """Return the best NPC to initiate contact this turn, or None.

    Eligibility requires:
    - NPC was seen at least once (last_seen_turn > 0)
    - Hasn't actually SPOKEN in the last _INACTIVE_TURNS_MIN turns
      (silent on stage now counts toward initiative eligibility — they
      get a chance to do a delayed reaction). NPCs who have never
      spoken (last_spoke_turn = 0) are always eligible by this check
      since their voice is "untapped".
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
        spoke_turn = await _last_spoke_turn(
            session, session_id, npc.name, current_turn,
        )
        # If NPC has never spoken (spoke_turn=0) but has appeared, treat as
        # always eligible — a never-heard-from NPC has the highest reason
        # to step in.
        if spoke_turn > 0 and (current_turn - spoke_turn) < _INACTIVE_TURNS_MIN:
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
