"""Assets API: list / upload / serve / delete / attach / list-by-owner."""
# ============================================================
# routes_assets.py — 素材库（Asset）的 REST API 路由
#
# 「Asset（素材）」= 跑团中使用的多媒体文件，目前支持：
#   - image（图片）：NPC 头像、场景插图等
#   - audio（音频）：背景音乐（BGM）、音效等
#
# 素材与游戏对象的关联通过「AssetLink（附件关系）」实现：
#   例如：NPC #5 的头像 = 素材 #12 挂载在 slot "avatar" 上
#
# 接口列表：
#   GET    /assets                      — 列出所有素材（支持过滤）
#   POST   /assets/upload               — 上传新素材
#   GET    /assets/{id}/file            — 获取素材文件内容
#   DELETE /assets/{id}                 — 删除素材
#   POST   /assets/{id}/attach          — 把素材挂载到某个对象
#   GET    /assets/by_owner/{type}/{id} — 列出某对象的所有挂载素材
# ============================================================

import json    # 用于序列化/反序列化 tag_json 字段
import uuid    # 用于生成唯一文件名（防止同名文件覆盖）
from pathlib import Path  # 跨平台文件路径操作

# FastAPI 核心组件
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
# Form      = 声明表单字段（上传文件时通常同时用 Form 传元数据）
# File      = 声明文件上传参数
# UploadFile = 上传的文件对象

from fastapi.responses import FileResponse  # 返回文件内容的特殊响应
from sqlalchemy import select               # SQL 查询构建器
from sqlalchemy.ext.asyncio import AsyncSession  # 异步数据库会话

# 注意：这里复用 sessions 路由的依赖注入
from dzmm.api.routes_sessions._common import get_session_dep
from dzmm.db.models import Asset, AssetLink  # 数据库素材 ORM 模型
from dzmm.service.assets import (
    asset_storage_dir,   # 获取素材存储目录的工具函数
    attach_asset,        # 将素材挂载到对象的服务函数
    get_attached_assets, # 查询对象上所有挂载素材的服务函数
    resolve_asset_file,  # 解析素材实际文件路径的工具函数
)

# 创建路由组：所有路由的 URL 都以 /assets 开头
router = APIRouter(prefix="/assets", tags=["assets"])

# 允许上传的图片 MIME 类型白名单（MIME = 文件格式标识）
_ALLOWED_IMAGE_MIMES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
# 允许上传的音频 MIME 类型白名单
_ALLOWED_AUDIO_MIMES = {
    "audio/mpeg", "audio/mp3", "audio/wav",
    "audio/ogg", "audio/x-m4a", "audio/mp4",
}
# 单次上传文件大小上限：25 MB
_MAX_UPLOAD_SIZE = 25 * 1024 * 1024  # 25MB


# _asset_dict：把数据库 ORM 对象（Asset）转成 Python 字典返回
# url 字段统一指向文件内容获取接口，前端直接用这个 URL 显示图片/播放音频
def _asset_dict(a: Asset) -> dict:
    return {
        "id": a.id,
        "kind": a.kind,          # 类型：image / audio
        "source": a.source,      # 来源：local（本地上传）/ http（外链）/ builtin（内置）
        "mime": a.mime,          # MIME 类型，如 image/png
        "width": a.width,        # 图片宽度（像素），非图片为 None
        "height": a.height,      # 图片高度（像素）
        "duration_ms": a.duration_ms,  # 音频时长（毫秒），非音频为 None
        "tag": json.loads(a.tag_json or "{}"),  # 标签字典，如 {"category": "npc_avatar"}
        "title": a.title,        # 素材标题/文件名
        "uploaded_by": a.uploaded_by,  # 上传者标识
        "url": f"/assets/{a.id}/file", # 访问文件内容的 API URL
        "created_at": a.created_at.isoformat() if a.created_at else None,  # 上传时间
    }


# ──────────────────────────────────────────────
# GET /assets — 获取素材列表（支持多维过滤）
# ──────────────────────────────────────────────

