# ============================================================
# assets.py — 素材（Asset）路径解析 + 内置素材种子数据
# ============================================================
# 【什么是素材（Asset）？】
#   游戏里用到的图片（NPC 头像、场景图）和音频（背景音乐、音效）统称素材。
#   每个素材在数据库里有一行 Asset 记录，记录文件路径、MIME 类型、尺寸等。
#   AssetLink 是"素材-对象"关联表，例如把一张图片关联到某个 NPC 的 "avatar" 槽。
#
# 【素材来源（source 字段）】
#   - "builtin"：随应用打包的内置素材（存储在打包目录里）
#   - "http"：远程 URL（不在本地文件系统，直接用 URL 访问）
#   - 其他：用户上传的文件（存储在 APP_DIR/assets/ 目录下）
#
# 【内置素材种子（seed_builtin_assets）】
#   应用安装后首次启动时，把 manifest.json 里列出的内置素材批量写入数据库。
#   幂等：已存在的条目（通过 builtin_id 去重）不重复插入。
# ============================================================
from __future__ import annotations

import json
from pathlib import Path
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.db.models import Asset, AssetLink  # 数据库模型

# 以下两个全局变量在应用启动时（main.py）由 init_paths() 设置
_APP_DIR: Path | None = None      # 用户数据目录（如 ~/.dzmm/）
_BUILTIN_DIR: Path | None = None  # 内置素材目录（打包在应用里）


def init_paths(app_dir: Path, builtin_dir: Path) -> None:
    # 应用启动时调用一次，初始化路径并创建必要的子目录
    global _APP_DIR, _BUILTIN_DIR
    _APP_DIR = app_dir
    _BUILTIN_DIR = builtin_dir
    # 创建用户素材存储目录（图片和音频分开存放）
    (app_dir / "assets" / "image").mkdir(parents=True, exist_ok=True)
    (app_dir / "assets" / "audio").mkdir(parents=True, exist_ok=True)


def asset_storage_dir(kind: str) -> Path:
    # 返回指定类型素材的存储目录（kind 通常为 "image" 或 "audio"）
    assert _APP_DIR is not None, "init_paths() not called"
    return _APP_DIR / "assets" / kind


def resolve_asset_file(asset: Asset) -> Path | None:
    # 根据 Asset 的 source 字段，返回该素材在文件系统上的绝对路径
    # 若是 http 来源（远程 URL），返回 None（调用方应直接使用 URL）
    if asset.source == "http":
        return None  # 远程素材，没有本地路径
    if asset.source == "builtin":
        assert _BUILTIN_DIR is not None
        # 内置素材：路径相对于打包目录
        return _BUILTIN_DIR / asset.file_path
    # 用户上传的素材：file_path 直接是绝对路径
    return Path(asset.file_path)


