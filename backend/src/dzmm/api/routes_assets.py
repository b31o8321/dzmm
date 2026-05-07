"""Assets API: list / upload / serve / delete / attach / list-by-owner."""
import json
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.api.routes_sessions._common import get_session_dep
from dzmm.db.models import Asset, AssetLink
from dzmm.service.assets import (
    asset_storage_dir,
    attach_asset,
    get_attached_assets,
    resolve_asset_file,
)

router = APIRouter(prefix="/assets", tags=["assets"])

_ALLOWED_IMAGE_MIMES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
_ALLOWED_AUDIO_MIMES = {
    "audio/mpeg", "audio/mp3", "audio/wav",
    "audio/ogg", "audio/x-m4a", "audio/mp4",
}
_MAX_UPLOAD_SIZE = 25 * 1024 * 1024  # 25MB


def _asset_dict(a: Asset) -> dict:
    return {
        "id": a.id, "kind": a.kind, "source": a.source,
        "mime": a.mime, "width": a.width, "height": a.height,
        "duration_ms": a.duration_ms,
        "tag": json.loads(a.tag_json or "{}"),
        "title": a.title, "uploaded_by": a.uploaded_by,
        "url": f"/assets/{a.id}/file",
        "created_at": a.created_at.isoformat() if a.created_at else None,
    }


@router.get("")
async def list_assets(
    kind: str | None = None,
    category: str | None = None,
    source: str | None = None,
    s: AsyncSession = Depends(get_session_dep),
):
    """Filter by kind (image/audio), tag.category (npc_avatar/scene/bgm/...), source."""
    stmt = select(Asset)
    if kind:
        stmt = stmt.where(Asset.kind == kind)
    if source:
        stmt = stmt.where(Asset.source == source)
    rows = (await s.execute(stmt.order_by(Asset.id.desc()))).scalars().all()
    out = [_asset_dict(a) for a in rows]
    if category:
        out = [a for a in out if a["tag"].get("category") == category]
    return out


@router.post("/upload")
async def upload_asset(
    file: UploadFile = File(...),
    kind: str = Form("image"),
    category: str = Form(""),
    title: str = Form(""),
    s: AsyncSession = Depends(get_session_dep),
):
    if kind == "image" and file.content_type not in _ALLOWED_IMAGE_MIMES:
        raise HTTPException(415, f"image MIME {file.content_type} not allowed")
    if kind == "audio" and file.content_type not in _ALLOWED_AUDIO_MIMES:
        raise HTTPException(415, f"audio MIME {file.content_type} not allowed")

    contents = await file.read()
    if len(contents) > _MAX_UPLOAD_SIZE:
        raise HTTPException(413, f"file too large (max {_MAX_UPLOAD_SIZE} bytes)")

    ext_default = {
        "image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp",
        "image/gif": ".gif", "audio/mpeg": ".mp3", "audio/wav": ".wav",
        "audio/ogg": ".ogg",
    }.get(file.content_type or "", "")
    ext = Path(file.filename or "").suffix.lower() or ext_default
    fname = f"{uuid.uuid4().hex}{ext}"
    target = asset_storage_dir(kind) / fname
    target.write_bytes(contents)

    a = Asset(
        kind=kind, source="local", file_path=str(target),
        mime=file.content_type or "", title=title or file.filename or fname,
        tag_json=json.dumps({"category": category} if category else {}, ensure_ascii=False),
        uploaded_by="user",
    )
    s.add(a)
    await s.commit()
    await s.refresh(a)
    return _asset_dict(a)


@router.get("/{asset_id}/file")
async def get_asset_file(asset_id: int, s: AsyncSession = Depends(get_session_dep)):
    a = await s.get(Asset, asset_id)
    if a is None:
        raise HTTPException(404, "asset not found")
    if a.source == "http":
        raise HTTPException(302, "external asset; use asset.url directly")
    path = resolve_asset_file(a)
    if path is None or not path.exists():
        raise HTTPException(404, "file missing")
    return FileResponse(path, media_type=a.mime or "application/octet-stream")


@router.delete("/{asset_id}", status_code=204)
async def delete_asset(asset_id: int, s: AsyncSession = Depends(get_session_dep)):
    a = await s.get(Asset, asset_id)
    if a is None:
        return
    if a.source == "builtin":
        raise HTTPException(403, "cannot delete builtin asset")
    links = (await s.execute(select(AssetLink).where(AssetLink.asset_id == asset_id))).scalars().all()
    for link in links:
        await s.delete(link)
    if a.file_path:
        try:
            Path(a.file_path).unlink(missing_ok=True)
        except OSError:
            pass
    await s.delete(a)
    await s.commit()


@router.post("/{asset_id}/attach")
async def attach(
    asset_id: int,
    payload: dict,
    s: AsyncSession = Depends(get_session_dep),
):
    """Body: { owner_type, owner_id, slot, extra?: {} }"""
    a = await s.get(Asset, asset_id)
    if a is None:
        raise HTTPException(404, "asset not found")
    try:
        owner_type = str(payload["owner_type"])
        owner_id = int(payload["owner_id"])
        slot = str(payload["slot"])
    except (KeyError, ValueError, TypeError) as e:
        raise HTTPException(400, f"missing/invalid field: {e}")
    extra = payload.get("extra")
    if extra is not None and not isinstance(extra, dict):
        raise HTTPException(400, "extra must be an object")
    await attach_asset(s, asset_id, owner_type, owner_id, slot, extra)
    await s.commit()
    return {"ok": True}


@router.get("/by_owner/{owner_type}/{owner_id}")
async def list_by_owner(
    owner_type: str,
    owner_id: int,
    slot: str | None = None,
    s: AsyncSession = Depends(get_session_dep),
):
    pairs = await get_attached_assets(s, owner_type, owner_id, slot)
    return [
        {
            "slot": link.slot,
            "extra": json.loads(link.extra_json or "{}"),
            "asset": _asset_dict(asset),
        }
        for (link, asset) in pairs
    ]