@router.get("")
async def list_assets(
    kind: str | None = None,       # URL 查询参数：?kind=image 或 ?kind=audio
    category: str | None = None,   # ?category=npc_avatar / scene / bgm 等
    source: str | None = None,     # ?source=local 或 ?source=builtin
    s: AsyncSession = Depends(get_session_dep),
):
    """Filter by kind (image/audio), tag.category (npc_avatar/scene/bgm/...), source."""
    # 构建基础查询
    stmt = select(Asset)
    # 动态追加过滤条件（只有提供了参数才过滤）
    if kind:
        stmt = stmt.where(Asset.kind == kind)
    if source:
        stmt = stmt.where(Asset.source == source)
    # 按 id 倒序（最新上传的排在前面）
    rows = (await s.execute(stmt.order_by(Asset.id.desc()))).scalars().all()
    out = [_asset_dict(a) for a in rows]
    if category:
        # category 存在 tag_json 里，无法直接用 SQL WHERE 过滤（JSON 字段），
        # 所以在 Python 层做二次过滤（数据量不大时可接受）
        out = [a for a in out if a["tag"].get("category") == category]
    return out


# ──────────────────────────────────────────────
# POST /assets/upload — 上传新素材
# ──────────────────────────────────────────────

@router.post("/upload")
async def upload_asset(
    file: UploadFile = File(...),    # 必填：上传的文件
    kind: str = Form("image"),       # 表单字段：素材类型，默认 image
    category: str = Form(""),        # 表单字段：分类标签，如 npc_avatar
    title: str = Form(""),           # 表单字段：自定义标题（可选）
    s: AsyncSession = Depends(get_session_dep),
):
    # 根据 kind 校验 MIME 类型（防止上传不支持的格式）
    if kind == "image" and file.content_type not in _ALLOWED_IMAGE_MIMES:
        raise HTTPException(415, f"image MIME {file.content_type} not allowed")
        # 415 Unsupported Media Type = 不支持的媒体格式
    if kind == "audio" and file.content_type not in _ALLOWED_AUDIO_MIMES:
        raise HTTPException(415, f"audio MIME {file.content_type} not allowed")

    # 读取文件内容到内存，检查大小
    contents = await file.read()
    if len(contents) > _MAX_UPLOAD_SIZE:
        raise HTTPException(413, f"file too large (max {_MAX_UPLOAD_SIZE} bytes)")
        # 413 Request Entity Too Large = 文件过大

    # 根据 MIME 类型确定默认扩展名（如果上传的文件名没有扩展名则用这个）
    ext_default = {
        "image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp",
        "image/gif": ".gif", "audio/mpeg": ".mp3", "audio/wav": ".wav",
        "audio/ogg": ".ogg",
    }.get(file.content_type or "", "")
    # 优先用文件名中的扩展名，没有则用根据 MIME 推断的默认值
    ext = Path(file.filename or "").suffix.lower() or ext_default
    # 用 UUID 生成唯一文件名，防止同名文件互相覆盖（如两个 "avatar.png"）
    fname = f"{uuid.uuid4().hex}{ext}"
    # asset_storage_dir(kind) 返回对应类型的存储目录（如 .../assets/images/）
    target = asset_storage_dir(kind) / fname
    target.write_bytes(contents)  # 把文件内容写入磁盘

    # 创建数据库记录
    a = Asset(
        kind=kind, source="local", file_path=str(target),
        mime=file.content_type or "",
        # 标题：优先用用户填写的，其次用原始文件名，最后用生成的 UUID 文件名
        title=title or file.filename or fname,
        # tag_json 存分类信息；ensure_ascii=False 保证中文不被转义
        tag_json=json.dumps({"category": category} if category else {}, ensure_ascii=False),
        uploaded_by="user",  # 目前固定为 "user"，后续可扩展为账户 ID
    )
    s.add(a)
    await s.commit()
    await s.refresh(a)
    return _asset_dict(a)


# ──────────────────────────────────────────────
# GET /assets/{asset_id}/file — 获取素材文件内容
# ──────────────────────────────────────────────

@router.get("/{asset_id}/file")
async def get_asset_file(asset_id: int, s: AsyncSession = Depends(get_session_dep)):
    a = await s.get(Asset, asset_id)
    if a is None:
        raise HTTPException(404, "asset not found")
    if a.source == "http":
        # 外链素材不走服务器中转，让前端直接用原始 URL 访问
        raise HTTPException(302, "external asset; use asset.url directly")
    # resolve_asset_file 处理不同 source 类型的路径解析逻辑
    path = resolve_asset_file(a)
    if path is None or not path.exists():
        raise HTTPException(404, "file missing")
    # FileResponse 流式传输文件，自动设置 Content-Type 响应头
    return FileResponse(path, media_type=a.mime or "application/octet-stream")


