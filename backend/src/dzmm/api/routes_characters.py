# ============================================================
# routes_characters.py — 角色（Character）的 REST API 路由
#
# 提供的功能：
#   - CRUD：创建、列表、详情、更新、删除角色
#   - 头像上传/获取
#   - 角色升级（levelup）
#
# 「角色」= 玩家在跑团中扮演的 PC（Player Character），
# 每个角色都属于某个「世界」。
# ============================================================

import json         # 用于解析/序列化 base_stats_json 字段
from pathlib import Path  # 跨平台文件路径操作

# FastAPI 核心组件
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
# File      = 声明文件上传参数
# UploadFile = 表示上传的文件对象（含文件名、内容类型等）

from fastapi.responses import FileResponse  # 返回文件内容的特殊响应类型
from sqlalchemy import select               # SQL 查询构建器
from sqlalchemy.ext.asyncio import AsyncSession  # 异步数据库会话

from dzmm.api.schemas import CharacterIn, CharacterOut  # 请求/响应数据结构
from dzmm.config import APP_DIR             # 应用数据目录（存头像文件用）
from dzmm.db.models import Character        # 数据库角色 ORM 模型
from dzmm.db.models import Session as SessionModel  # 数据库跑团存档模型

# 创建路由组：所有路由的 URL 都以 /characters 开头
router = APIRouter(prefix="/characters", tags=["characters"])

# 允许上传的图片格式白名单（防止上传可执行文件）
_ALLOWED_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".svg", ".gif"}
# 上传文件大小上限：5 MB（防止超大文件耗尽磁盘/内存）
_MAX_BYTES = 5 * 1024 * 1024  # 5 MB


# 依赖注入占位函数（真正实现由 main.py 在启动时通过 dependency_overrides 注入）
def get_session_dep():
    raise RuntimeError("override")


# ──────────────────────────────────────────────
# 工具函数
# ──────────────────────────────────────────────

# _xp_threshold：计算升到下一级所需的累计经验值
# 公式：100 * level * (level + 1) / 2
# 例：level=1 时需要 100，level=2 时需要 300，以此类推
def _xp_threshold(level: int) -> int:
    """Cumulative XP needed to reach `level + 1`."""
    return 100 * level * (level + 1) // 2


# _serialize：把数据库 ORM 对象（Character）转换成 API 响应对象（CharacterOut）
# 之所以要单独封装，是因为 ORM 对象的字段可能含有 None 等需要处理的情况
def _serialize(c: Character) -> CharacterOut:
    return CharacterOut(
        id=c.id,
        world_id=c.world_id,
        name=c.name,
        gender=c.gender or "",          # None 转成空字符串，保持响应格式一致
        profile_md=c.profile_md,
        base_stats_json=c.base_stats_json,
        portrait_path=c.portrait_path or "",  # None 转成空字符串
        xp=c.xp,
        level=c.level,
    )


# ──────────────────────────────────────────────
# POST /characters — 创建新角色
# ──────────────────────────────────────────────

@router.post("", response_model=CharacterOut)
async def create_character(body: CharacterIn, s: AsyncSession = Depends(get_session_dep)):
    # body.model_dump() 把 Pydantic 对象转成字典，
    # ** 解包后作为关键字参数传给 Character(...)
    # 等价于 Character(world_id=body.world_id, name=body.name, ...)
    c = Character(**body.model_dump())
    s.add(c)           # 加入会话（标记为「待插入」）
    await s.commit()   # 写入数据库，生成 id
    await s.refresh(c) # 重新加载获取数据库生成的字段
    return _serialize(c)


# ──────────────────────────────────────────────
# GET /characters — 获取角色列表（可按世界过滤）
# ──────────────────────────────────────────────

@router.get("", response_model=list[CharacterOut])
async def list_characters(world_id: int | None = None,  # URL 查询参数：?world_id=1
                          s: AsyncSession = Depends(get_session_dep)):
    # 基础查询：获取所有角色，按 id 排序
    q = select(Character).order_by(Character.id)
    if world_id is not None:
        # 如果提供了 world_id，追加 WHERE 条件过滤
        q = q.where(Character.world_id == world_id)
    rows = (await s.execute(q)).scalars().all()  # 执行查询，取出所有结果
    return [_serialize(c) for c in rows]


# ──────────────────────────────────────────────
# GET /characters/{character_id} — 获取单个角色详情
# ──────────────────────────────────────────────

@router.get("/{character_id}", response_model=CharacterOut)
async def get_character(character_id: int, s: AsyncSession = Depends(get_session_dep)):
    c = await s.get(Character, character_id)  # 按主键查找
    if c is None:
        raise HTTPException(404, "character not found")
    return _serialize(c)


# ──────────────────────────────────────────────
# PUT /characters/{character_id} — 全量更新角色
# ──────────────────────────────────────────────

@router.put("/{character_id}", response_model=CharacterOut)
async def update_character(
    character_id: int, body: CharacterIn,
    s: AsyncSession = Depends(get_session_dep),
):
    c = await s.get(Character, character_id)
    if c is None:
        raise HTTPException(404, "character not found")
    # 逐字段覆盖（全量更新，所有可编辑字段都被替换）
    c.world_id = body.world_id
    c.name = body.name
    c.gender = body.gender
    c.profile_md = body.profile_md
    c.base_stats_json = body.base_stats_json
    await s.commit()
    await s.refresh(c)
    return _serialize(c)


# ──────────────────────────────────────────────
# DELETE /characters/{character_id} — 删除角色
# ──────────────────────────────────────────────

