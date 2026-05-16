# ============================================================
# routes_screenplay.py — 单个游戏存档（Session）的剧本大纲 API
# ============================================================
#
# 【什么是剧本大纲（Screenplay）？】
#   在这个跑团系统里，每个游戏存档（Session）都关联一份"剧本大纲"，
#   记录了整个故事的章节结构、关键 NPC、结局方向等。
#   GM（游戏主持）在推进故事时会参考大纲，确保剧情有始有终。
#
# 【为什么要"动态重写"剧本？】
#   玩家的重大决策可能改变故事走向。当玩家做出关键选择时（比如杀死了关键 NPC），
#   系统会调用 LLM 把剩余章节重写，让大纲和实际发生的事情保持一致。
#
# 【什么是 ScreenplayRevision？】
#   每次大纲被重写，都会创建一条 ScreenplayRevision 记录，保存重写前后的章节对比，
#   供 GM 查看「因为玩家做了 X，故事从 Y 变成了 Z」。
#
# 【文件结构】
#   - _screenplay_dict: 把数据库 ORM 对象转成前端友好的 dict
#   - /generate: 为当前存档生成（或重新生成）剧本大纲
#   - /get (GET): 获取当前活跃的剧本大纲
#   - /mark_decision: 标记一个重大决策，触发大纲重写
#   - /continue: 剧本结束后，续写下一部
#   - /revisions: 列出所有重写记录
#   - /revisions/{rev_id}/process: 手动触发某条待处理的重写记录

"""v0.1.0 — screenplay (outline) API endpoints."""
import json
from typing import Any

# FastAPI 核心组件（见 routes_wizard.py 里的说明）
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

# select — SQLAlchemy 的查询构建器，用于写 SELECT 语句
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.api.routes_sessions import get_session_dep

# 数据库模型（ORM 类，对应数据库里的各张表）：
#   ModelConfig      — 模型配置表
#   Screenplay       — 剧本大纲表（每个存档可以有多版，只有一版是 active）
#   ScreenplayRevision — 大纲重写记录表
#   Session (重命名为 GameSession) — 游戏存档表
from dzmm.db.models import (
    ModelConfig,
    Screenplay,
    ScreenplayRevision,
    Session as GameSession,  # 避免和 Python/SQLAlchemy 自己的 Session 命名冲突
)
from dzmm.models.factory import build_client

# service 层的三个核心函数：
#   generate_screenplay          — 调用 LLM 生成新剧本大纲并写入数据库
#   get_active_screenplay        — 查询当前存档的活跃大纲
#   rewrite_screenplay_after_decision — 玩家决策后重写大纲
from dzmm.service.screenplay import (
    generate_screenplay,
    get_active_screenplay,
    rewrite_screenplay_after_decision,
)

# 路由前缀是 /sessions，因为剧本操作都是针对某个存档（session）的子资源
router = APIRouter(prefix="/sessions", tags=["screenplay"])


# ──────────────────────────────────────────────
# 辅助函数：把 ORM 对象序列化成 dict
# ──────────────────────────────────────────────

# Screenplay 是 SQLAlchemy ORM 对象，不能直接当 JSON 返回。
# 这个函数手动把它转成 Python dict，前端可以直接使用。
# JSON 字段（chapters_json、main_characters_json 等）是数据库里存的 JSON 字符串，
# 用 json.loads 解析成 Python 列表/字典后再返回，让前端不用再手动解析。
def _screenplay_dict(sp: Screenplay) -> dict:
    return {
        "id": sp.id,
        "session_id": sp.session_id,
        "version": sp.version,                # 版本号，每次重新生成会递增
        "genre": sp.genre,                    # 游戏类型，如"悬疑探案"
        "chapters": json.loads(sp.chapters_json or "[]"),  # 章节列表（JSON 字符串 → list）
        "main_characters": json.loads(sp.main_characters_json or "[]"),  # 主要角色列表
        "ending_md": sp.ending_md,            # 结局描述（Markdown 文本）
        "opening_hook": sp.opening_hook,      # 开场钩子——让玩家快速投入剧情的第一幕
        "current_chapter": sp.current_chapter,  # 当前进行到第几章
        "completed_events": json.loads(sp.completed_events_json or "[]"),  # 已完成的事件
        "parent_screenplay_id": sp.parent_screenplay_id,  # 如果是续集，指向上一部的 id
        "status": sp.status,  # "active"（进行中）或 "concluded"（已结束）
        "created_at": sp.created_at.isoformat() if sp.created_at else None,
        "concluded_at": sp.concluded_at.isoformat() if sp.concluded_at else None,
    }


