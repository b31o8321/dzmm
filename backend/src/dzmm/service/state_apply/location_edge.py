"""<location_edge> tag handler — 锁定场景拓扑关系。

GM 在首次进入新地点时必须 emit 一条 <location_edge>（搭配 <location_enter>）
把"出发地→目的地"的空间关系锁住。本 handler 把这条关系写进 location_edges 表。
是 idempotent 的：同一 (session_id, from, to, relation) 四元组只产生一行。
"""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.db.models import Location, LocationEdge

log = logging.getLogger(__name__)

_VALID_RELATIONS = {"contains", "adjacent", "connects", "blocked"}


async def _get_or_create_location(
    s: AsyncSession, session_id: int, name: str,
) -> Location | None:
    name = (name or "").strip()
    if not name:
        return None
    existing = (await s.execute(
        select(Location).where(
            Location.session_id == session_id, Location.name == name,
        )
    )).scalar_one_or_none()
    if existing is not None:
        return existing
    row = Location(session_id=session_id, name=name[:120])
    s.add(row)
    await s.flush()
    return row


async def _apply_location_edge(
    s: AsyncSession,
    session_id: int,
    attrs: dict[str, str],
    current_turn: int,
) -> None:
    from_name = (attrs.get("from") or "").strip()
    to_name = (attrs.get("to") or "").strip()
    relation = (attrs.get("relation") or "").strip().lower()
    if not from_name or not to_name or relation not in _VALID_RELATIONS:
        log.warning(
            "location_edge: skip invalid edge from=%r to=%r relation=%r",
            from_name, to_name, relation,
        )
        return
    if from_name == to_name:
        return

    src = await _get_or_create_location(s, session_id, from_name)
    dst = await _get_or_create_location(s, session_id, to_name)
    if src is None or dst is None:
        return

    existing = (await s.execute(
        select(LocationEdge).where(
            LocationEdge.session_id == session_id,
            LocationEdge.from_loc_id == src.id,
            LocationEdge.to_loc_id == dst.id,
            LocationEdge.relation == relation,
        )
    )).scalar_one_or_none()
    if existing is not None:
        new_desc = (attrs.get("description") or "").strip()[:500]
        if new_desc and len(new_desc) > len(existing.description or ""):
            existing.description = new_desc
        return

    s.add(LocationEdge(
        session_id=session_id,
        from_loc_id=src.id,
        to_loc_id=dst.id,
        relation=relation,
        description=(attrs.get("description") or "").strip()[:500],
        introduced_turn=current_turn,
    ))
