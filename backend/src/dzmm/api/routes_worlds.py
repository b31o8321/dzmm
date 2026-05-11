# ============================================================
# routes_worlds.py — 世界（World）的 REST API 路由
#
# REST 基本概念：
#   GET    = 查询数据（不修改）
#   POST   = 创建新数据
#   PUT    = 全量更新已有数据
#   DELETE = 删除数据
#
# 这个文件负责处理所有「世界」相关的 HTTP 请求，
# 包括：列表、详情、创建、更新、删除，以及
# 触发世界书向量化索引（RAG）。
# ============================================================

import asyncio  # 用于创建异步后台任务（fire-and-forget 模式）
import json     # 用于序列化/反序列化 JSON 字段

# FastAPI 核心组件
from fastapi import APIRouter, Depends, HTTPException, Query
# APIRouter   = 路由组，类似 Flask 的 Blueprint，把相关接口归为一组
# Depends     = 依赖注入系统，FastAPI 会自动调用它并把结果注入参数
# HTTPException = 主动抛出 HTTP 错误（如 404 Not Found）
# Query       = 声明 URL 查询参数（?cascade=true 这种形式）

from pydantic import BaseModel                          # 数据校验基类
from sqlalchemy import delete as sa_delete, select      # SQL 操作构建器
from sqlalchemy.ext.asyncio import AsyncSession          # 异步数据库会话

# 内部模块
from dzmm.api.routes_sessions._common import delete_session_cascade  # 级联删除跑团存档
from dzmm.api.schemas import WorldIn, WorldOut          # 请求/响应数据结构
from dzmm.db.models import Character as CharacterModel  # 数据库角色模型
from dzmm.db.models import ModelConfig                  # 数据库模型配置
from dzmm.db.models import Screenplay                   # 数据库剧本模型
from dzmm.db.models import Session as SessionModel      # 数据库跑团存档模型
from dzmm.db.models import World                        # 数据库世界模型
from dzmm.service.world_rag import index_world_async    # 世界书向量化索引服务

# 创建路由组：所有路由的 URL 都以 /worlds 开头
# tags=["worlds"] 用于 Swagger 文档自动分组显示
router = APIRouter(prefix="/worlds", tags=["worlds"])


# ──────────────────────────────────────────────
# 工具函数
# ──────────────────────────────────────────────

# _to_out：把数据库 ORM 对象（World）转换成 API 响应对象（WorldOut）
# 因为数据库里 rules 存成 JSON 字符串，而 API 需要暴露 rules_mode 字段，
# 所以需要这一步「拆包」转换
def _to_out(w: World) -> WorldOut:
    # 解析 rules_json 字符串为 Python 字典，若为空则给默认值
    rules = json.loads(w.rules_json or '{"mode":"light"}')
    return WorldOut(id=w.id, name=w.name, content_md=w.content_md,
                    style=w.style, rules_mode=rules.get("mode", "light"))


# ReindexRequest：手动触发 RAG 重新索引时的请求体
# （定义在这里是因为只有这个文件用到它）
class ReindexRequest(BaseModel):
    ollama_url: str           # Ollama 服务地址（用于生成向量嵌入）
    model: str = "nomic-embed-text"  # 嵌入模型名，默认用 nomic-embed-text


# get_session_dep：数据库会话的依赖注入占位函数
# FastAPI 的依赖注入（Depends）要求提供一个可调用对象。
# 这里给一个会抛错的占位符，真正的实现由应用启动时通过
# app.dependency_overrides 注入（见 main.py）。
def get_session_dep():
    raise RuntimeError("override via dependency_overrides")


# _maybe_trigger_reindex：在世界创建/更新后，异步触发 RAG 重新索引
# 「fire-and-forget」= 启动后不等待结果，接口立刻返回，索引在后台跑
async def _maybe_trigger_reindex(w: World, s: AsyncSession) -> None:
    """Fire-and-forget RAG reindex after world create/update.

    Looks up the first available ModelConfig for its base_url.
    Silently skips if no config exists or content is empty.
    """
    # 如果世界书内容为空，没有东西可以索引，直接跳过
    if not w.content_md:
        return
    # 从数据库取第一条模型配置，用来获取 Ollama 服务地址
    cfg = (await s.execute(select(ModelConfig).limit(1))).scalar_one_or_none()
    if cfg is None:
        # 没有任何模型配置，无法索引，静默跳过
        return
    try:
        # asyncio.create_task 创建后台任务：不等待、不阻塞当前请求
        asyncio.create_task(
            index_world_async(w.id, w.content_md, cfg.base_url)
        )
    except RuntimeError:
        # No running event loop in tests — skip silently
        pass


