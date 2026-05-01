"""<character_xp> handler — bump Character.xp."""

from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.db.models import Character, Session as GameSession


async def _apply_character_xp(
    session: AsyncSession,
    session_id: int,
    attrs: dict[str, str],
    content: str,
) -> None:
    """Apply <character_xp delta="N"> by mutating Character.xp.

    Note: we don't auto-bump Character.level here; the frontend detects when
    the threshold is crossed and routes the user through /levelup, which
    advances the level and applies the player-chosen stat bonus.
    """
    try:
        delta = int(attrs.get("delta", "0"))
    except ValueError:
        return
    if delta == 0:
        return

    sess = await session.get(GameSession, session_id)
    if sess is None:
        return
    char = await session.get(Character, sess.character_id)
    if char is None:
        return
    char.xp = max(0, char.xp + delta)
