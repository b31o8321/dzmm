from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.api.schemas import CharacterIn, CharacterOut
from dzmm.config import APP_DIR
from dzmm.db.models import Character
from dzmm.db.models import Session as SessionModel

router = APIRouter(prefix="/characters", tags=["characters"])

_ALLOWED_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".svg", ".gif"}
_MAX_BYTES = 5 * 1024 * 1024  # 5 MB


def get_session_dep():
    raise RuntimeError("override")


def _to_out(c: Character) -> CharacterOut:
    return CharacterOut(
        id=c.id,
        world_id=c.world_id,
        name=c.name,
        profile_md=c.profile_md,
        base_stats_json=c.base_stats_json,
        portrait_path=c.portrait_path or "",
    )


@router.post("", response_model=CharacterOut)
async def create_character(body: CharacterIn, s: AsyncSession = Depends(get_session_dep)):
    c = Character(**body.model_dump())
    s.add(c)
    await s.commit()
    await s.refresh(c)
    return _to_out(c)


@router.get("", response_model=list[CharacterOut])
async def list_characters(world_id: int | None = None,
                          s: AsyncSession = Depends(get_session_dep)):
    q = select(Character).order_by(Character.id)
    if world_id is not None:
        q = q.where(Character.world_id == world_id)
    rows = (await s.execute(q)).scalars().all()
    return [_to_out(c) for c in rows]


@router.get("/{character_id}", response_model=CharacterOut)
async def get_character(character_id: int, s: AsyncSession = Depends(get_session_dep)):
    c = await s.get(Character, character_id)
    if c is None:
        raise HTTPException(404, "character not found")
    return _to_out(c)


@router.put("/{character_id}", response_model=CharacterOut)
async def update_character(
    character_id: int, body: CharacterIn,
    s: AsyncSession = Depends(get_session_dep),
):
    c = await s.get(Character, character_id)
    if c is None:
        raise HTTPException(404, "character not found")
    c.world_id = body.world_id
    c.name = body.name
    c.profile_md = body.profile_md
    c.base_stats_json = body.base_stats_json
    await s.commit()
    await s.refresh(c)
    return _to_out(c)


@router.delete("/{character_id}", status_code=204)
async def delete_character(
    character_id: int, s: AsyncSession = Depends(get_session_dep),
):
    c = await s.get(Character, character_id)
    if c is None:
        raise HTTPException(404, "character not found")
    has_sessions = (
        await s.execute(
            select(SessionModel.id).where(SessionModel.character_id == character_id).limit(1)
        )
    ).scalar_one_or_none()
    if has_sessions is not None:
        raise HTTPException(409, "character has sessions (该角色仍有跑团存档)")
    await s.delete(c)
    await s.commit()


@router.post("/{character_id}/portrait", response_model=CharacterOut)
async def upload_portrait(
    character_id: int,
    file: UploadFile = File(...),
    s: AsyncSession = Depends(get_session_dep),
):
    c = await s.get(Character, character_id)
    if c is None:
        raise HTTPException(404, "character not found")

    name = file.filename or ""
    ext = Path(name).suffix.lower()
    if ext not in _ALLOWED_EXTS:
        raise HTTPException(400, f"unsupported file type: {ext}")

    data = await file.read()
    if len(data) > _MAX_BYTES:
        raise HTTPException(
            400, f"file too large: {len(data)} bytes (max {_MAX_BYTES})"
        )

    portraits_dir = APP_DIR / "portraits"
    portraits_dir.mkdir(parents=True, exist_ok=True)

    # Remove any prior portrait for this character (different ext).
    for old in portraits_dir.glob(f"{character_id}.*"):
        try:
            old.unlink()
        except Exception:
            pass

    out_path = portraits_dir / f"{character_id}{ext}"
    out_path.write_bytes(data)

    c.portrait_path = str(out_path)
    await s.commit()
    await s.refresh(c)
    return _to_out(c)


@router.get("/{character_id}/portrait")
async def get_portrait(
    character_id: int, s: AsyncSession = Depends(get_session_dep),
):
    c = await s.get(Character, character_id)
    if c is None or not c.portrait_path:
        raise HTTPException(404, "no portrait")
    p = Path(c.portrait_path)
    if not p.exists():
        raise HTTPException(404, "portrait file missing")
    return FileResponse(str(p))
