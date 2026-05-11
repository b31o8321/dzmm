# ============================================================
# 存档（Session）CRUD 接口
# ============================================================
# 【模块作用】
#   负责游戏存档的增删改查（CRUD）操作：
#   - POST   /sessions            创建新存档
#   - GET    /sessions            列出所有存档
#   - GET    /sessions/{id}       获取单个存档信息
#   - DELETE /sessions/{id}       删除存档（级联删所有关联数据）
#   - PATCH  /sessions/{id}/settings      修改存档设置（内容等级/调试模式等）
#   - GET    /sessions/{id}/settings      读取存档设置
#   - PATCH  /sessions/{id}/gm_model      切换 GM 模型配置
#   - PATCH  /sessions/{id}/debug_state   调试用：直接修改游戏数值
#   - GET    /sessions/{id}/debug_state   调试用：读取游戏数值
# ============================================================
"""Sessions CRUD: POST/GET/DELETE /sessions, /sessions/{id}.

DELETE cascades through every per-session table since SQLite FKs aren't
enabled on this schema."""
import json
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.api.routes_sessions._common import (
    _to_out,
    delete_session_cascade,
    get_session_dep,
)
from dzmm.api.schemas import SessionIn, SessionOut
from dzmm.db.models import (
    CharState,
    ModelConfig,
    NPC,
    Screenplay,
    Session as GameSession,  # 重命名：避免与 Python 内置的 session 概念混淆
)

# APIRouter：模块化路由注册器
# prefix="/sessions" 表示本模块所有路由都以 /sessions 开头
# tags=["sessions"] 用于 OpenAPI 文档分组（Swagger UI 里会显示标签）
router = APIRouter(prefix="/sessions", tags=["sessions"])


# ── 请求体模型（Pydantic BaseModel）──────────────────────────────────
# Pydantic 模型负责自动解析并验证 HTTP 请求体（JSON → Python 对象）
# 类似 Java 中的 @RequestBody + Bean Validation

class PatchGmModelRequest(BaseModel):
    # 切换 GM 模型时的请求体：只需要传新的 ModelConfig id
    gm_model_config_id: int


class PatchSettingsRequest(BaseModel):
    # 修改存档设置的请求体
    # 所有字段都是 Optional（| None），只传需要改的字段，其余保持不变
    narrative_polish: bool | None = None   # 是否开启叙事润色（让 LLM 美化文字）
    debug_mode: bool | None = None         # 调试模式（前端显示额外信息）
    content_level: str | None = None       # 内容分级: safe | mature | unrestricted
    use_v10: bool | None = None            # 是否使用 v0.10 多 Agent 框架


# ── PATCH /sessions/{session_id}/settings ────────────────────────────
@router.patch("/{session_id}/settings")
async def patch_session_settings(
    session_id: int,
    body: PatchSettingsRequest,
    s: AsyncSession = Depends(get_session_dep),  # 依赖注入：FastAPI 自动提供 DB 会话
):
    # s.get(Model, pk) → 按主键查单行，比 select().where() 更简洁
    sess = await s.get(GameSession, session_id)
    if sess is None:
        raise HTTPException(404, "session not found")  # 404 = 资源不存在

    # settings_json 是数据库里存储的 JSON 字符串；先解析成 dict，修改后再存回去
    settings = json.loads(sess.settings_json or "{}")

    # 只更新请求中明确传入的字段（None 表示"不修改这个字段"）
    if body.narrative_polish is not None:
        settings["narrative_polish"] = body.narrative_polish
    if body.debug_mode is not None:
        settings["debug_mode"] = body.debug_mode
    if body.content_level in ("safe", "mature", "unrestricted"):
        # 额外的值校验：只接受合法的分级字符串
        settings["content_level"] = body.content_level
    if body.use_v10 is not None:
        settings["use_v10"] = body.use_v10

    # 把修改后的 dict 序列化回 JSON 字符串，存入 ORM 对象属性
    sess.settings_json = json.dumps(settings)
    # await s.commit() → 把本次事务的所有修改持久化到数据库
    await s.commit()
    return {"id": sess.id, "settings": settings}


# ── GET /sessions/{session_id}/settings ──────────────────────────────
@router.get("/{session_id}/settings")
async def get_session_settings(
    session_id: int,
    s: AsyncSession = Depends(get_session_dep),
):
    sess = await s.get(GameSession, session_id)
    if sess is None:
        raise HTTPException(404, "session not found")
    # json.loads(... or "{}") → 如果 settings_json 是 None，就用空字符串兜底
    return {"id": sess.id, "settings": json.loads(sess.settings_json or "{}")}


# ── PATCH /sessions/{session_id}/gm_model ────────────────────────────
@router.patch("/{session_id}/gm_model")
async def patch_session_gm_model(
    session_id: int,
    body: PatchGmModelRequest,
    s: AsyncSession = Depends(get_session_dep),
):
    sess = await s.get(GameSession, session_id)
    if sess is None:
        raise HTTPException(404, "session not found")
    # 校验 gm_model_config_id 对应的 ModelConfig 存在
    cfg = await s.get(ModelConfig, body.gm_model_config_id)
    if cfg is None:
        raise HTTPException(404, "model config not found")
    sess.gm_model_config_id = body.gm_model_config_id
    await s.commit()
    return {"id": sess.id, "gm_model_config_id": sess.gm_model_config_id}