# ──────────────────────────────────────────────
# POST /worlds — 创建新世界
# ──────────────────────────────────────────────

# @router.post("") 表示处理 POST /worlds 请求
# response_model=WorldOut 告诉 FastAPI 用 WorldOut 格式序列化返回值，
# 同时自动生成 Swagger 文档中的响应示例
@router.post("", response_model=WorldOut)
async def create_world(body: WorldIn, s: AsyncSession = Depends(get_session_dep)):
    # body: FastAPI 自动从请求体 JSON 解析并校验为 WorldIn 对象
    # s: FastAPI 通过 Depends(get_session_dep) 注入数据库会话

    # 用请求数据创建 ORM 对象（此时还没写入数据库）
    w = World(
        name=body.name,
        content_md=body.content_md,
        style=body.style,
        # rules_mode 在数据库里存为 JSON 字符串 {"mode": "light"}
        rules_json=json.dumps({"mode": body.rules_mode}),
    )
    s.add(w)          # 把对象加入当前数据库会话（标记为「待插入」）
    await s.commit()  # 真正写入数据库，并获得自动生成的 id
    await s.refresh(w)  # 从数据库重新加载对象（获取 id 等服务器生成的字段）
    await _maybe_trigger_reindex(w, s)  # 后台触发向量索引（不阻塞响应）
    return _to_out(w)  # 转换为 API 响应格式并返回


# ──────────────────────────────────────────────
# GET /worlds — 获取所有世界列表
# ──────────────────────────────────────────────

@router.get("", response_model=list[WorldOut])
async def list_worlds(s: AsyncSession = Depends(get_session_dep)):
    # select(World) 构建 SQL: SELECT * FROM worlds ORDER BY id
    rows = (await s.execute(select(World).order_by(World.id))).scalars().all()
    # .scalars().all() = 从查询结果中取出所有 World 对象组成列表
    return [_to_out(w) for w in rows]  # 把每条记录转为 API 格式


# ──────────────────────────────────────────────
# GET /worlds/{world_id} — 获取单个世界详情
# ──────────────────────────────────────────────

# {world_id} 是路径参数，FastAPI 自动从 URL 提取并注入为同名函数参数
@router.get("/{world_id}", response_model=WorldOut)
async def get_world(world_id: int, s: AsyncSession = Depends(get_session_dep)):
    # s.get(World, world_id) = 按主键查询，相当于 SELECT * FROM worlds WHERE id=world_id
    w = await s.get(World, world_id)
    if w is None:
        # 抛出 HTTP 404 Not Found，FastAPI 会把它转成 {"detail": "world not found"}
        raise HTTPException(404, "world not found")
    return _to_out(w)


# ──────────────────────────────────────────────
# PUT /worlds/{world_id} — 全量更新世界
# ──────────────────────────────────────────────

# PUT = 替换整条记录（所有字段都更新）
@router.put("/{world_id}", response_model=WorldOut)
async def update_world(
    world_id: int, body: WorldIn, s: AsyncSession = Depends(get_session_dep)
):
    w = await s.get(World, world_id)
    if w is None:
        raise HTTPException(404, "world not found")
    # 逐字段覆盖（全量更新）
    w.name = body.name
    w.content_md = body.content_md
    w.style = body.style
    w.rules_json = json.dumps({"mode": body.rules_mode})
    await s.commit()    # 提交修改到数据库
    await s.refresh(w)  # 重新加载确保数据最新
    await _maybe_trigger_reindex(w, s)  # 内容变了，重新建立向量索引
    return _to_out(w)


# ──────────────────────────────────────────────
# GET /worlds/{world_id}/cascade_summary — 预览级联删除影响范围
# ──────────────────────────────────────────────

@router.get("/{world_id}/cascade_summary")
async def cascade_summary(world_id: int, s: AsyncSession = Depends(get_session_dep)):
    """Return counts of subresources that would be deleted with cascade=true.
    Used by the frontend to show a confirmation dialog before destructive delete."""
    w = await s.get(World, world_id)
    if w is None:
        raise HTTPException(404, "world not found")
    # 统计该世界下的角色数量（只查 id 列，性能更好）
    chars = len((
        await s.execute(select(CharacterModel.id).where(CharacterModel.world_id == world_id))
    ).scalars().all())
    # 统计该世界下的跑团存档数量
    sessions = len((
        await s.execute(select(SessionModel.id).where(SessionModel.world_id == world_id))
    ).scalars().all())
    # 统计该世界下的「独立剧本」（session_id 为空 = 尚未开始跑的剧本）
    screenplays = len((
        await s.execute(
            select(Screenplay.id).where(
                Screenplay.world_id == world_id, Screenplay.session_id.is_(None),
            )
        )
    ).scalars().all())
    # 返回各子资源计数，前端用这个数字显示确认对话框
    return {"characters": chars, "sessions": sessions, "screenplays": screenplays}


