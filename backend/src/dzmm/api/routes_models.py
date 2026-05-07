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
        max_concurrent=getattr(m, "max_concurrent", 0) or 0,
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
        max_concurrent=max(0, int(body.max_concurrent)),
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


_EMBED_MODEL = "nomic-embed-text"


def _model_base(name: str) -> str:
    """Strip Ollama tag suffix, e.g. 'qwen2.5:7b' → 'qwen2.5'."""
    return name.split(":")[0].lower()


def _model_available(target: str, available_list: list[str]) -> bool:
    """Check if target model (ignoring tag) is present in the available list."""
    target_base = _model_base(target)
    return bool(target_base) and any(_model_base(m) == target_base for m in available_list)


@router.get("/{cfg_id}/check")
async def check_model_config(cfg_id: int, s: AsyncSession = Depends(get_session_dep)):
    """Check if the configured model (and nomic-embed-text for RAG) are available in Ollama.

    Returns:
      narrative_ok: whether the narrative model is in Ollama's model list
      embed_ok: whether nomic-embed-text is available (None for non-Ollama configs)
      missing: list of model names that need to be pulled
    """
    cfg = await s.get(ModelConfig, cfg_id)
    if cfg is None:
        raise HTTPException(404, "config not found")
    client = build_client(cfg)

    if cfg.type != "ollama":
        ok, _ = await client.health_check()
        return {"narrative_ok": ok, "embed_ok": None, "missing": []}

    try:
        available = await client.list_models()
    except Exception:
        return {"narrative_ok": False, "embed_ok": False, "missing": [cfg.model_name, _EMBED_MODEL]}

    narrative_ok = _model_available(cfg.model_name, available)
    embed_ok = _model_available(_EMBED_MODEL, available)

    missing = []
    if not narrative_ok:
        missing.append(cfg.model_name)
    if not embed_ok:
        missing.append(_EMBED_MODEL)

    return {"narrative_ok": narrative_ok, "embed_ok": embed_ok, "missing": missing}


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
    m.max_concurrent = max(0, int(body.max_concurrent))
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
