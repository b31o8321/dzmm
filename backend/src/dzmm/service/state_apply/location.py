# ============================================================
# 地点进入模块
#
# 负责处理 <location_enter> XML 标签，该标签由 GM 在 PC 进入新地点时 emit。
#
# 典型的 GM 输出示例：
#   <location_enter name="废弃医院" description="阴暗潮湿，到处是锈迹斑斑的病床" items="手术刀,断裂的注射器"/>
#
# 【地点拓扑（Topology）系统】
# dzmm 维护一张"地点图"（Location Graph），地点是节点，
# LocationEdge 是节点之间的边（表示相邻/包含/连接关系）。
# 良好的地图拓扑对于：
#   - 前端地图渲染正确显示空间关系
#   - 防止 PC 瞬移（从毫无关联的地点A直接跳到地点B）
# 都很重要。
#
# 当 GM 让 PC 进入新地点却没有 emit <location_edge> 时，
# 本模块会返回一条警告字符串，调度器把它写入数据库，
# 下回合提示词构建时会把警告注入 GM 的 system prompt，
# 强制 GM 在下一回合补发 <location_edge>。
# ============================================================

"""Handler for <location_enter name="..." description="..." items="..."/> tag.

v0.10 T12: 跨地点跳跃时如果没有 LocationEdge 记录两个地点之间的关系，
返回一条警告字符串给 dispatcher，由它累积到 Session.topology_warning_json，
下回合 _build_key_facts 注入 prompt 强制 GM 补 emit <location_edge>。
"""
import json
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from dzmm.db.models import Location, LocationEdge, Session as GameSession, WorldLocation


_PLACEHOLDER_LOCATION_NAMES = {
    "具体地点名", "地点名", "新地点", "目标地点", "a", "b", "...", "…",
}
_PLACEHOLDER_DESCRIPTIONS = {"一句话", "一句话描述", "描述", "...", "…"}


async def _check_topology(
    s: AsyncSession,
    session_id: int,
    current: Location | None,  # 当前地点（PC 现在在哪里）
    target_name: str,           # 目标地点名字（PC 要去哪里）
) -> str | None:
    # -------------------------------------------------------
    # 拓扑完整性检查
    #
    # 检查从 current 到 target 是否存在 LocationEdge 记录。
    # 如果不存在，返回一条格式化的警告字符串；
    # 如果存在或不需要检查，返回 None。
    #
    # 什么情况下不需要检查？
    # - current 为 None：PC 还没有位置记录（游戏刚开始），允许直接进入任何地点
    # - current 和 target 是同一个地点：原地"进入"，不是跳跃
    #
    # 为什么目标地点不存在时也要发警告？
    # - 按照 GM 规则，在叙事里让 PC 离开A进入B的同一回合，
    #   就应该 emit <location_edge> 来声明 A 和 B 的空间关系
    # - 如果目标地点根本不存在于数据库，说明 GM 跳过了这个步骤
    # -------------------------------------------------------
    """从 current 跳到 target_name 之前，检查是否有 LocationEdge 把两点连起来。
    没有 → 返回一条提示字符串；有 / 无需检查 → 返回 None。

    如果 target 还不存在（首次发现的新地点），仍需警告——因为 GM 应该在
    "narrative 写 PC 离开 A 进入 B" 的同一回合 emit `<location_edge>`，
    把空间关系锁住。
    """
    if current is None:
        return None  # 没有当前地点，不做检查
    if (current.name or "").strip() == target_name.strip():
        return None  # 原地进入同一地点，不需要检查

    # 查找目标地点是否已在数据库里
    target = (await s.execute(
        select(Location).where(
            Location.session_id == session_id, Location.name == target_name,
        )
    )).scalar_one_or_none()

    if target is not None:
        # 目标地点存在，检查两个地点之间是否有任意方向的 edge
        # （LocationEdge 是有向的，但空间关系通常是双向的，所以检查两个方向）
        has_edge = (await s.execute(
            select(LocationEdge.id).where(
                LocationEdge.session_id == session_id,
                or_(
                    # A → B 方向
                    (LocationEdge.from_loc_id == current.id)
                    & (LocationEdge.to_loc_id == target.id),
                    # B → A 方向
                    (LocationEdge.from_loc_id == target.id)
                    & (LocationEdge.to_loc_id == current.id),
                ),
            ).limit(1)  # 只需要知道"存在"，不需要取全部
        )).scalar_one_or_none()
        if has_edge is not None:
            return None  # 已有 edge，拓扑完整，不发警告

    # 没有 edge（或目标地点根本不存在），返回提示 GM 补发 <location_edge> 的警告
    return (
        f"⚠️ 拓扑警告：从「{current.name}」直接 enter「{target_name}」前，"
        f"系统未登记任何 location_edge。下回合 GM **必须** emit "
        f"<location_edge from=\"{current.name}\" to=\"{target_name}\" "
        f"relation=\"contains|adjacent|connects\" "
        f"description=\"...\"/> 把空间关系锁住。"
    )


