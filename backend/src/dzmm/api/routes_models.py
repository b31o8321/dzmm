# ============================================================
# routes_models.py — AI 模型配置（ModelConfig）的 REST API 路由
#
# 「模型配置」= 告诉系统如何连接某个 AI 服务，包括：
#   - 接口类型（Ollama 本地 / OpenAI 兼容 / 智谱等）
#   - 服务地址（URL）
#   - 要使用的具体模型名称
#   - API 密钥（敏感，加密存储）
#   - 并发限制等参数
#
# 每次跑团需要选择两个模型配置：
#   1. GM 模型（负责生成叙事）
#   2. 摘要器模型（负责压缩对话记忆）
# ============================================================

import uuid  # 用于生成唯一的 API 密钥引用 ID

# FastAPI 核心组件
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, update  # SQL 操作构建器
# update = 构建 SQL UPDATE 语句
from sqlalchemy.ext.asyncio import AsyncSession  # 异步数据库会话

from dzmm.api.schemas import ModelConfigIn, ModelConfigOut  # 请求/响应数据结构
from dzmm.db.models import ModelConfig              # 数据库模型配置 ORM
from dzmm.db.models import Session as SessionModel  # 数据库跑团存档 ORM
from dzmm.models.factory import build_client        # 根据配置构建 AI 客户端的工厂函数
from dzmm.secrets import delete_api_key, store_api_key  # API 密钥的安全存储/删除

# 创建路由组：所有路由的 URL 都以 /model_configs 开头
router = APIRouter(prefix="/model_configs", tags=["models"])


# 依赖注入占位函数（真正实现由 main.py 注入）
def get_session_dep():
    raise RuntimeError("override")


# _to_out：把数据库 ORM 对象转成 API 响应对象
# 注意：api_key 的真实值不暴露，只返回 api_key_ref（引用 ID）
# getattr(..., 0) 这种写法是为了兼容旧数据库记录（字段可能不存在）
def _to_out(m: ModelConfig) -> ModelConfigOut:
    return ModelConfigOut(
        id=m.id, name=m.name, type=m.type, base_url=m.base_url,
        model_name=m.model_name, api_key_ref=m.api_key_ref, timeout=m.timeout,
        # getattr 安全读取属性：如果 m 对象没有该属性，返回默认值 0
        max_concurrent=getattr(m, "max_concurrent", 0) or 0,
        is_default=bool(getattr(m, "is_default", False)),
    )


# ──────────────────────────────────────────────
# POST /model_configs — 创建新模型配置
# ──────────────────────────────────────────────

@router.post("", response_model=ModelConfigOut)
async def create_model_config(body: ModelConfigIn, s: AsyncSession = Depends(get_session_dep)):
    api_key_ref = None
    if body.api_key:
        # API 密钥不能明文存入数据库，改用「引用 ID」方案：
        # 生成唯一的引用名，把真实密钥存入系统密钥链（Keychain/Secret Service）
        # 数据库只存引用名，确保密钥泄露风险最小化
        api_key_ref = f"{body.name}_{uuid.uuid4().hex[:8]}"  # 如：本地Qwen_3a7f2c1b
        store_api_key(api_key_ref, body.api_key)              # 安全存储真实密钥

    m = ModelConfig(
        name=body.name, type=body.type, base_url=body.base_url,
        model_name=body.model_name, api_key_ref=api_key_ref, timeout=body.timeout,
        # max(0, ...) 确保并发数不会是负数
        max_concurrent=max(0, int(body.max_concurrent)),
    )
    s.add(m)
    await s.commit()
    await s.refresh(m)
    return _to_out(m)


# ──────────────────────────────────────────────
# GET /model_configs — 获取所有模型配置列表
# ──────────────────────────────────────────────

@router.get("", response_model=list[ModelConfigOut])
async def list_model_configs(s: AsyncSession = Depends(get_session_dep)):
    rows = (await s.execute(select(ModelConfig).order_by(ModelConfig.id))).scalars().all()
    return [_to_out(m) for m in rows]


# ──────────────────────────────────────────────
# POST /model_configs/{cfg_id}/test — 连通性测试
# ──────────────────────────────────────────────

@router.post("/{cfg_id}/test")
async def test_model_config(cfg_id: int, s: AsyncSession = Depends(get_session_dep)):
    cfg = await s.get(ModelConfig, cfg_id)
    if cfg is None:
        raise HTTPException(404, "config not found")
    # build_client 根据配置类型（ollama/openai等）构建对应的 AI 客户端实例
    client = build_client(cfg)
    # health_check 发送一个简单请求测试服务是否可达
    ok, info = await client.health_check()
    return {"ok": ok, "info": info}  # ok=True 表示连接成功


# 用于 RAG 嵌入的模型名（Ollama 专用）
_EMBED_MODEL = "nomic-embed-text"


# _model_base：去掉 Ollama 模型名中的版本标签
# 例如 "qwen2.5:7b" → "qwen2.5"（用于模糊匹配，不关心具体版本）
def _model_base(name: str) -> str:
    """Strip Ollama tag suffix, e.g. 'qwen2.5:7b' → 'qwen2.5'."""
    return name.split(":")[0].lower()


