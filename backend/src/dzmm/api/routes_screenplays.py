# ============================================================
# routes_screenplays.py — 剧本（Screenplay）独立 CRUD API
# ============================================================
#
# 【和 routes_screenplay.py 的区别】
#   routes_screenplay.py  → 针对"某个游戏存档（Session）"的剧本操作，
#                           路径是 /sessions/{id}/screenplay/...，
#                           剧本和存档强绑定，生成/重写都依赖存档上下文。
#   routes_screenplays.py → 独立的剧本管理，剧本可以存在于世界（World）下
#                           但不绑定任何存档（session_id = NULL），
#                           供用户在"剧本库"里预先创建、编辑、删除剧本，
#                           需要时再关联到某个存档。
#
# 【为什么需要独立剧本？】
#   玩家可能想先写好几份剧本大纲，然后再决定玩哪个；
#   或者社区分享剧本时，剧本不能绑定到某个特定存档。
#   这个文件提供了完整的 CRUD（创建/读取/更新/删除）接口。
#
# 【什么是 PATCH 而不是 PUT？】
#   PUT = 完整替换整条记录（必须提供所有字段）
#   PATCH = 局部更新（只提供要改的字段，其余保持不变）
#   这里用 PATCH，更灵活，前端可以只发一个字段来修改。

"""Standalone Screenplay CRUD: independent of session lifecycle."""
from fastapi import APIRouter, Depends, HTTPException

# sa_delete — SQLAlchemy 的批量删除语句构建器，用于删除关联记录
# select — 查询语句构建器
from sqlalchemy import delete as sa_delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.api.routes_sessions._common import get_session_dep

# Pydantic 模式（Schema）类：
#   ScreenplayStandaloneIn  — 前端发来的剧本创建/更新请求体格式定义
#   ScreenplayStandaloneOut — 后端返回给前端的剧本数据格式定义
# Pydantic 负责自动验证字段类型和必填项，比手写 dict 检查更安全
from dzmm.api.schemas import ScreenplayStandaloneIn, ScreenplayStandaloneOut

# 数据库模型：
#   Screenplay         — 剧本大纲表
#   ScreenplayRevision — 剧本修订记录表（删除剧本时需级联删除）
#   Session (重命名)   — 游戏存档表（用于检查剧本是否被存档引用）
#   World              — 世界表（剧本归属某个世界）
from dzmm.db.models import Screenplay, ScreenplayRevision, Session as SessionModel, World

# 这个路由没有统一的 prefix，因为路径会因资源不同而变化（/worlds/.../screenplays 或 /screenplays/...）
router = APIRouter(tags=["screenplays"])


# ──────────────────────────────────────────────
# 辅助函数：ORM 对象 → Pydantic 输出模式
# ──────────────────────────────────────────────

# 把数据库 ORM 对象 Screenplay 转成 ScreenplayStandaloneOut（Pydantic 模型）。
# Pydantic 模型可以直接被 FastAPI 序列化成 JSON 返回给前端，
# 同时还提供字段类型校验，防止意外的 None 或类型错误。
def _sp_to_out(sp: Screenplay) -> ScreenplayStandaloneOut:
    return ScreenplayStandaloneOut(
        id=sp.id,
        world_id=sp.world_id,          # 剧本所属世界的 id
        session_id=sp.session_id,      # None（独立剧本）或某个存档的 id
        title=sp.title,                # 剧本标题
        genre=sp.genre,                # 游戏类型
        pc_name=sp.pc_name,            # 玩家角色（PC）名字
        pc_gender=sp.pc_gender or "",  # PC 性别，or "" 防止 None 传给 Pydantic
        pc_profile_md=sp.pc_profile_md,       # PC 详细设定（Markdown）
        pc_base_stats_json=sp.pc_base_stats_json,  # PC 基础属性（JSON 字符串）
        custom_prompt=sp.custom_prompt,            # 用户自定义的剧本生成提示
        outline_md=sp.outline_md,                  # 手动编写的大纲（Markdown）
        chapters_json=sp.chapters_json,            # LLM 生成的章节结构（JSON 字符串）
        main_characters_json=sp.main_characters_json,  # 主要角色列表（JSON）
        ending_md=sp.ending_md,                    # 结局描述（Markdown）
        opening_hook=sp.opening_hook,              # 开场钩子文本
        pc_tts_voice=sp.pc_tts_voice,              # PC 角色的 TTS 声音 ID
        version=sp.version,
        current_chapter=sp.current_chapter,
        completed_events_json=sp.completed_events_json,
        status=sp.status,
        created_at=sp.created_at.isoformat() if sp.created_at else "",  # 转为 ISO 8601 字符串
    )