# 大纲生成是一次性的多 token 输出，本地 7B 模型常常需要 90-180 秒。
# 默认的 cfg.timeout（60-120 秒）不够用，所以强制覆盖为 600 秒。
_OUTLINER_TIMEOUT_SECONDS = 600.0


# 构建一个超时时间更长的 LLM 客户端，专用于大纲生成场景。
# 只修改当次请求的客户端实例，不修改数据库里的 ModelConfig 记录。
def _build_outliner_client(cfg: ModelConfig):
    """Like build_client(cfg) but with a longer HTTP timeout suitable for
    multi-minute single-shot outline generation. Mutates a fresh client; the
    cfg row in the DB is unchanged."""
    client = build_client(cfg)
    if hasattr(client, "timeout"):
        # 取当前 timeout 和 600 秒的较大值，保证不会缩短原来的配置
        client.timeout = max(getattr(client, "timeout", 0.0), _OUTLINER_TIMEOUT_SECONDS)
    return client


# ──────────────────────────────────────────────
# 路由处理函数
# ──────────────────────────────────────────────

# POST /sessions/{session_id}/screenplay/generate
# 为指定存档生成（或重新生成）剧本大纲。
# 每次调用都会让 LLM 重新生成一份，并写入数据库，版本号自动递增。
@router.post("/{session_id}/screenplay/generate")
async def generate(
    session_id: int,        # URL 路径参数，FastAPI 自动从 URL 中解析
    payload: dict,          # 请求体，包含 genre（类型）和 custom_prompt（自定义提示）
    s: AsyncSession = Depends(get_session_dep),
):
    # 先查询存档是否存在
    sess = await s.get(GameSession, session_id)
    if sess is None:
        raise HTTPException(404, "session not found")
    # 查询该存档配置的 GM 模型（GM = Game Master，游戏主持人，这里指驱动剧情的 LLM）
    cfg = await s.get(ModelConfig, sess.gm_model_config_id)
    if cfg is None:
        raise HTTPException(400, "GM model config missing")
    client = _build_outliner_client(cfg)
    # 从请求体提取参数，用 .strip() 去掉多余空格
    genre = (payload.get("genre") or "悬疑探案").strip()
    custom = (payload.get("custom_prompt") or "").strip()
    # 调用 service 层生成大纲，同时写入数据库（但还未 commit）
    sp = await generate_screenplay(s, session_id, genre, custom, client)
    # commit() 永久提交改动
    await s.commit()
    # refresh() 重新从数据库读取对象，确保拿到最新的自增 id 等字段
    await s.refresh(sp)
    return _screenplay_dict(sp)


# GET /sessions/{session_id}/screenplay
# 获取指定存档当前活跃（status="active"）的剧本大纲
@router.get("/{session_id}/screenplay")
async def get_active(
    session_id: int,
    s: AsyncSession = Depends(get_session_dep),
):
    sp = await get_active_screenplay(s, session_id)
    if sp is None:
        raise HTTPException(404, "no active screenplay")
    return _screenplay_dict(sp)


