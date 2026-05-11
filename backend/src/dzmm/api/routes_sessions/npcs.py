# ============================================================
# NPC 管理接口
# ============================================================
# 【模块作用】
#   提供对存档内 NPC（非玩家角色）的查询和管理操作：
#   - GET    /sessions/{id}/npcs                  获取所有 NPC 列表
#   - DELETE /sessions/{id}/npcs/auto_created      清理 NER 自动创建的存根 NPC
#   - PUT    /sessions/{id}/npcs/{npc_id}/pin      切换 NPC 的"钉选"状态
#   - PATCH  /sessions/{id}/npcs/{npc_id}/voice    设置 NPC 的 TTS 音色
#
# 【NPC 的创建方式】
#   NPC 不是玩家手动创建的，而是 GM（LLM）在每回合输出 <npc_update> 标签时自动创建/更新的。
#   还有一种是 NER（命名实体识别）回退机制：GM 忘记写标签但正文提到了人名时，
#   系统会自动创建一个描述为"（GM 未补全）"的存根 NPC。
#   这个模块提供清理这些存根的接口。
# ============================================================
"""NPC roster + pin-toggle endpoints."""
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.api.routes_sessions._common import _npc_to_dict, get_session_dep
from dzmm.db.models import NPC, Session as GameSession

router = APIRouter(prefix="/sessions", tags=["sessions"])


# NER 回退机制写入的固定哨兵描述字符串
# 用这个特殊描述来识别"自动创建的存根 NPC"（区别于 GM 正常创建的 NPC）
# v0.1.9: this exact string is the signature the NER fallback writes for stub
# NPCs (see service/state_apply/npc.py::_register_npc_ner_fallback). Used by
# the cleanup endpoint to identify rows safe to bulk-delete.
_NER_STUB_DESCRIPTION = "（GM 未补全）"


# ── GET /sessions/{session_id}/npcs ──────────────────────────────────
@router.get("/{session_id}/npcs")
async def get_npcs(session_id: int, s: AsyncSession = Depends(get_session_dep)):
    """Return all NPCs for this session with full fields (affinity, archetype,
    purpose, pin, notes timeline). Used by the NPC roster + detail dialog."""
    sess = await s.get(GameSession, session_id)
    if sess is None:
        raise HTTPException(404, "session not found")
    rows = (
        await s.execute(
            select(NPC)
            .where(NPC.session_id == session_id)
            .order_by(
                NPC.pinned.desc(),         # 钉选的 NPC 排最前
                NPC.last_seen_turn.desc(), # 然后按最近出场回合倒序
                NPC.id.desc(),             # 最后按 id 倒序（最新创建的排前）
            )
        )
    ).scalars().all()
    # _npc_to_dict: 把 NPC ORM 对象转换成包含所有前端需要字段的字典
    # 其中包括解析 JSON 字段（affinity/notes/emotion）和计算渐进披露映射
    return [_npc_to_dict(n) for n in rows]


# ── 请求体模型 ─────────────────────────────────────────────────────
class PinUpdate(BaseModel):
    # 切换钉选状态的请求体：只需要传一个布尔值
    pinned: bool


# ── DELETE /sessions/{session_id}/npcs/auto_created ──────────────────
@router.delete("/{session_id}/npcs/auto_created", status_code=204)
async def delete_auto_created_npcs(
    session_id: int,
    s: AsyncSession = Depends(get_session_dep),
):
    """v0.1.9 cleanup: drop every NER-fallback stub NPC for this session.

    Stubs are identified by the fixed sentinel description "（GM 未补全）",
    written by `_register_npc_ner_fallback`. Once the GM has run a real
    `<npc_update>` against a name, its description is replaced and the row
    is no longer eligible for cleanup. This is wired to the DebugView
    "🧹 清理 NER 自动创建" button so players can purge historical false
    positives picked up by older, looser NER thresholds."""
    # 背景：NER（命名实体识别）是一种用来从文本里提取人名的 AI 技术。
    # 当 GM 的输出正文里提到了新人名但没有附带 <npc_update> 标签时，
    # 系统用 NER 提取人名，自动创建描述为"（GM 未补全）"的 NPC 存根，
    # 避免 NPC 信息完全丢失。
    # 但 NER 的精度不是 100%，有时会误识别（比如把地名当人名），
    # 需要手动清理这些误创建的存根。

    sess = await s.get(GameSession, session_id)
    if sess is None:
        raise HTTPException(404, "session not found")

    from dzmm.service.npc_memory import delete_npc_memory

    # 先查出所有存根 NPC 的 id（删除 SQL 行之前先记录 id，用于清理向量数据库）
    stub_ids = (await s.execute(
        select(NPC.id).where(
            NPC.session_id == session_id,
            NPC.description == _NER_STUB_DESCRIPTION,  # 用描述字段识别存根
        )
    )).scalars().all()

    # 批量删除 SQL 行（一条 DELETE WHERE 语句，比逐行删除高效）
    await s.execute(
        delete(NPC).where(
            NPC.session_id == session_id,
            NPC.description == _NER_STUB_DESCRIPTION,
        )
    )
    await s.commit()

    # 删除每个 NPC 在 ChromaDB 里的向量记忆集合（best-effort）
    for nid in stub_ids:
        delete_npc_memory(nid)

    # Response(status_code=204)：明确返回 204 No Content（无响应体）
    return Response(status_code=204)


# ── PUT /sessions/{session_id}/npcs/{npc_id}/pin ─────────────────────
@router.put("/{session_id}/npcs/{npc_id}/pin")
async def update_npc_pin(
    session_id: int,
    npc_id: int,
    body: PinUpdate,
    s: AsyncSession = Depends(get_session_dep),
):
    # 按主键查 NPC，同时校验它属于当前存档（防止跨存档操作）
    npc = await s.get(NPC, npc_id)
    if npc is None or npc.session_id != session_id:
        raise HTTPException(404, "npc not found")
    npc.pinned = bool(body.pinned)  # bool() 确保是布尔类型（而不是 0/1 整数）
    await s.commit()
    # refresh() 重新从数据库加载 NPC 对象，确保返回的是最新的数据库状态
    await s.refresh(npc)
    return _npc_to_dict(npc)


# ── 请求体模型 ─────────────────────────────────────────────────────
class NpcVoicePatch(BaseModel):
    # 设置 TTS 音色的请求体
    tts_voice: str  # 音色名称（如 "zh-CN-XiaoxiaoNeural"）


# ── PATCH /sessions/{session_id}/npcs/{npc_id}/voice ─────────────────
@router.patch("/{session_id}/npcs/{npc_id}/voice")
async def patch_npc_voice(
    session_id: int,
    npc_id: int,
    body: NpcVoicePatch,
    s: AsyncSession = Depends(get_session_dep),
):
    # 给 NPC 指定 TTS（文字转语音）音色
    # 游戏里 GM 说话时可以用不同的声音表现不同的 NPC
    npc = await s.get(NPC, npc_id)
    if npc is None or npc.session_id != session_id:
        raise HTTPException(404, "npc not found")
    npc.tts_voice = body.tts_voice
    await s.commit()
    await s.refresh(npc)
    return _npc_to_dict(npc)
