"""Handler for <location_enter name="..." description="..." items="..."/> tag.

v0.10 T12: 跨地点跳跃时如果没有 LocationEdge 记录两个地点之间的关系，
返回一条警告字符串给 dispatcher，由它累积到 Session.topology_warning_json，
下回合 _build_key_facts 注入 prompt 强制 GM 补 emit <location_edge>。
"""
import json
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from dzmm.db.models import Location, LocationEdge


async def _check_topology(
    s: AsyncSession,
    session_id: int,
    current: Location | None,
    target_name: str,
) -> str | None:
    """从 current 跳到 target_name 之前，检查是否有 LocationEdge 把两点连起来。
    没有 → 返回一条提示字符串；有 / 无需检查 → 返回 None。

    如果 target 还不存在（首次发现的新地点），仍需警告——因为 GM 应该在
    "narrative 写 PC 离开 A 进入 B" 的同一回合 emit `<location_edge>`，
    把空间关系锁住。
    """
    if current is None:
        return None
    if (current.name or "").strip() == target_name.strip():
        return None
    target = (await s.execute(
        select(Location).where(
            Location.session_id == session_id, Location.name == target_name,
        )
    )).scalar_one_or_none()
    if target is not None:
        has_edge = (await s.execute(
            select(LocationEdge.id).where(
                LocationEdge.session_id == session_id,
                or_(
                    (LocationEdge.from_loc_id == current.id)
                    & (LocationEdge.to_loc_id == target.id),
                    (LocationEdge.from_loc_id == target.id)
                    & (LocationEdge.to_loc_id == current.id),
                ),
            ).limit(1)
        )).scalar_one_or_none()
        if has_edge is not None:
            return None
    return (
        f"⚠️ 拓扑警告：从「{current.name}」直接 enter「{target_name}」前，"
        f"系统未登记任何 location_edge。下回合 GM **必须** emit "
        f"<location_edge from=\"{current.name}\" to=\"{target_name}\" "
        f"relation=\"contains|adjacent|connects\" "
        f"description=\"...\"/> 把空间关系锁住。"
    )


async def _apply_location_enter(
    session: AsyncSession,
    session_id: int,
    current_turn: int,
    attrs: dict,
    content: str,
) -> str | None:
    name = (attrs.get("name") or "").strip()
    if not name:
        return None
    description = (attrs.get("description") or content or "").strip()

    # Parse items= attr (comma-separated names, no descriptions)
    items_attr = (attrs.get("items") or "").strip()
    new_items: list[dict] | None = None
    if items_attr:
        new_items = [{"name": n.strip(), "description": ""}
                     for n in items_attr.split(",") if n.strip()]

    # v0.10 T12: capture current location BEFORE flipping is_current, so we
    # can check whether the GM is jumping to an unconnected place.
    existing = (await session.execute(
        select(Location).where(Location.session_id == session_id)
    )).scalars().all()
    current = next((l for l in existing if l.is_current), None)

    # Topology check happens against the to-be-entered name (looked up fresh
    # in case it's a duplicate of an existing row by case-insensitive match).
    target_lookup_name = name
    match = next((l for l in existing if l.name.lower() == name.lower()), None)
    if match is not None:
        target_lookup_name = match.name
    warning = await _check_topology(
        session, session_id, current, target_lookup_name,
    )

    # Clear is_current on all existing locations
    for loc in existing:
        loc.is_current = False

    # Upsert: find by name (case-insensitive match)
    if match:
        match.last_visited_turn = current_turn
        match.is_current = True
        if description and not match.description:
            match.description = description
        # items= on revisit: only update if currently empty
        if new_items is not None:
            try:
                existing_items = json.loads(match.items_json or "[]")
            except (TypeError, ValueError):
                existing_items = []
            if not existing_items:
                match.items_json = json.dumps(new_items, ensure_ascii=False)
    else:
        session.add(Location(
            session_id=session_id,
            name=name,
            description=description,
            first_visited_turn=current_turn,
            last_visited_turn=current_turn,
            is_current=True,
            items_json=json.dumps(new_items, ensure_ascii=False) if new_items else "[]",
        ))

    return warning
