# ============================================================
# 地点列表查询接口
# ============================================================
# 【模块作用】
#   提供单个只读接口：
#   - GET /sessions/{id}/locations → 返回存档中所有已知地点
#
# 【地点的创建方式】
#   地点（Location）由 GM 在回合中输出 <location_update> 标签后自动创建/更新。
#   玩家第一次到达某地时记录 first_visited_turn，
#   每次重访时更新 last_visited_turn，并标记 is_current（当前所在地）。
#
# 【地图用途】
#   前端可以用这些数据绘制"探索地图"，展示玩家走过的地方和各地点的道具。
# ============================================================
"""GET /sessions/{id}/locations — list of visited locations."""
import json
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.api.routes_sessions._common import get_session_dep
from dzmm.db.models import Location, Session as GameSession

router = APIRouter(prefix="/sessions", tags=["sessions"])


# ── GET /sessions/{session_id}/locations ─────────────────────────────
@router.get("/{session_id}/locations")
async def get_locations(session_id: int, s: AsyncSession = Depends(get_session_dep)):
    sess = await s.get(GameSession, session_id)
    if sess is None:
        raise HTTPException(404, "session not found")

    # 按首次访问回合升序排列（最早发现的地点在前），id 作为次级排序稳定键
    rows = (await s.execute(
        select(Location).where(Location.session_id == session_id)
        .order_by(Location.first_visited_turn, Location.id)
    )).scalars().all()

    result = []
    for r in rows:
        # items_json: 该地点存放的道具列表，以 JSON 字符串存储
        # 用 try/except 防御性解析：即使字段损坏也安全返回 []
        try:
            items = json.loads(r.items_json or "[]")
            if not isinstance(items, list):
                items = []
        except (TypeError, ValueError):
            items = []
        result.append({
            "id": r.id,
            "name": r.name,
            "description": r.description,
            "first_visited_turn": r.first_visited_turn,  # 首次访问的回合号
            "last_visited_turn": r.last_visited_turn,    # 最近一次访问的回合号
            "is_current": r.is_current,                  # True = 玩家当前所在地
            "items": items,                              # 该地点的道具列表
        })
    return result