# POST /sessions/{session_id}/screenplay/mark_decision
# 标记玩家做出了一个重大决策，触发大纲重写。
# 流程：① 创建一条 ScreenplayRevision 记录（先占位）→ ② 调用 LLM 重写大纲 → ③ 更新记录
@router.post("/{session_id}/screenplay/mark_decision")
async def mark_decision(
    session_id: int,
    payload: dict,
    s: AsyncSession = Depends(get_session_dep),
):
    # 获取当前活跃大纲
    sp = await get_active_screenplay(s, session_id)
    if sp is None:
        raise HTTPException(404, "no active screenplay")
    sess = await s.get(GameSession, session_id)
    # 从请求体取决策描述，截断到 500 字防止过长
    description = str(payload.get("description") or "玩家手动标记")[:500]
    # 先创建一条"占位"的修订记录，before/after 都是当前章节，summary 是占位符
    # 目的是：即使后续 LLM 调用失败，也能保留这条决策记录
    rev = ScreenplayRevision(
        screenplay_id=sp.id,
        revision_num=1,                          # 修订编号
        trigger_turn=sess.turn_count if sess else 0,  # 触发时的回合数
        trigger_description=description,          # 触发原因描述
        before_chapters_json=sp.chapters_json,   # 重写前的章节 JSON
        after_chapters_json=sp.chapters_json,    # 先和 before 一样，等 LLM 重写后再更新
        diff_summary="(rewriting…)",             # 占位符，表示"重写中"
    )
    s.add(rev)
    await s.commit()
    await s.refresh(rev)

    # Synchronously rewrite — caller is willing to wait (UI shows a spinner)
    # 同步等待 LLM 重写完成（前端会显示加载动画，用户愿意等）
    cfg = await s.get(ModelConfig, sess.gm_model_config_id) if sess else None
    if cfg is not None:
        client = _build_outliner_client(cfg)
        # 调用 LLM 重写剩余章节，把结果更新到 rev 记录里
        await rewrite_screenplay_after_decision(s, session_id, rev.id, description, client)
        await s.commit()
        await s.refresh(rev)

    return {
        "ok": True,
        "revision_id": rev.id,
        "diff_summary": rev.diff_summary,  # LLM 生成的改动摘要（比如"删除了章节3的刺客伏击"）
    }


# POST /sessions/{session_id}/screenplay/continue
# 当当前剧本结束（status="concluded"）后，基于上一部的结局生成续集剧本
@router.post("/{session_id}/screenplay/continue")
async def continue_to_next(
    session_id: int,
    payload: dict | None = None,  # payload 可选，本接口目前不需要额外参数
    s: AsyncSession = Depends(get_session_dep),
):
    sess = await s.get(GameSession, session_id)
    if sess is None:
        raise HTTPException(404, "session not found")
    # 查找最新的已结束剧本（按版本号倒序取第一条）
    prev = (await s.execute(
        select(Screenplay).where(
            Screenplay.session_id == session_id,
            Screenplay.status == "concluded",   # 只找已结束的
        ).order_by(Screenplay.version.desc())   # 取版本号最大的（最新一部）
    )).scalars().first()
    if prev is None:
        raise HTTPException(400, "no concluded screenplay to continue from")
    cfg = await s.get(ModelConfig, sess.gm_model_config_id)
    if cfg is None:
        raise HTTPException(400, "GM model config missing")
    client = _build_outliner_client(cfg)
    # 生成续集剧本，传入上一部的结局作为"开篇钩子"的参考
    sp = await generate_screenplay(
        s, session_id, prev.genre, prev.custom_prompt, client,
        parent_screenplay_id=prev.id,        # 记录父子关系，便于追溯
        previous_ending=prev.ending_md,      # 上一部的结局文本，LLM 据此续写
    )
    await s.commit()
    await s.refresh(sp)
    return _screenplay_dict(sp)


