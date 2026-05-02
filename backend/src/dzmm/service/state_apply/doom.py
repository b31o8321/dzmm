"""<doom delta="±N"> handler — update Session.doom_score (0-100)."""

from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.db.models import Session as GameSession


async def _apply_doom(
    session: AsyncSession,
    session_id: int,
    attrs: dict[str, str],
) -> None:
    try:
        delta = int(attrs.get("delta", "0"))
    except ValueError:
        return
    if delta == 0:
        return
    sess = await session.get(GameSession, session_id)
    if sess is None:
        return
    sess.doom_score = max(0, min(100, sess.doom_score + delta))