# ──────────────────────────────────────────────
# 路由处理函数
# ──────────────────────────────────────────────

# POST /worlds/{world_id}/screenplays
# 在指定世界下创建一个独立剧本（不关联任何存档）
# response_model=ScreenplayStandaloneOut 告诉 FastAPI 按此模式序列化返回值
# status_code=201 表示资源创建成功（201 Created）
@router.post("/worlds/{world_id}/screenplays", response_model=ScreenplayStandaloneOut, status_code=201)
async def create_world_screenplay(
    world_id: int,
    body: ScreenplayStandaloneIn,  # FastAPI 自动把请求 JSON 解析成此 Pydantic 对象并验证
    s: AsyncSession = Depends(get_session_dep),
):
    # 验证世界是否存在
    world = await s.get(World, world_id)
    if world is None:
        raise HTTPException(404, "world not found")
    # 创建新的 Screenplay ORM 对象（尚未写入数据库）
    sp = Screenplay(
        world_id=world_id,
        session_id=None,              # 独立剧本，不绑定存档
        title=body.title,
        genre=body.genre,
        pc_name=body.pc_name,
        pc_gender=body.pc_gender,
        pc_profile_md=body.pc_profile_md,
        pc_base_stats_json=body.pc_base_stats_json,
        custom_prompt=body.custom_prompt,
        outline_md=body.outline_md,
        chapters_json=body.chapters_json,
        main_characters_json=body.main_characters_json,
        ending_md=body.ending_md,
        opening_hook=body.opening_hook,
        pc_tts_voice=body.pc_tts_voice,
    )
    s.add(sp)       # 把对象加入当前 session（还没写数据库）
    await s.commit()  # 提交事务，实际执行 INSERT 语句
    await s.refresh(sp)  # 刷新对象，获取数据库自动生成的 id 和 created_at
    return _sp_to_out(sp)


# GET /worlds/{world_id}/screenplays
# 列出指定世界下的所有独立剧本（不包括已关联存档的剧本），按创建时间倒序
@router.get("/worlds/{world_id}/screenplays", response_model=list[ScreenplayStandaloneOut])
async def list_world_screenplays(
    world_id: int,
    s: AsyncSession = Depends(get_session_dep),
):
    world = await s.get(World, world_id)
    if world is None:
        raise HTTPException(404, "world not found")
    rows = (await s.execute(
        select(Screenplay)
        .where(
            Screenplay.world_id == world_id,
            Screenplay.session_id.is_(None)  # 只取独立剧本（不关联存档的）
        )
        .order_by(Screenplay.created_at.desc())  # 最新创建的排在最前面
    )).scalars().all()
    # 把每条 ORM 记录转成 Pydantic 输出对象，组成列表返回
    return [_sp_to_out(sp) for sp in rows]