async def seed_builtin_assets(session: AsyncSession) -> int:
    # 扫描内置素材清单（manifest.json），把尚未入库的素材插入 Asset 表
    # 返回本次新插入的条数，0 表示清单不存在或全部已入库（幂等）
    #
    # 【幂等设计】
    #   每个内置素材有唯一的 builtin_id（在 manifest.json 里定义），
    #   先读取数据库里现有的 builtin_id 集合，
    #   跳过已存在的条目，只插入新的。
    if _BUILTIN_DIR is None:
        return 0
    manifest_path = _BUILTIN_DIR / "manifest.json"
    if not manifest_path.exists():
        return 0  # 清单文件不存在（可能是精简版安装），跳过
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0  # 清单读取或解析失败，跳过

    # 读取数据库里已有的 builtin_id 集合（避免重复插入）
    existing_ids: set[str] = set()
    rows = (await session.execute(select(Asset).where(Asset.source == "builtin"))).scalars().all()
    for r in rows:
        try:
            bid = json.loads(r.tag_json).get("builtin_id")  # tag_json 里存了 builtin_id
            if bid:
                existing_ids.add(bid)
        except (TypeError, ValueError):
            continue

    inserted = 0
    for entry in manifest.get("assets", []):
        bid = entry.get("builtin_id")
        if not bid or bid in existing_ids:
            continue  # 没有 builtin_id 或已存在，跳过
        # 按清单数据构造 Asset 行
        a = Asset(
            kind=entry.get("kind", "image"),              # 素材类型：image/audio
            source="builtin",                              # 来源标记
            file_path=entry.get("file", ""),               # 相对于 builtin_dir 的路径
            mime=entry.get("mime", ""),                    # MIME 类型（如 image/png）
            width=entry.get("width", 0),                   # 图片宽度（像素）
            height=entry.get("height", 0),                 # 图片高度
            duration_ms=entry.get("duration_ms", 0),       # 音频时长（毫秒）
            tag_json=json.dumps(
                {**entry.get("tag", {}), "builtin_id": bid},  # 把 builtin_id 也存进 tag_json
                ensure_ascii=False,
            ),
            title=entry.get("title", bid),                 # 显示名称，默认用 builtin_id
            uploaded_by="builtin",                         # 标记为内置，非用户上传
        )
        session.add(a)
        inserted += 1
    if inserted:
        await session.commit()  # 有新行才提交
    return inserted


async def attach_asset(
    session: AsyncSession,
    asset_id: int,         # 要关联的素材 ID
    owner_type: str,       # 拥有者类型（如 "npc"、"session"）
    owner_id: int,         # 拥有者 ID
    slot: str,             # 槽位名称（如 "avatar"、"background"）
    extra: dict | None = None,  # 额外数据（如角色扮演场景 ID）
    *,
    replace: bool = True,  # 是否替换已有的同槽位关联（默认替换）
) -> None:
    # 创建或替换一个 AssetLink（素材关联记录）
    #
    # 【AssetLink 的作用】
    #   AssetLink 把"素材"和"游戏对象"关联起来，而不是在对象里直接存文件路径。
    #   这样一个素材可以被多个对象引用，对象也可以随时换素材，
    #   而不需要修改素材文件本身。
    #
    # 【replace 参数】
    #   同一个对象同一个槽位，通常只有一个有效的素材关联。
    #   replace=True（默认）：先删除旧的再建新的，保证一槽一素材。
    extra_json = json.dumps(extra or {}, ensure_ascii=False)
    if replace:
        # 找到相同的 (owner_type, owner_id, slot, extra_json) 的旧关联
        existing = (await session.execute(
            select(AssetLink).where(
                AssetLink.owner_type == owner_type,
                AssetLink.owner_id == owner_id,
                AssetLink.slot == slot,
                AssetLink.extra_json == extra_json,
            )
        )).scalars().all()
        for link in existing:
            await session.delete(link)  # 删除旧关联
    # 创建新的 AssetLink 行
    session.add(AssetLink(
        asset_id=asset_id, owner_type=owner_type, owner_id=owner_id,
        slot=slot, extra_json=extra_json,
    ))


async def get_attached_assets(
    session: AsyncSession,
    owner_type: str,        # 拥有者类型
    owner_id: int,          # 拥有者 ID
    slot: str | None = None,  # 若指定，只返回这个槽位的素材；否则返回所有槽位
) -> list[tuple[AssetLink, Asset]]:
    # 查询某个对象关联的素材，返回 (AssetLink行, Asset行) 的列表
    #
    # 用 JOIN 一次性查出两张表的数据，避免 N+1 查询
    stmt = select(AssetLink, Asset).join(Asset, AssetLink.asset_id == Asset.id).where(
        AssetLink.owner_type == owner_type,
        AssetLink.owner_id == owner_id,
    )
    if slot is not None:
        stmt = stmt.where(AssetLink.slot == slot)  # 按槽位过滤
    rows = (await session.execute(stmt)).all()
    return [(link, asset) for (link, asset) in rows]