@router.delete("/{character_id}", status_code=204)
async def delete_character(
    character_id: int, s: AsyncSession = Depends(get_session_dep),
):
    c = await s.get(Character, character_id)
    if c is None:
        raise HTTPException(404, "character not found")
    # 安全检查：角色正在被跑团存档使用时，不允许删除
    # （否则删除后存档里的 character_id 外键会指向不存在的记录）
    has_sessions = (
        await s.execute(
            select(SessionModel.id).where(SessionModel.character_id == character_id).limit(1)
        )
    ).scalar_one_or_none()
    if has_sessions is not None:
        # 409 Conflict = 因为业务冲突无法操作
        raise HTTPException(409, "character has sessions (该角色仍有跑团存档)")
    await s.delete(c)
    await s.commit()


# ──────────────────────────────────────────────
# POST /characters/{character_id}/portrait — 上传头像
# ──────────────────────────────────────────────

@router.post("/{character_id}/portrait", response_model=CharacterOut)
async def upload_portrait(
    character_id: int,
    file: UploadFile = File(...),  # File(...) 表示这是必填的文件上传字段
    s: AsyncSession = Depends(get_session_dep),
):
    c = await s.get(Character, character_id)
    if c is None:
        raise HTTPException(404, "character not found")

    # 检查文件扩展名是否在白名单中
    name = file.filename or ""
    ext = Path(name).suffix.lower()  # 提取扩展名，转小写（.PNG → .png）
    if ext not in _ALLOWED_EXTS:
        raise HTTPException(400, f"unsupported file type: {ext}")

    # 读取文件内容到内存，检查大小
    data = await file.read()
    if len(data) > _MAX_BYTES:
        raise HTTPException(
            400, f"file too large: {len(data)} bytes (max {_MAX_BYTES})"
        )

    # 确保头像目录存在（parents=True = 自动创建父目录，exist_ok=True = 已存在不报错）
    portraits_dir = APP_DIR / "portraits"
    portraits_dir.mkdir(parents=True, exist_ok=True)

    # Remove any prior portrait for this character (different ext).
    # 删除该角色之前上传的头像（防止残留不同扩展名的旧文件）
    for old in portraits_dir.glob(f"{character_id}.*"):
        try:
            old.unlink()  # 删除旧文件
        except Exception:
            pass  # 删除失败不影响主流程

    # 将文件写入磁盘，文件名以 character_id 命名便于直接定位
    out_path = portraits_dir / f"{character_id}{ext}"
    out_path.write_bytes(data)

    # 更新数据库中的头像路径
    c.portrait_path = str(out_path)
    await s.commit()
    await s.refresh(c)
    return _serialize(c)


# ──────────────────────────────────────────────
# GET /characters/{character_id}/portrait — 获取头像文件
# ──────────────────────────────────────────────

@router.get("/{character_id}/portrait")
async def get_portrait(
    character_id: int, s: AsyncSession = Depends(get_session_dep),
):
    c = await s.get(Character, character_id)
    if c is None or not c.portrait_path:
        raise HTTPException(404, "no portrait")
    p = Path(c.portrait_path)
    if not p.exists():
        # 数据库里有路径记录，但实际文件不存在（可能被手动删除）
        raise HTTPException(404, "portrait file missing")
    # FileResponse 直接把磁盘文件作为 HTTP 响应体流式传输，
    # FastAPI 会自动设置正确的 Content-Type
    return FileResponse(str(p))


# ──────────────────────────────────────────────
# POST /characters/{character_id}/levelup — 角色升级
# ──────────────────────────────────────────────

@router.post("/{character_id}/levelup", response_model=CharacterOut)
async def levelup(
    character_id: int, body: dict,  # body 是自由格式 JSON 对象，包含 stat 字段
    s: AsyncSession = Depends(get_session_dep),
):
    """Advance Character.level by 1 and apply a stat bonus chosen by the player.

    HP and stamina get +5; everything else (sanity, 灵力, etc.) gets +1.
    Requires `xp >= xp_threshold(level)`. XP is left unchanged (it's
    treated as a cumulative running counter for v0.7).
    """
    c = await s.get(Character, character_id)
    if c is None:
        raise HTTPException(404, "character not found")

    # 检查经验值是否达到升级门槛
    threshold = _xp_threshold(c.level)
    if c.xp < threshold:
        raise HTTPException(400, f"not enough xp ({c.xp} < {threshold})")

    # 从请求体中取出玩家选择要提升的属性名
    stat = str(body.get("stat", "")).strip()
    if not stat:
        raise HTTPException(400, "stat required")

    # 解析当前角色属性（存为 JSON 字符串）
    try:
        stats = json.loads(c.base_stats_json or "{}")
    except json.JSONDecodeError:
        stats = {}
    if not isinstance(stats, dict):
        stats = {}

    # 根据属性类型决定加成量：hp/stamina 每次升级 +5，其余属性 +1
    bonus = 5 if stat in ("hp", "stamina") else 1
    current = stats.get(stat, 0)  # 当前属性值，不存在则默认 0
    try:
        current_int = int(current)  # 转为整数（防止属性值是字符串或浮点数）
    except (TypeError, ValueError):
        current_int = 0
    stats[stat] = current_int + bonus  # 应用加成

    # 把更新后的属性写回数据库（ensure_ascii=False 保证中文不被转义）
    c.base_stats_json = json.dumps(stats, ensure_ascii=False)
    c.level += 1  # 等级 +1
    await s.commit()
    await s.refresh(c)
    return _serialize(c)