# GET /screenplays
# 跨世界列出所有独立剧本，供全局剧本管理界面使用
@router.get("/screenplays", response_model=list[ScreenplayStandaloneOut])
async def list_all_screenplays(s: AsyncSession = Depends(get_session_dep)):
    """Cross-world list of standalone screenplays (those not attached to a
    specific session). Powers the global screenplay management view."""
    rows = (await s.execute(
        select(Screenplay)
        .where(Screenplay.session_id.is_(None))  # 所有不关联存档的剧本
        .order_by(Screenplay.created_at.desc())
    )).scalars().all()
    return [_sp_to_out(sp) for sp in rows]


# GET /screenplays/{screenplay_id}
# 获取单个剧本的详情
@router.get("/screenplays/{screenplay_id}", response_model=ScreenplayStandaloneOut)
async def get_screenplay(
    screenplay_id: int,
    s: AsyncSession = Depends(get_session_dep),
):
    sp = await s.get(Screenplay, screenplay_id)
    if sp is None:
        raise HTTPException(404, "screenplay not found")
    return _sp_to_out(sp)


# PATCH /screenplays/{screenplay_id}
# 局部更新剧本内容（只更新前端发来的字段，其余保持不变）
@router.patch("/screenplays/{screenplay_id}", response_model=ScreenplayStandaloneOut)
async def patch_screenplay(
    screenplay_id: int,
    body: ScreenplayStandaloneIn,   # 请求体中可以只包含部分字段
    s: AsyncSession = Depends(get_session_dep),
):
    sp = await s.get(Screenplay, screenplay_id)
    if sp is None:
        raise HTTPException(404, "screenplay not found")
    # body.model_dump(exclude_unset=True) — 只返回前端实际传入的字段（跳过未传的字段）
    # 这样就实现了"只更新传入的字段"的 PATCH 语义
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(sp, field, value)   # 动态设置 ORM 对象的属性
    await s.commit()
    await s.refresh(sp)
    return _sp_to_out(sp)


# GET /screenplays/{screenplay_id}/refs
# 查询有多少个游戏存档正在引用这个剧本。
# 前端在删除存档时会先调用此接口，判断是否要同时提示删除剧本。
@router.get("/screenplays/{screenplay_id}/refs")
async def screenplay_refs(
    screenplay_id: int,
    s: AsyncSession = Depends(get_session_dep),
):
    """How many sessions still reference this screenplay. Frontend uses this
    to decide whether to offer "also delete screenplay" after deleting a
    session."""
    sp = await s.get(Screenplay, screenplay_id)
    if sp is None:
        raise HTTPException(404, "screenplay not found")
    # 查询所有 session_id 中 screenplay_id 等于此值的存档数量
    sess_count = len((
        await s.execute(
            select(SessionModel.id).where(SessionModel.screenplay_id == screenplay_id)
        )
    ).scalars().all())
    return {"sessions": sess_count}


# DELETE /screenplays/{screenplay_id}
# 删除一个独立剧本（204 No Content 表示删除成功且无返回体）
@router.delete("/screenplays/{screenplay_id}", status_code=204)
async def delete_screenplay(
    screenplay_id: int,
    s: AsyncSession = Depends(get_session_dep),
):
    sp = await s.get(Screenplay, screenplay_id)
    if sp is None:
        raise HTTPException(404, "screenplay not found")
    # 先检查是否有存档正在使用此剧本，有则拒绝删除（防止外键约束错误）
    in_use = (
        await s.execute(
            select(SessionModel.id).where(SessionModel.screenplay_id == screenplay_id).limit(1)
        )
    ).scalar_one_or_none()
    if in_use is not None:
        # 409 Conflict — 资源冲突，被其他资源引用，无法删除
        raise HTTPException(409, "screenplay is referenced by an existing session (剧本仍被存档使用)")
    # 先删除所有关联的修订记录（外键依赖，必须先删子表再删父表）
    await s.execute(
        sa_delete(ScreenplayRevision).where(ScreenplayRevision.screenplay_id == screenplay_id)
    )
    # 再删除剧本本身
    await s.delete(sp)
    await s.commit()
    # 204 响应无返回体，FastAPI 会自动处理