# ── 调试用状态修改接口 ─────────────────────────────────────────────

class PatchDebugStateRequest(BaseModel):
    # 调试用：直接修改存档的各种数值（绕过正常游戏逻辑）
    doom_score: int | None = None        # 末日进度（0-100）
    turn_count: int | None = None        # 当前回合数
    scene_turn_count: int | None = None  # 当前场景内的回合数
    stats_json: str | None = None        # 角色属性 JSON 字符串（如 {"HP": 80}）
    inventory_json: str | None = None    # 背包物品 JSON 字符串（如 ["钥匙", "地图"]）


@router.patch("/{session_id}/debug_state", status_code=200)
async def patch_debug_state(
    session_id: int,
    body: PatchDebugStateRequest,
    s: AsyncSession = Depends(get_session_dep),
):
    sess = await s.get(GameSession, session_id)
    if sess is None:
        raise HTTPException(404, "session not found")

    # 修改 Session 级别的数值（带边界检查防止非法值）
    if body.doom_score is not None:
        sess.doom_score = max(0, min(100, body.doom_score))  # 限制在 0-100 范围内
    if body.turn_count is not None:
        sess.turn_count = max(0, body.turn_count)            # 不能为负数
    if body.scene_turn_count is not None:
        sess.scene_turn_count = max(0, body.scene_turn_count)

    # 修改 CharState（角色状态）—— 存储在独立的表中
    if body.stats_json is not None or body.inventory_json is not None:
        # 查找该存档的角色状态行；scalar_one_or_none() 返回单行或 None（不存在也不报错）
        cs = (
            await s.execute(select(CharState).where(CharState.session_id == session_id))
        ).scalar_one_or_none()
        if cs is None:
            # 如果还没有 CharState 行，创建一个新的
            cs = CharState(session_id=session_id)
            s.add(cs)  # s.add() 把新对象纳入当前会话，等待 commit 时写入数据库
        if body.stats_json is not None:
            json.loads(body.stats_json)   # 只用来校验 JSON 格式是否合法，不使用返回值
            cs.stats_json = body.stats_json
        if body.inventory_json is not None:
            json.loads(body.inventory_json)  # 同上，校验 JSON 格式
            cs.inventory_json = body.inventory_json

    await s.commit()
    return {
        "doom_score": sess.doom_score,
        "turn_count": sess.turn_count,
        "scene_turn_count": sess.scene_turn_count,
    }


# ── GET /sessions/{session_id}/debug_state ──────────────────────────
@router.get("/{session_id}/debug_state")
async def get_debug_state(
    session_id: int,
    s: AsyncSession = Depends(get_session_dep),
):
    sess = await s.get(GameSession, session_id)
    if sess is None:
        raise HTTPException(404, "session not found")
    # scalar_one_or_none() 查不到时返回 None，不抛异常
    cs = (
        await s.execute(select(CharState).where(CharState.session_id == session_id))
    ).scalar_one_or_none()
    return {
        "doom_score": sess.doom_score,
        "turn_count": sess.turn_count,
        "scene_turn_count": sess.scene_turn_count,
        "settings": json.loads(sess.settings_json or "{}"),
        # cs 可能为 None（新存档还没有 CharState），用三元表达式安全取值
        "stats": json.loads(cs.stats_json if cs else "{}"),
        "inventory": json.loads(cs.inventory_json if cs else "[]"),
    }