# ──────────────────────────────────────────────
# DELETE /assets/{asset_id} — 删除素材
# ──────────────────────────────────────────────

@router.delete("/{asset_id}", status_code=204)
async def delete_asset(asset_id: int, s: AsyncSession = Depends(get_session_dep)):
    a = await s.get(Asset, asset_id)
    if a is None:
        return  # 素材不存在视为已删除，直接返回成功（幂等操作）
    if a.source == "builtin":
        # 内置素材是系统预置的，不允许用户删除
        raise HTTPException(403, "cannot delete builtin asset")
        # 403 Forbidden = 无权执行此操作
    # 先删除所有「附件关系」记录（外键约束要求先删子表）
    links = (await s.execute(select(AssetLink).where(AssetLink.asset_id == asset_id))).scalars().all()
    for link in links:
        await s.delete(link)
    # 再删除磁盘上的实际文件（本地素材才有文件路径）
    if a.file_path:
        try:
            # missing_ok=True = 文件不存在时不报错（可能已被手动删除）
            Path(a.file_path).unlink(missing_ok=True)
        except OSError:
            pass  # 删除失败忽略（如权限问题），不阻塞数据库记录的删除
    # 最后删除数据库记录
    await s.delete(a)
    await s.commit()


# ──────────────────────────────────────────────
# POST /assets/{asset_id}/attach — 将素材挂载到某个对象
# ──────────────────────────────────────────────

@router.post("/{asset_id}/attach")
async def attach(
    asset_id: int,
    payload: dict,  # 请求体为自由格式 JSON 对象
    s: AsyncSession = Depends(get_session_dep),
):
    """Body: { owner_type, owner_id, slot, extra?: {} }"""
    # 「挂载」= 建立素材与游戏对象之间的关联，例如：
    #   素材 #12（一张头像图）挂载到 NPC #5 的 "avatar" 插槽
    #   素材 #33（BGM）挂载到 Session #2 的 "bgm" 插槽
    a = await s.get(Asset, asset_id)
    if a is None:
        raise HTTPException(404, "asset not found")
    try:
        # 从请求体中提取必填字段
        owner_type = str(payload["owner_type"])  # 宿主类型：npc / session / character 等
        owner_id = int(payload["owner_id"])       # 宿主对象的 ID
        slot = str(payload["slot"])               # 插槽名：avatar / bgm / scene 等
    except (KeyError, ValueError, TypeError) as e:
        raise HTTPException(400, f"missing/invalid field: {e}")
    # extra 是可选的附加元数据（如图片的裁剪参数）
    extra = payload.get("extra")
    if extra is not None and not isinstance(extra, dict):
        raise HTTPException(400, "extra must be an object")
    # 调用服务层函数创建 AssetLink 关联记录
    await attach_asset(s, asset_id, owner_type, owner_id, slot, extra)
    await s.commit()
    return {"ok": True}


# ──────────────────────────────────────────────
# GET /assets/by_owner/{owner_type}/{owner_id} — 查询对象的所有挂载素材
# ──────────────────────────────────────────────

@router.get("/by_owner/{owner_type}/{owner_id}")
async def list_by_owner(
    owner_type: str,          # 宿主类型（路径参数）
    owner_id: int,            # 宿主 ID（路径参数）
    slot: str | None = None,  # 可选：只查某个插槽，?slot=avatar
    s: AsyncSession = Depends(get_session_dep),
):
    # get_attached_assets 查询该对象上所有挂载的素材，返回 (AssetLink, Asset) 元组列表
    pairs = await get_attached_assets(s, owner_type, owner_id, slot)
    # 把每对 (link, asset) 组合成前端友好的字典格式
    return [
        {
            "slot": link.slot,   # 插槽名（该素材挂在哪个位置）
            "extra": json.loads(link.extra_json or "{}"),  # 附加元数据
            "asset": _asset_dict(asset),  # 完整的素材信息
        }
        for (link, asset) in pairs
    ]
