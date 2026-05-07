"""Asset path resolution + builtin seeding."""
from __future__ import annotations

import json
from pathlib import Path
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.db.models import Asset, AssetLink

# Resolved at startup from main.py
_APP_DIR: Path | None = None
_BUILTIN_DIR: Path | None = None


def init_paths(app_dir: Path, builtin_dir: Path) -> None:
    global _APP_DIR, _BUILTIN_DIR
    _APP_DIR = app_dir
    _BUILTIN_DIR = builtin_dir
    (app_dir / "assets" / "image").mkdir(parents=True, exist_ok=True)
    (app_dir / "assets" / "audio").mkdir(parents=True, exist_ok=True)


def asset_storage_dir(kind: str) -> Path:
    assert _APP_DIR is not None, "init_paths() not called"
    return _APP_DIR / "assets" / kind


def resolve_asset_file(asset: Asset) -> Path | None:
    """Return absolute filesystem path for serving, or None for http-source."""
    if asset.source == "http":
        return None
    if asset.source == "builtin":
        assert _BUILTIN_DIR is not None
        return _BUILTIN_DIR / asset.file_path
    return Path(asset.file_path)


async def seed_builtin_assets(session: AsyncSession) -> int:
    """Idempotent: scan packaging/assets/builtin/manifest.json, insert any
    Asset rows whose tag_json.builtin_id is not already present. Returns
    count of newly inserted rows. Returns 0 if manifest missing/empty."""
    if _BUILTIN_DIR is None:
        return 0
    manifest_path = _BUILTIN_DIR / "manifest.json"
    if not manifest_path.exists():
        return 0
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0

    existing_ids: set[str] = set()
    rows = (await session.execute(select(Asset).where(Asset.source == "builtin"))).scalars().all()
    for r in rows:
        try:
            bid = json.loads(r.tag_json).get("builtin_id")
            if bid:
                existing_ids.add(bid)
        except (TypeError, ValueError):
            continue

    inserted = 0
    for entry in manifest.get("assets", []):
        bid = entry.get("builtin_id")
        if not bid or bid in existing_ids:
            continue
        a = Asset(
            kind=entry.get("kind", "image"),
            source="builtin",
            file_path=entry.get("file", ""),
            mime=entry.get("mime", ""),
            width=entry.get("width", 0),
            height=entry.get("height", 0),
            duration_ms=entry.get("duration_ms", 0),
            tag_json=json.dumps(
                {**entry.get("tag", {}), "builtin_id": bid},
                ensure_ascii=False,
            ),
            title=entry.get("title", bid),
            uploaded_by="builtin",
        )
        session.add(a)
        inserted += 1
    if inserted:
        await session.commit()
    return inserted


async def attach_asset(
    session: AsyncSession,
    asset_id: int,
    owner_type: str,
    owner_id: int,
    slot: str,
    extra: dict | None = None,
    *,
    replace: bool = True,
) -> None:
    """Create / replace an AssetLink. If replace=True (default), removes any
    existing link with the same (owner_type, owner_id, slot, extra_json)."""
    extra_json = json.dumps(extra or {}, ensure_ascii=False)
    if replace:
        existing = (await session.execute(
            select(AssetLink).where(
                AssetLink.owner_type == owner_type,
                AssetLink.owner_id == owner_id,
                AssetLink.slot == slot,
                AssetLink.extra_json == extra_json,
            )
        )).scalars().all()
        for link in existing:
            await session.delete(link)
    session.add(AssetLink(
        asset_id=asset_id, owner_type=owner_type, owner_id=owner_id,
        slot=slot, extra_json=extra_json,
    ))


async def get_attached_assets(
    session: AsyncSession,
    owner_type: str,
    owner_id: int,
    slot: str | None = None,
) -> list[tuple[AssetLink, Asset]]:
    stmt = select(AssetLink, Asset).join(Asset, AssetLink.asset_id == Asset.id).where(
        AssetLink.owner_type == owner_type,
        AssetLink.owner_id == owner_id,
    )
    if slot is not None:
        stmt = stmt.where(AssetLink.slot == slot)
    rows = (await session.execute(stmt)).all()
    return [(link, asset) for (link, asset) in rows]