# ──────────────────────────────────────────────
# DELETE /worlds/{world_id} — 删除世界
# ──────────────────────────────────────────────

# status_code=204 表示成功但不返回任何响应体（No Content）
@router.delete("/{world_id}", status_code=204)
async def delete_world(
    world_id: int,
    # Query(...) 声明这是 URL 查询参数：DELETE /worlds/1?cascade=true
    cascade: bool = Query(False, description="If true, also delete this world's characters, screenplays, and sessions (with all per-session subresources)."),
    s: AsyncSession = Depends(get_session_dep),
):
    w = await s.get(World, world_id)
    if w is None:
        raise HTTPException(404, "world not found")

    if not cascade:
        # 非级联模式：如果世界下还有子资源，拒绝删除（保护数据完整性）
        has_chars = (
            await s.execute(
                # .limit(1) = 只查一条，只关心「是否存在」，不用扫全表
                select(CharacterModel.id).where(CharacterModel.world_id == world_id).limit(1)
            )
        ).scalar_one_or_none()
        if has_chars is not None:
            # 409 Conflict = 因为业务冲突无法完成请求
            raise HTTPException(409, "world has characters (该世界仍有角色)")
        has_sessions = (
            await s.execute(
                select(SessionModel.id).where(SessionModel.world_id == world_id).limit(1)
            )
        ).scalar_one_or_none()
        if has_sessions is not None:
            raise HTTPException(409, "world has sessions (该世界仍有跑团存档)")
        await s.delete(w)   # 标记为「待删除」
        await s.commit()    # 真正执行删除
        return

    # Cascade path. Delete order:
    # 1) sessions (each via delete_session_cascade — also wipes any
    #    session-scoped Screenplay rows where session_id IS NOT NULL).
    # 2) world-level Screenplays (session_id IS NULL, world_id = this).
    # 3) characters of this world.
    # 4) the world row itself.

    # 级联删除模式：先删所有跑团存档（及其关联的消息、事件等子资源）
    sess_ids = (
        await s.execute(
            select(SessionModel.id).where(SessionModel.world_id == world_id)
        )
    ).scalars().all()
    for sid in sess_ids:
        # delete_session_cascade 负责清理每个存档的所有子资源
        # （消息、NPC、隐藏事件、骰子记录等）
        await delete_session_cascade(s, sid)
    if sess_ids:
        # 批量删除存档行（子资源已在上面清理完）
        await s.execute(
            sa_delete(SessionModel).where(SessionModel.id.in_(sess_ids))
        )
    # 删除该世界下未与存档绑定的独立剧本（session_id IS NULL）
    await s.execute(
        sa_delete(Screenplay).where(
            Screenplay.world_id == world_id, Screenplay.session_id.is_(None),
        )
    )
    # 删除该世界的所有角色
    await s.execute(
        sa_delete(CharacterModel).where(CharacterModel.world_id == world_id)
    )
    # 最后删除世界本身
    await s.delete(w)
    await s.commit()

    # Drop the world's vector index so embeddings on disk don't outlive the
    # World row. Best-effort; swallow errors so a stale ChromaDB never
    # blocks the user's "clean up this world" flow.
    # 删除磁盘上的向量索引（ChromaDB），避免孤儿数据占用空间
    # best-effort = 尽力而为，失败了也不影响主流程
    from dzmm.service.world_rag import delete_world_index
    delete_world_index(world_id)


# ──────────────────────────────────────────────
# POST /worlds/{world_id}/reindex — 手动触发 RAG 重新索引
# ──────────────────────────────────────────────

# status_code=202 = Accepted：请求已接受，但处理尚未完成（异步执行中）
@router.post("/{world_id}/reindex", status_code=202)
async def reindex_world(
    world_id: int,
    body: ReindexRequest,
    s: AsyncSession = Depends(get_session_dep),
):
    """手动触发世界书重新索引（向量化存入 ChromaDB）。

    返回 202 Accepted：后台异步执行，不等待完成。
    """
    w = await s.get(World, world_id)
    if w is None:
        raise HTTPException(404, "world not found")
    if not w.content_md:
        # 内容为空没必要索引，返回跳过状态
        return {"status": "skipped", "reason": "empty content"}
    # 后台启动索引任务，使用用户指定的 Ollama 地址和嵌入模型
    asyncio.create_task(
        index_world_async(w.id, w.content_md, body.ollama_url, body.model)
    )
    return {"status": "started"}  # 立刻返回，不等索引完成
