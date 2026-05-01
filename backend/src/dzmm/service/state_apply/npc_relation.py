"""<npc_relation> handler — register unordered NPC↔NPC relationship pairs."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.db.models import NpcRelation


async def _apply_npc_relation(
    session: AsyncSession,
    session_id: int,
    current_turn: int,
    attrs: dict[str, str],
    content: str,
) -> None:
    """Register an NPC↔NPC relationship. The pair is treated as unordered:
    (A,B,kind) is equivalent to (B,A,kind), so re-declarations don't duplicate.

    If a row already exists and the new declaration carries a description while
    the old one is empty, fill in the description as a one-shot upgrade."""
    between = (attrs.get("between") or "").strip()
    parts = [p.strip() for p in between.split(",") if p.strip()]
    if len(parts) != 2:
        return
    a, b = parts[0], parts[1]
    kind = (attrs.get("kind") or "").strip() or "未定义"

    existing = (
        await session.execute(
            select(NpcRelation).where(
                NpcRelation.session_id == session_id,
                NpcRelation.kind == kind,
                ((NpcRelation.npc_a == a) & (NpcRelation.npc_b == b))
                | ((NpcRelation.npc_a == b) & (NpcRelation.npc_b == a)),
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        if content.strip() and not existing.description:
            existing.description = content.strip()
        return

    rel = NpcRelation(
        session_id=session_id,
        npc_a=a,
        npc_b=b,
        kind=kind,
        description=content.strip(),
        introduced_turn=current_turn,
    )
    session.add(rel)