# _model_available：检查目标模型是否在已下载列表中（忽略版本标签）
def _model_available(target: str, available_list: list[str]) -> bool:
    """Check if target model (ignoring tag) is present in the available list."""
    target_base = _model_base(target)
    # any(...) = 列表中只要有一个满足条件就返回 True
    return bool(target_base) and any(_model_base(m) == target_base for m in available_list)


# ──────────────────────────────────────────────
# GET /model_configs/{cfg_id}/check — 检查模型是否已下载
# ──────────────────────────────────────────────

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
        # 非 Ollama 接口（如 OpenAI）不需要检查本地模型列表，
        # 只做连通性测试
        ok, _ = await client.health_check()
        return {"narrative_ok": ok, "embed_ok": None, "missing": []}

    try:
        # 向 Ollama 请求已下载的模型列表
        available = await client.list_models()
    except Exception:
        # 服务不可达，两个模型都标记为缺失
        return {"narrative_ok": False, "embed_ok": False, "missing": [cfg.model_name, _EMBED_MODEL]}

    # 检查叙事模型和嵌入模型是否都在本地
    narrative_ok = _model_available(cfg.model_name, available)
    embed_ok = _model_available(_EMBED_MODEL, available)

    # 收集需要 ollama pull 的模型名列表
    missing = []
    if not narrative_ok:
        missing.append(cfg.model_name)
    if not embed_ok:
        missing.append(_EMBED_MODEL)

    return {"narrative_ok": narrative_ok, "embed_ok": embed_ok, "missing": missing}


# ──────────────────────────────────────────────
# PUT /model_configs/{cfg_id} — 全量更新模型配置
# ──────────────────────────────────────────────

@router.put("/{cfg_id}", response_model=ModelConfigOut)
async def update_model_config(
    cfg_id: int, body: ModelConfigIn,
    s: AsyncSession = Depends(get_session_dep),
):
    m = await s.get(ModelConfig, cfg_id)
    if m is None:
        raise HTTPException(404, "config not found")
    # 逐字段覆盖
    m.name = body.name
    m.type = body.type
    m.base_url = body.base_url
    m.model_name = body.model_name
    m.timeout = body.timeout
    m.max_concurrent = max(0, int(body.max_concurrent))
    if body.api_key:
        # 如果提供了新密钥：
        if m.api_key_ref is None:
            # 之前没有密钥引用，现在创建一个新的
            m.api_key_ref = f"{body.name}_{uuid.uuid4().hex[:8]}"
        # 更新密钥链中的密钥（同一 ref 覆盖写入）
        store_api_key(m.api_key_ref, body.api_key)
    await s.commit()
    await s.refresh(m)
    return _to_out(m)


# ──────────────────────────────────────────────
# DELETE /model_configs/{cfg_id} — 删除模型配置
# ──────────────────────────────────────────────

@router.delete("/{cfg_id}", status_code=204)
async def delete_model_config(
    cfg_id: int, s: AsyncSession = Depends(get_session_dep),
):
    m = await s.get(ModelConfig, cfg_id)
    if m is None:
        raise HTTPException(404, "config not found")
    # 安全检查：该配置正在被存档使用时，不允许删除
    # （GM 模型或摘要器模型任一在用都要阻止）
    has_sessions = (
        await s.execute(
            select(SessionModel.id).where(
                # | 是 SQLAlchemy 的「OR」操作符
                (SessionModel.gm_model_config_id == cfg_id)
                | (SessionModel.summarizer_model_config_id == cfg_id)
            ).limit(1)
        )
    ).scalar_one_or_none()
    if has_sessions is not None:
        raise HTTPException(409, "model config in use by a session (该模型配置已被存档使用)")
    if m.api_key_ref:
        # 删除配置前，也要从系统密钥链中清除对应的 API 密钥，避免孤儿数据
        delete_api_key(m.api_key_ref)
    await s.delete(m)
    await s.commit()


# ──────────────────────────────────────────────
# POST /model_configs/{cfg_id}/default — 设为默认模型
# ──────────────────────────────────────────────

@router.post("/{cfg_id}/default", response_model=ModelConfigOut)
async def set_default_model_config(
    cfg_id: int, s: AsyncSession = Depends(get_session_dep),
):
    """把这条配置标为"默认模型"，同时把其余所有配置的 is_default 清零。

    Wizard / 一次性 LLM 调用（无 session 上下文）会优先使用这一条；这样用户
    在多个本地 + 远程模型间切换时，不用每次手动选。互斥保证：写入新默认前
    先 UPDATE ... SET is_default=0，再把目标这条置 1。
    """
    m = await s.get(ModelConfig, cfg_id)
    if m is None:
        raise HTTPException(404, "config not found")
    # 先把所有配置的 is_default 都设为 False（互斥：只能有一个默认）
    # update(ModelConfig).values(is_default=False) = SQL: UPDATE model_configs SET is_default=FALSE
    await s.execute(
        update(ModelConfig).values(is_default=False)
    )
    # 再把目标配置设为默认
    m.is_default = True
    await s.commit()
    await s.refresh(m)
    return _to_out(m)
