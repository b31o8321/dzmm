"""<era_begin> handler — start a new Era row."""

from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.db.models import Era


async def _apply_era_begin(
    session: AsyncSession,
    session_id: int,
    current_turn: int,
    attrs: dict[str, str],
    content: str,
) -> None:
    name = attrs.get("name", "").strip()
    if not name:
        return
    era = Era(
        session_id=session_id,
        name=name,
        started_turn=current_turn,
        description=content.strip(),
    )
    session.add(era)
