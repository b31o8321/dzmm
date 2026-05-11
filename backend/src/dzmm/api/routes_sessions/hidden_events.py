# ============================================================
# 隐藏事件查询接口
# ============================================================
# 【模块作用】
#   提供单个只读接口：
#   - GET /sessions/{id}/hidden_events → 返回 GM 追踪的隐藏事件列表
#
# 【什么是隐藏事件？】
#   隐藏事件（HiddenEvent）是 GM 在叙事中埋下的"定时炸弹"，玩家（前端）
#   通常不直接看到，只有 GM（LLM）在构建上下文时才能看到。
#   例子：
#   - 伤势（injury）：玩家角色受了伤，但还不知道严重性
#   - 截止日期（deadline）：某个任务必须在 N 回合内完成，否则触发惩罚
#   - 秘密（secret）：GM 知道但玩家尚未发现的信息
#   - 持续效果（status）：中毒/诅咒等状态
#
# 【为什么需要这个接口？】
#   虽然玩家通常看不到隐藏事件，但调试视图（DebugView）需要展示这些信息，
#   让开发者或"GM 视角"的玩家了解当前有哪些隐藏的剧情压力。
# ============================================================
"""GM-tracked hidden events: injuries, deadlines, secrets..."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.api.routes_sessions._common import get_session_dep
from dzmm.db.models import HiddenEvent, Session as GameSession

router = APIRouter(prefix="/sessions", tags=["sessions"])


# ── GET /sessions/{session_id}/hidden_events ─────────────────────────
@router.get("/{session_id}/hidden_events")
async def get_hidden_events(
    session_id: int,
    # 查询参数（Query Parameter）：URL 里的 ?include_resolved=true
    # FastAPI 会自动从 URL 解析这个参数，默认值为 False（只返回活跃事件）
    include_resolved: bool = False,
    s: AsyncSession = Depends(get_session_dep),
):
    """Return GM-tracked hidden events (injuries, deadlines, secrets...).
    By default only `active` rows; pass include_resolved=true for the full list."""
    sess = await s.get(GameSession, session_id)
    if sess is None:
        raise HTTPException(404, "session not found")

    # 动态构建查询条件
    stmt = select(HiddenEvent).where(HiddenEvent.session_id == session_id)
    if not include_resolved:
        # 默认只返回状态为 "active" 的事件（排除已结束/已触发的）
        stmt = stmt.where(HiddenEvent.status == "active")
    # 按引入回合升序排列，id 作为稳定键（最早埋下的隐患排在前面）
    stmt = stmt.order_by(HiddenEvent.introduced_turn, HiddenEvent.id)
    rows = (await s.execute(stmt)).scalars().all()

    return [
        {
            "id": h.id,
            "subject": h.subject,       # 事件主体（"玩家"/"NPC名"等）
            "kind": h.kind,             # 事件类型（injury/deadline/secret/status 等）
            "severity": h.severity,     # 严重程度（1-10）
            "description": h.description,  # 事件描述
            "consequence": h.consequence,  # 不处理时的后果
            "introduced_turn": h.introduced_turn,  # 在第几回合埋下
            "status": h.status,         # active（活跃）/ resolved（已解决）/ triggered（已触发）
        }
        for h in rows
    ]