# ── POST /sessions ─────────────────────────────────────────────────
@router.post("", response_model=SessionOut)  # "" 表示 /sessions 本身（无子路径）
async def create_session(body: SessionIn, s: AsyncSession = Depends(get_session_dep)):
    # 创建新存档，支持两种模式：
    # 模式 A：传入 screenplay_id → 按剧本创建（自动生成角色、绑定剧本、导入 NPC）
    # 模式 B：传入 world_id + character_id → 手动指定世界和角色（自由模式）

    # 延迟导入（避免在模块加载时就触发循环依赖）
    from dzmm.db.models import Character as CharacterRow

    world_id = body.world_id
    character_id = body.character_id

    if body.screenplay_id is not None:
        # 模式 A：从剧本创建
        sp = await s.get(Screenplay, body.screenplay_id)
        if sp is None:
            raise HTTPException(404, "screenplay not found")
        world_id = sp.world_id  # 世界来自剧本
        # 根据剧本里的 PC 模板自动创建 Character 行
        char = CharacterRow(
            world_id=world_id,
            name=sp.pc_name or "主角",
            gender=sp.pc_gender or "",
            profile_md=sp.pc_profile_md or "",
            base_stats_json=sp.pc_base_stats_json or "{}",
        )
        s.add(char)
        # flush() 把 ORM 对象写入数据库但不提交事务，让 char.id 有值以便后续引用
        await s.flush()
        character_id = char.id
    elif world_id is None or character_id is None:
        # 模式 B：必须同时提供 world_id 和 character_id
        raise HTTPException(422, "either screenplay_id or both world_id+character_id are required")
        # 422 = Unprocessable Entity（请求格式正确但语义错误）

    # 创建 Session（存档）行
    sess = GameSession(
        name=body.name,
        world_id=world_id,
        character_id=character_id,
        screenplay_id=body.screenplay_id,
        framework_id=body.framework_id,
        gm_model_config_id=body.gm_model_config_id,
        summarizer_model_config_id=body.summarizer_model_config_id,
    )
    s.add(sess)
    await s.flush()  # 刷新以获取 sess.id（用于下面创建 CharState）

    # v0.10.4: copy Character.base_stats_json → CharState.stats_json so the
    # StatePanel shows the wizard-defined HP/sanity/etc from turn 0 instead
    # of '尚未初始化'. Backwards-compat: if Character row is missing or has
    # malformed JSON, CharState falls back to default '{}'.
    # 把角色初始属性复制到存档状态表，这样游戏一开始面板就显示正确的数值
    from dzmm.db.models import Character as _CharacterModel
    _initial_stats = "{}"
    if character_id is not None:
        _ch = await s.get(_CharacterModel, character_id)
        if _ch is not None and _ch.base_stats_json:
            _initial_stats = _ch.base_stats_json
    s.add(CharState(session_id=sess.id, stats_json=_initial_stats))

    # Tier-1 复用现有剧本：把剧本绑回新存档，并重置进度字段，让 GM/前端的
    # get_active_screenplay 能在新会话里找到它，且从第 1 章开始重玩。
    if body.screenplay_id is not None:
        sp = await s.get(Screenplay, body.screenplay_id)
        if sp is not None:
            sp.session_id = sess.id         # 绑定到新存档
            sp.current_chapter = 1          # 重置章节进度
            sp.completed_events_json = "[]" # 清空已完成事件
            sp.status = "active"            # 重置状态

            # 把剧本里预设的 NPC 模板导入到新存档
            # 这样打开存档后 NPC 面板立即显示剧本里定义的角色（虽然还没出场）
            try:
                npc_templates = json.loads(sp.npcs_json or "[]")
            except (ValueError, TypeError):
                npc_templates = []
            for tpl in npc_templates:
                if not isinstance(tpl, dict) or not tpl.get("name"):
                    continue  # 跳过无效模板
                s.add(NPC(
                    session_id=sess.id,
                    name=tpl.get("name", ""),
                    gender=tpl.get("gender", ""),
                    archetype=tpl.get("archetype", ""),
                    description=tpl.get("description", ""),
                    state=tpl.get("state", "未知"),
                    purpose=tpl.get("purpose", ""),
                    favor=0,             # 初始好感度为 0
                    pinned=True,         # 剧本 NPC 默认钉选（重要角色）
                    last_seen_turn=0,    # 还没出场
                    notes_json="[]",
                    affinity_json="{}",
                    revealed_json='{"name": true}',  # 初始只显示名字
                ))

    # commit() 将所有变更写入数据库并结束事务
    await s.commit()
    # refresh() 从数据库重新加载对象，确保所有字段（包括数据库自动填充的）都是最新值
    await s.refresh(sess)
    return _to_out(sess)  # 转换成 Pydantic 响应模型


# ── GET /sessions/{session_id} ────────────────────────────────────
@router.get("/{session_id}", response_model=SessionOut)
async def get_session(session_id: int, s: AsyncSession = Depends(get_session_dep)):
    sess = await s.get(GameSession, session_id)
    if sess is None:
        raise HTTPException(404, "session not found")
    return _to_out(sess)


# ── GET /sessions ─────────────────────────────────────────────────
@router.get("", response_model=list[SessionOut])
async def list_sessions(s: AsyncSession = Depends(get_session_dep)):
    # select(GameSession) → 构建 SQL SELECT * FROM sessions
    # order_by(GameSession.last_played.desc()) → 按最近游玩时间倒序
    # .scalars().all() → 把 SQLAlchemy 的 Row 结果集提取为 Python 对象列表
    rows = (await s.execute(
        select(GameSession).order_by(GameSession.last_played.desc())
    )).scalars().all()
    return [_to_out(x) for x in rows]  # 列表推导式：批量转换格式


# ── DELETE /sessions/{session_id} ────────────────────────────────
@router.delete("/{session_id}", status_code=204)  # 204 = No Content（成功但无返回体）
async def delete_session(
    session_id: int, s: AsyncSession = Depends(get_session_dep)
):
    """Delete a session and all of its associated rows. The world, character,
    and model_configs are NOT touched (shared across sessions)."""
    # 注意：世界（World）、角色（Character）、模型配置（ModelConfig）是跨存档共享的，
    # 删存档时不会删这些"共享资源"
    sess = await s.get(GameSession, session_id)
    if sess is None:
        raise HTTPException(404, "session not found")
    # 先删除所有关联子表数据（因为 SQLite 没有开启外键级联删除）
    await delete_session_cascade(s, session_id)
    # 再删除 Session 行本身
    await s.delete(sess)
    await s.commit()
    return  # 204 响应不返回任何内容