async def _apply_location_enter(
    session: AsyncSession,  # 数据库会话
    session_id: int,        # 当前游戏局
    current_turn: int,      # 当前回合
    attrs: dict,            # XML 属性（name/description/items 等）
    content: str,           # 标签 body 文本（有时 GM 把描述放这里）
) -> str | None:
    # -------------------------------------------------------
    # 处理 <location_enter> 标签的主函数
    #
    # 执行步骤：
    # 1. 提取地点名、描述、道具列表
    # 2. 在翻转"当前地点"之前，先做拓扑检查（需要知道 PC 原来在哪）
    # 3. 把所有现有地点的 is_current 设为 False
    # 4. 找到或创建目标地点，设为 is_current=True
    # 5. 返回拓扑警告（如果有）
    #
    # 为什么是 upsert（找到就更新，找不到就创建）？
    # PC 可能多次进入同一地点，每次进入都应该更新 last_visited_turn，
    # 但不应该重复创建地点行。
    # -------------------------------------------------------
    name = (attrs.get("name") or "").strip()
    if not name:
        return None  # 没有地点名，忽略这个标签

    # 优先用 XML 属性里的 description，其次用标签 body 内容
    description = (attrs.get("description") or content or "").strip()
    if name.casefold() in {value.casefold() for value in _PLACEHOLDER_LOCATION_NAMES}:
        return f"⚠️ 地点登记被拒绝：name「{name}」是说明占位符，必须填写真实地点。"
    if description.casefold() in {value.casefold() for value in _PLACEHOLDER_DESCRIPTIONS}:
        return f"⚠️ 地点登记被拒绝：description「{description}」是说明占位符。"

    sess = await session.get(GameSession, session_id)
    framework_location: WorldLocation | None = None
    if sess is not None and sess.framework_id is not None:
        framework_location = (await session.execute(
            select(WorldLocation).where(
                WorldLocation.framework_id == sess.framework_id,
                WorldLocation.name == name,
            )
        )).scalar_one_or_none()
        if framework_location is None:
            return (
                f"⚠️ 地点登记被拒绝：「{name}」不属于当前开放世界框架。"
                "请使用框架中已有的准确地点名。"
            )
        name = framework_location.name
        if not description:
            description = framework_location.description_md

    # 解析道具列表：items="手术刀,断裂的注射器" → [{"name": "手术刀", "description": ""}, ...]
    # Parse items= attr (comma-separated names, no descriptions)
    items_attr = (attrs.get("items") or "").strip()
    new_items: list[dict] | None = None
    if items_attr:
        new_items = [{"name": n.strip(), "description": ""}
                     for n in items_attr.split(",") if n.strip()]

    # -------------------------------------------------------
    # 重要：在翻转 is_current 之前，先获取当前地点
    # 这样 _check_topology 才能知道 PC 是从哪里跳过来的
    # -------------------------------------------------------
    # v0.10 T12: capture current location BEFORE flipping is_current, so we
    # can check whether the GM is jumping to an unconnected place.
    existing = (await session.execute(
        select(Location).where(Location.session_id == session_id)
    )).scalars().all()
    current = next((loc for loc in existing if loc.is_current), None)  # 找到当前地点

    # 做大小写不敏感的名字匹配，防止 GM 前后大小写不一致
    target_lookup_name = name
    match = next((loc for loc in existing if loc.name.lower() == name.lower()), None)
    if match is not None:
        target_lookup_name = match.name  # 用数据库里的标准名称做拓扑检查

    # 拓扑完整性检查（在修改数据库之前做）
    warning = await _check_topology(
        session, session_id, current, target_lookup_name,
    )

    # 把所有现有地点的"当前"标记清除（PC 只能同时在一个地点）
    # Clear is_current on all existing locations
    for loc in existing:
        loc.is_current = False

    # Upsert: find by name (case-insensitive match)
    if match:
        # 地点已存在（PC 是在重游旧地）
        match.last_visited_turn = current_turn  # 更新最后到访回合
        match.is_current = True                  # 标记为当前地点
        if description and not match.description:
            match.description = description       # 只在原描述为空时补充描述
        # 道具列表：重游时只在当前道具列表为空时才写入（保留之前的状态）
        # items= on revisit: only update if currently empty
        if new_items is not None:
            try:
                existing_items = json.loads(match.items_json or "[]")
            except (TypeError, ValueError):
                existing_items = []
            if not existing_items:
                match.items_json = json.dumps(new_items, ensure_ascii=False)
    else:
        # 地点不存在，创建新行
        session.add(Location(
            session_id=session_id,
            name=name,
            description=description,
            first_visited_turn=current_turn,  # 首次到访回合
            last_visited_turn=current_turn,
            is_current=True,
            items_json=json.dumps(new_items, ensure_ascii=False) if new_items else "[]",
        ))

    if sess is not None and framework_location is not None:
        try:
            settings = json.loads(sess.settings_json or "{}")
        except (TypeError, ValueError):
            settings = {}
        settings["pc_location_id"] = framework_location.id
        sess.settings_json = json.dumps(settings, ensure_ascii=False)

    return warning  # 返回拓扑警告（可能为 None）
