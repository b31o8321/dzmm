import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.api.schemas import ModelConfigIn, ModelConfigOut
from dzmm.db.models import ModelConfig
from dzmm.db.models import Session as SessionModel
from dzmm.models.factory import build_client
from dzmm.secrets import delete_api_key, store_api_key

router = APIRouter(prefix="/model_configs", tags=["models"])


def get_session_dep():
    raise RuntimeError("override")


def _to_out(m: ModelConfig) -> ModelConfigOut:
    return ModelConfigOut(
        id=m.id, name=m.name, type=m.type, base_url=m.base_url,
        model_name=m.model_name, api_key_ref=m.api_key_ref, timeout=m.timeout,
    )


@router.post("", response_model=ModelConfigOut)
async def create_model_config(body: ModelConfigIn, s: AsyncSession = Depends(get_session_dep)):
    api_key_ref = None
    if body.api_key:
        api_key_ref = f"{body.name}_{uuid.uuid4().hex[:8]}"
        store_api_key(api_key_ref, body.api_key)

    m = ModelConfig(
        name=body.name, type=body.type, base_url=body.base_url,
        model_name=body.model_name, api_key_ref=api_key_ref, timeout=body.timeout,
    )
    s.add(m)
    await s.commit()
    await s.refresh(m)
    return _to_out(m)


@router.get("", response_model=list[ModelConfigOut])
async def list_model_configs(s: AsyncSession = Depends(get_session_dep)):
    rows = (await s.execute(select(ModelConfig).order_by(ModelConfig.id))).scalars().all()
    return [_to_out(m) for m in rows]


@router.post("/{cfg_id}/test")
async def test_model_config(cfg_id: int, s: AsyncSession = Depends(get_session_dep)):
    cfg = await s.get(ModelConfig, cfg_id)
    if cfg is None:
        raise HTTPException(404, "config not found")
    client = build_client(cfg)
    ok, info = await client.health_check()
    return {"ok": ok, "info": info}


@router.put("/{cfg_id}", response_model=ModelConfigOut)
async def update_model_config(
    cfg_id: int, body: ModelConfigIn,
    s: AsyncSession = Depends(get_session_dep),
):
    m = await s.get(ModelConfig, cfg_id)
    if m is None:
        raise HTTPException(404, "config not found")
    m.name = body.name
    m.type = body.type
    m.base_url = body.base_url
    m.model_name = body.model_name
    m.timeout = body.timeout
    if body.api_key:
        if m.api_key_ref is None:
            m.api_key_ref = f"{body.name}_{uuid.uuid4().hex[:8]}"
        store_api_key(m.api_key_ref, body.api_key)
    await s.commit()
    await s.refresh(m)
    return _to_out(m)


@router.delete("/{cfg_id}", status_code=204)
async def delete_model_config(
    cfg_id: int, s: AsyncSession = Depends(get_session_dep),
):
    m = await s.get(ModelConfig, cfg_id)
    if m is None:
        raise HTTPException(404, "config not found")
    has_sessions = (
        await s.execute(
            select(SessionModel.id).where(
                (SessionModel.gm_model_config_id == cfg_id)
                | (SessionModel.summarizer_model_config_id == cfg_id)
            ).limit(1)
        )
    ).scalar_one_or_none()
    if has_sessions is not None:
        raise HTTPException(409, "model config in use by a session (该模型配置已被存档使用)")
    if m.api_key_ref:
        delete_api_key(m.api_key_ref)
    await s.delete(m)
    await s.commit()
