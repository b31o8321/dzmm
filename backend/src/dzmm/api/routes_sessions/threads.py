# ============================================================
# 剧情线（Plot Thread）& NPC 关系查询接口
# ============================================================
# 【模块作用】
#   提供只读的元数据查询接口，用于右侧面板的信息展示：
#   - GET /sessions/{id}/threads            → 所有剧情线列表
#   - GET /sessions/{id}/threads/{thread_id} → 单条剧情线详情（附上下文消息）
#   - GET /sessions/{id}/relations          → 所有 NPC 之间的关系
#
# 【只读的含义】
#   这些接口没有 POST/PUT/DELETE，所有数据的变更都通过 /turn 接口
#   由 GM 输出 <plot_thread> / <npc_relation> 标签触发，再由
#   state_apply 模块解析并写入数据库。
#   这里只是读取数据库并格式化返回。
# ============================================================
"""Read-only meta endpoints: /threads, /relations.

These power the right-panel summaries; no writes happen here (all mutation
flows through state_apply tag handlers during /turn)."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.api.routes_sessions._common import get_session_dep
from dzmm.db.models import (
    Message,
    NpcRelation,
    PlotThread,
    Session as GameSession,
)

router = APIRouter(prefix="/sessions", tags=["sessions"])


# ── GET /sessions/{session_id}/threads ────────────────────────────────
@router.get("/{session_id}/threads")
async def get_threads(session_id: int, s: AsyncSession = Depends(get_session_dep)):
    sess = await s.get(GameSession, session_id)
    if sess is None:
        raise HTTPException(404, "session not found")
    rows = (
        await s.execute(
            select(PlotThread)
            .where(PlotThread.session_id == session_id)
            .order_by(
                PlotThread.status,             # 先按状态排序（active 排在 resolved 前）
                PlotThread.importance.desc(),  # 同状态内按重要性倒序
                PlotThread.id.desc(),          # 最后按 id 倒序（最新的在前）
            )
        )
    ).scalars().all()
    return [
        {
            "id": t.id,
            "type": t.type,           # 剧情类型（main/side/faction/mystery 等）
            "description": t.description,
            "importance": t.importance,  # 重要性分值（影响显示优先级）
            "status": t.status,       # active（进行中）/ resolved（已结束）
            "introduced_turn": t.introduced_turn,  # 该剧情线在第几回合引入
            "resolution": t.resolution,  # 结局描述（状态为 resolved 时有值）
        }
        for t in rows
    ]


# ── GET /sessions/{session_id}/threads/{thread_id} ───────────────────
@router.get("/{session_id}/threads/{thread_id}")
async def get_thread_detail(
    session_id: int,
    thread_id: int,
    s: AsyncSession = Depends(get_session_dep),
):
    """Return one plot thread's details."""
    sess = await s.get(GameSession, session_id)
    if sess is None:
        raise HTTPException(404, "session not found")
    thread = await s.get(PlotThread, thread_id)
    # 双重校验：剧情线存在 && 属于该存档
    if thread is None or thread.session_id != session_id:
        raise HTTPException(404, "thread not found")

    # 查询该剧情线引入时前后的上下文消息（帮助用户回忆剧情）
    # lo/hi 定义消息范围：引入回合前 1 回合 到 后 2 回合（共 4 回合窗口）
    lo = max(0, thread.introduced_turn - 1)
    hi = thread.introduced_turn + 2
    msgs = (await s.execute(
        select(Message)
        .where(Message.session_id == session_id, Message.turn >= lo, Message.turn <= hi)
        .order_by(Message.turn, Message.id)  # 按时间顺序排列
    )).scalars().all()

    return {
        "id": thread.id,
        "type": thread.type,
        "description": thread.description,
        "importance": thread.importance,
        "status": thread.status,
        "introduced_turn": thread.introduced_turn,
        "resolution": thread.resolution,
        # context_messages：该剧情线附近的对话片段，供用户回看
        # 内容截断到 500 字符（避免响应过大）
        "context_messages": [
            {"role": m.role, "content": m.content[:500], "turn": m.turn}
            for m in msgs
        ],
    }


# ── GET /sessions/{session_id}/relations ─────────────────────────────
@router.get("/{session_id}/relations")
async def get_relations(session_id: int, s: AsyncSession = Depends(get_session_dep)):
    """Return all NPC↔NPC relations registered via <npc_relation> for this session."""
    # NpcRelation 记录 NPC 之间的关系（朋友/敌人/家人/派系对立等）
    # 由 GM 在回合中输出 <npc_relation> 标签后由 state_apply 写入
    sess = await s.get(GameSession, session_id)
    if sess is None:
        raise HTTPException(404, "session not found")
    rows = (
        await s.execute(
            select(NpcRelation)
            .where(NpcRelation.session_id == session_id)
            .order_by(NpcRelation.introduced_turn.desc(), NpcRelation.id.desc())
            # 最近引入的关系排在前面
        )
    ).scalars().all()
    return [
        {
            "id": r.id,
            "npc_a": r.npc_a,         # 关系一方的 NPC 名字
            "npc_b": r.npc_b,         # 关系另一方的 NPC 名字
            "kind": r.kind,           # 关系类型（ally/rival/family/faction 等）
            "description": r.description,  # 关系描述
            "introduced_turn": r.introduced_turn,  # 在第几回合被揭示
        }
        for r in rows
    ]