# GET /sessions/{session_id}/screenplay/revisions
# 列出当前活跃剧本的所有重写记录，按时间升序排列
@router.get("/{session_id}/screenplay/revisions")
async def list_revisions(
    session_id: int,
    s: AsyncSession = Depends(get_session_dep),
):
    sp = await get_active_screenplay(s, session_id)
    if sp is None:
        return []  # 没有活跃剧本时返回空列表，不报错
    rows = (await s.execute(
        select(ScreenplayRevision)
        .where(ScreenplayRevision.screenplay_id == sp.id)
        .order_by(ScreenplayRevision.created_at, ScreenplayRevision.id)
    )).scalars().all()
    return [
        {
            "id": r.id,
            "revision_num": r.revision_num,
            "trigger_turn": r.trigger_turn,
            "trigger_description": r.trigger_description,
            "diff_summary": r.diff_summary,
            # pending 标志：before == after 且 summary 里有"pending"或"rewriting"，
            # 说明这条记录是 GM 发出的 <plot_turn> 标签创建的占位，还没被处理。
            # 前端看到 pending=True 时会显示"重写"按钮，让 GM 手动触发处理。
            "pending": (r.before_chapters_json == r.after_chapters_json)
                and ("pending" in (r.diff_summary or "").lower()
                     or "rewriting" in (r.diff_summary or "").lower()),
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


# ──────────────────────────────────────────────
# PATCH /sessions/{session_id}/screenplay — 手动编辑剧本大纲
# ──────────────────────────────────────────────

class ScreenplayPatch(BaseModel):
    chapters: list[dict[str, Any]] | None = None         # 完整替换 chapters_json
    main_characters: list[dict[str, Any]] | None = None  # 完整替换 main_characters_json
    ending_md: str | None = None
    opening_hook: str | None = None


@router.patch("/{session_id}/screenplay")
async def patch_screenplay(
    session_id: int,
    body: ScreenplayPatch,
    s: AsyncSession = Depends(get_session_dep),
):
    """手动编辑剧本大纲（chapters / main_characters / ending_md / opening_hook）。
    只更新请求体中非 None 的字段；同时追加一条 ScreenplayRevision 记录。"""
    # 检查 session 是否存在
    sess = await s.get(GameSession, session_id)
    if sess is None:
        raise HTTPException(404, "session not found")

    # 查询活跃大纲
    sp = await get_active_screenplay(s, session_id)
    if sp is None:
        raise HTTPException(404, "no active screenplay")

    # 保存编辑前的 chapters_json（用于 Revision 记录）
    before_chapters_json = sp.chapters_json

    # 应用 chapters（完整替换）
    if body.chapters is not None:
        try:
            sp.chapters_json = json.dumps(body.chapters, ensure_ascii=False)
        except (TypeError, ValueError) as exc:
            raise HTTPException(422, f"chapters 无法序列化为 JSON: {exc}") from exc

    # 应用 main_characters（完整替换）
    if body.main_characters is not None:
        try:
            sp.main_characters_json = json.dumps(body.main_characters, ensure_ascii=False)
        except (TypeError, ValueError) as exc:
            raise HTTPException(422, f"main_characters 无法序列化为 JSON: {exc}") from exc

    if body.ending_md is not None:
        sp.ending_md = body.ending_md

    if body.opening_hook is not None:
        sp.opening_hook = body.opening_hook

    # 追加 ScreenplayRevision 记录，标记为 manual_edit
    rev = ScreenplayRevision(
        screenplay_id=sp.id,
        revision_num=1,
        trigger_turn=sess.turn_count if sess else 0,
        trigger_description="manual_edit",
        before_chapters_json=before_chapters_json,
        after_chapters_json=sp.chapters_json,
        diff_summary="manual edit by user",
    )
    s.add(rev)

    await s.commit()
    await s.refresh(sp)
    return _screenplay_dict(sp)


# POST /sessions/{session_id}/screenplay/revisions/{rev_id}/process
# 手动处理一条"待处理"的修订记录（通常由 GM 在对话中发出 <plot_turn> 标签触发）。
# 幂等：重复调用不会出错，只会用新的 LLM 结果覆盖之前的内容。
@router.post("/{session_id}/screenplay/revisions/{rev_id}/process")
async def process_revision(
    session_id: int,
    rev_id: int,   # URL 路径参数：要处理的修订记录的 id
    s: AsyncSession = Depends(get_session_dep),
):
    """Run outliner rewrite on a previously-stashed revision (e.g. one created
    by a GM-emitted <plot_turn impact="major">). Idempotent: re-processing a
    completed revision overwrites the after_chapters_json with a fresh rewrite.
    """
    # 查询修订记录是否存在
    rev = await s.get(ScreenplayRevision, rev_id)
    if rev is None:
        raise HTTPException(404, "revision not found")
    # 验证该修订记录确实属于这个存档的剧本（防止跨存档访问）
    sp = await s.get(Screenplay, rev.screenplay_id)
    if sp is None or sp.session_id != session_id:
        raise HTTPException(404, "revision/session mismatch")
    sess = await s.get(GameSession, session_id)
    if sess is None:
        raise HTTPException(404, "session not found")
    cfg = await s.get(ModelConfig, sess.gm_model_config_id)
    if cfg is None:
        raise HTTPException(400, "GM model config missing")

    client = _build_outliner_client(cfg)
    # 触发 LLM 重写，返回更新后的修订记录，失败返回 None
    result = await rewrite_screenplay_after_decision(
        s, session_id, rev.id, rev.trigger_description, client,
    )
    if result is None:
        await s.commit()
        raise HTTPException(500, "rewrite failed (see backend logs)")
    await s.commit()
    await s.refresh(rev)
    return {"ok": True, "revision_id": rev.id, "diff_summary": rev.diff_summary}
