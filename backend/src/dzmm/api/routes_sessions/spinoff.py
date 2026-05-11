# ============================================================
# spinoff.py — 游戏存档"派生"（Spinoff）API
# ============================================================
#
# 【什么是"派生存档"（Spinoff）？】
#   玩家在当前故事进行到某个节点后，可能想"另起炉灶"——
#   保留同样的世界观、角色、部分 NPC，但从这个时间点重新开始讲一个新故事。
#   就像电影的衍生作品（Spinoff）：共享同一个宇宙，但是独立的新故事。
#
#   派生出的新存档：
#   - 继承：世界（world_id）、玩家角色（character_id）、模型配置
#   - 重置：回合数（turn_count=0）、NPC 的好感度（favor=0）和情绪（emotion={}）
#   - 可选：携带指定的 NPC（它们的基本信息保留，但关系值归零）
#
# 【为什么要重置好感度和情绪？】
#   因为派生存档是"全新的故事"。NPC 在新故事里还不认识玩家，
#   所以好感度和情绪应该从中立状态开始，而不是继承上一个存档里积累的关系。

"""POST /sessions/{id}/spinoff — create a new session forking from an existing one.

Copies world_id + character_id + gm_model_config_id + summarizer_model_config_id.
Copies selected NPCs (by id list) with favor and emotion reset to neutral.
"""
from datetime import datetime, UTC   # datetime 用于生成当前时间戳；UTC 确保时区一致

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.api.routes_sessions._common import get_session_dep

# NPC — NPC 数据模型（包含名字、描述、好感度、情绪等字段）
# GameSession — 游戏存档数据模型
from dzmm.db.models import NPC, Session as GameSession

# 挂载在 /sessions 路径下
router = APIRouter(prefix="/sessions", tags=["sessions"])


# 请求体：前端发来的派生参数
class SpinoffRequest(BaseModel):
    name: str           # 新存档的名称
    npc_ids: list[int] = []  # 想携带到新存档的 NPC id 列表（可以为空，不携带任何 NPC）


# POST /sessions/{session_id}/spinoff
# 从指定存档派生出一个新存档
@router.post("/{session_id}/spinoff")
async def spinoff_session(
    session_id: int,          # URL 路径参数：要从哪个存档派生
    body: SpinoffRequest,     # 请求体：新存档名称和要携带的 NPC
    s: AsyncSession = Depends(get_session_dep),
):
    # 查询父存档是否存在
    parent = await s.get(GameSession, session_id)
    if parent is None:
        raise HTTPException(404, "session not found")

    # datetime.now(UTC).replace(tzinfo=None) — 取当前 UTC 时间但去掉时区信息，
    # 因为数据库字段是 DATETIME（不含时区），如果传带时区的 datetime 会报错
    now = datetime.now(UTC).replace(tzinfo=None)

    # 创建子存档，继承父存档的世界/角色/模型配置
    child = GameSession(
        name=body.name or f"{parent.name} 续",  # 如果没填名字，自动用"父存档名 续"
        world_id=parent.world_id,               # 继承世界
        character_id=parent.character_id,       # 继承玩家角色
        gm_model_config_id=parent.gm_model_config_id,  # 继承 GM 模型配置
        summarizer_model_config_id=parent.summarizer_model_config_id,  # 继承摘要模型配置
        turn_count=0,      # 新存档从第 0 回合开始
        created_at=now,
        last_played=now,
    )
    s.add(child)
    # flush() — 把 child 写入数据库（执行 INSERT）但还没 commit，
    # 目的是让数据库分配 child.id，后面创建 NPC 时需要用到这个 id
    await s.flush()

    # 如果前端指定了要携带的 NPC，从父存档里查出这些 NPC 并复制到子存档
    if body.npc_ids:
        # 查询父存档中 id 在 npc_ids 列表里的 NPC
        # NPC.id.in_(body.npc_ids) — 相当于 SQL 的 WHERE id IN (1, 2, 3, ...)
        npcs = (await s.execute(
            select(NPC).where(NPC.session_id == session_id, NPC.id.in_(body.npc_ids))
        )).scalars().all()
        for npc in npcs:
            # 为每个 NPC 创建一个全新的副本，关联到子存档
            s.add(NPC(
                session_id=child.id,           # 关联到新存档
                name=npc.name,                 # 继承名字
                description=npc.description,   # 继承描述
                favor=0,                       # 好感度归零（新故事里双方还不熟）
                state="未知",                  # 状态重置为"未知"
                last_seen_turn=0,              # 上次见面回合重置
                notes_json="[]",               # 笔记清空
                purpose=npc.purpose,           # 继承 NPC 的故事用途
                archetype=npc.archetype,       # 继承角色原型（如"导师""反派"）
                affinity_json="{}",            # 亲密度数据清空
                pinned=npc.pinned,             # 继承"置顶"状态（重要 NPC 应保持置顶）
                emotion_json="{}",             # 情绪状态清空
                revealed_json='{"name": true}',  # 只有名字是已知的，其他信息玩家还不了解
            ))

    # commit() — 提交整个事务（子存档 + 所有 NPC 副本）
    # 如果中间任何一步失败，整个事务会自动回滚
    await s.commit()
    return {"id": child.id, "name": child.name}
