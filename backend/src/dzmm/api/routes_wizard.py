# ============================================================
# routes_wizard.py — 向导（Wizard）API 路由
# ============================================================
#
# 【什么是"向导"？】
#   在这个跑团系统里，"向导"是一个分步骤引导玩家建档的流程：
#   第 1 步生成世界简介 → 第 2 步扩展世界细节 → 第 3 步创建角色
#   → 第 4 步生成 NPC → 第 5 步生成剧本大纲 → 第 6 步写入数据库
#
# 【为什么要分步骤？】
#   每一步都要调用大语言模型（LLM），单次调用可能耗时数秒到数分钟。
#   分步可以让前端在每步完成后立即展示结果，用户可以调整或重试某一步，
#   而不必等全部生成完再一次性呈现。
#
# 【什么是 SSE 流式响应？】
#   SSE = Server-Sent Events（服务器推送事件）。
#   普通 HTTP 请求是「客户端发请求 → 等待 → 服务器一次性返回全部结果」。
#   SSE 是「客户端发请求 → 服务器边生成边推送片段 → 客户端逐字显示」，
#   就像打字机一样实时显示 LLM 的输出，用户体验更好。
#   本文件末尾的 /stream 系列接口就是 SSE 接口。
#
# 【文件结构】
#   - _client_for: 根据 model_config_id 构建 LLM 客户端
#   - _require_int: 从 payload 中安全提取整数参数
#   - /world_brief、/world_details、/character、/npcs、/screenplay: 普通（阻塞）生成接口
#   - /npc/single: 单个 NPC 生成接口
#   - _sse + /*/stream: 流式（SSE）生成接口
#   - /suggest_archetypes、/suggest_npcs、/refine_theme、/suggest: 辅助建议接口
#   - /finalize: 旧版向导最终写入数据库（已废弃）
#   - /fw/*: 开放世界框架向导（新版）

"""v0.2.0 wizard endpoints — POST /wizard/{world_brief, world_details,
character, npcs, screenplay, finalize}.

Each step is a single LLM call (timeout bumped to 600s for local 12B-class
models) except `finalize`, which is a pure DB transaction creating
World + Character + Session + pinned NPCs + Screenplay atomically.

The session dependency is reused from `routes_sessions` so the FastAPI
override applied in `main.py` covers this router automatically.
"""
import json
from collections.abc import AsyncIterator

# FastAPI 核心组件：
#   APIRouter  — 把路由分组，最终挂载到主 app
#   Depends    — 依赖注入，FastAPI 会自动调用括号内的函数并把结果传给参数
#   HTTPException — 主动抛出 HTTP 错误（如 404、400）
from fastapi import APIRouter, Depends, HTTPException

# EventSourceResponse — 把 Python 异步生成器包装成 SSE 响应格式
from sse_starlette.sse import EventSourceResponse

# AsyncSession — SQLAlchemy 的异步数据库会话，用于执行 SQL 操作
from sqlalchemy.ext.asyncio import AsyncSession

# get_session_dep — 返回数据库会话的依赖函数，FastAPI 用它注入 DB session
from dzmm.api.routes_sessions import get_session_dep

# ModelConfig — 数据库中存储的"模型配置"记录（包含 base_url、api_key、模型名等）
from dzmm.db.models import ModelConfig

# build_client — 根据 ModelConfig 记录构建对应的 LLM 客户端对象
from dzmm.models.factory import build_client

# service.wizard 里是具体的业务逻辑函数，这里只是路由层（负责解析参数、调用服务、返回结果）
from dzmm.service.wizard import (
    finalize_wizard,
    generate_character,
    generate_npcs,
    generate_screenplay_from_wizard,
    generate_single_npc,
    generate_suggestions,
    generate_world_brief,
    generate_world_details,
    refine_theme,
    stream_character,
    suggest_npcs,
    stream_npcs,
    stream_screenplay,
    stream_world_brief,
    stream_world_details,
    suggest_archetypes,
)

# 创建路由组：所有路径都以 /wizard 开头，在 API 文档中归类到 "wizard" 标签
router = APIRouter(prefix="/wizard", tags=["wizard"])

# 向导每一步都是"一次性"的 LLM 调用，输出可能很长（数千 token）。
# 本地 12B 级别模型每步可能需要 1-3 分钟，所以把超时设为 600 秒（10 分钟），
# 防止 HTTP 连接在生成完成前断掉。
# 注意：这只修改当次请求的客户端对象，不修改数据库里的配置。
_WIZARD_TIMEOUT_SECONDS = 600.0


# ──────────────────────────────────────────────
# 辅助函数
# ──────────────────────────────────────────────

# 根据请求体里的 model_config_id，从数据库查出对应的模型配置，
# 构建 LLM 客户端，并把超时时间调高到 _WIZARD_TIMEOUT_SECONDS。
async def _client_for(s: AsyncSession, model_config_id: int):
    # s.get(ModelConfig, id) — 按主键查询，如果不存在返回 None
    cfg = await s.get(ModelConfig, model_config_id)
    if cfg is None:
        # 找不到配置时返回 404 错误，FastAPI 会自动把它转成 HTTP 404 响应
        raise HTTPException(404, "model_config not found")
    # 构建实际的 LLM 客户端（OpenAI / Ollama / 其他兼容接口）
    client = build_client(cfg)
    # 如果客户端有 timeout 属性，就把它调高到 600 秒（取较大值，不缩短已有的超时）
    if hasattr(client, "timeout"):
        client.timeout = max(
            float(getattr(client, "timeout", 0.0) or 0.0),
            _WIZARD_TIMEOUT_SECONDS,
        )
    return client


# 从前端发来的 payload 字典里取出指定 key 的值并转成整数。
# 如果 key 不存在或无法转换，直接返回 400 错误，避免后续代码出现难以追踪的异常。
def _require_int(payload: dict, key: str) -> int:
    if key not in payload:
        raise HTTPException(400, f"missing {key}")
    try:
        return int(payload[key])
    except (TypeError, ValueError) as e:
        raise HTTPException(400, f"{key} must be int") from e


# ──────────────────────────────────────────────
# 普通（阻塞式）生成接口
# ──────────────────────────────────────────────

# POST /wizard/world_brief
# 向导第 1 步：根据类型（genre）和主题（theme）让 LLM 生成世界简介
@router.post("/world_brief")
async def world_brief(
    payload: dict,             # 前端发来的 JSON 请求体，FastAPI 自动解析成 dict
    s: AsyncSession = Depends(get_session_dep),  # FastAPI 依赖注入数据库 session
):
    # 先构建 LLM 客户端（需要从 payload 里取出 model_config_id）
    client = await _client_for(s, _require_int(payload, "model_config_id"))
    # 调用 service 层的生成函数，payload.get("...") or "默认值" 保证参数不为 None
    return await generate_world_brief(
        genre=str(payload.get("genre") or "悬疑探案"),  # 游戏类型，默认"悬疑探案"
        theme=str(payload.get("theme") or ""),          # 用户输入的主题关键词
        client=client,
    )


# POST /wizard/world_details
# 向导第 2 步：在世界简介（brief_md）的基础上，让 LLM 扩展更详细的世界设定
@router.post("/world_details")
async def world_details(
    payload: dict,
    s: AsyncSession = Depends(get_session_dep),
):
    client = await _client_for(s, _require_int(payload, "model_config_id"))
    return await generate_world_details(
        brief_md=str(payload.get("brief_md") or ""),  # 上一步生成的世界简介 Markdown 文本
        client=client,
    )


# POST /wizard/character
# 向导第 3 步：根据世界设定和角色原型（archetype），生成玩家角色（PC）
@router.post("/character")
async def character(
    payload: dict,
    s: AsyncSession = Depends(get_session_dep),
):
    client = await _client_for(s, _require_int(payload, "model_config_id"))
    return await generate_character(
        world_md=str(payload.get("world_md") or ""),       # 完整的世界设定文本
        archetype=str(payload.get("archetype") or ""),     # 角色原型，例如"侦探""学者"
        client=client,
    )


# POST /wizard/npcs
# 向导第 4 步：根据世界和角色，批量生成若干 NPC（非玩家角色）
@router.post("/npcs")
async def npcs(
    payload: dict,
    s: AsyncSession = Depends(get_session_dep),
):
    client = await _client_for(s, _require_int(payload, "model_config_id"))
    try:
        return await generate_npcs(
            world_md=str(payload.get("world_md") or ""),
            character_md=str(payload.get("character_md") or ""),  # 玩家角色设定文本
            client=client,
        )
    except ValueError as e:
        # LLM 返回的 JSON 格式不符合预期时会抛 ValueError，转成 502 返回给前端
        raise HTTPException(502, f"NPC generation parse failed: {e}") from e


# POST /wizard/screenplay
# 向导第 5 步：根据世界、角色、NPC 列表，生成剧本大纲（章节/关键事件/结局）
@router.post("/screenplay")
async def screenplay(
    payload: dict,
    s: AsyncSession = Depends(get_session_dep),
):
    client = await _client_for(s, _require_int(payload, "model_config_id"))
    try:
        return await generate_screenplay_from_wizard(
            world_md=str(payload.get("world_md") or ""),
            character_md=str(payload.get("character_md") or ""),
            npcs=list(payload.get("npcs") or []),           # NPC 列表（dict 列表）
            genre=str(payload.get("genre") or "悬疑探案"),
            client=client,
        )
    except ValueError as e:
        raise HTTPException(502, f"screenplay generation parse failed: {e}") from e


# POST /wizard/npc/single
# 单独生成一个 NPC（用户在预览界面手动添加额外 NPC 时调用）
@router.post("/npc/single")
async def npc_single(
    payload: dict,
    s: AsyncSession = Depends(get_session_dep),
):
    client = await _client_for(s, _require_int(payload, "model_config_id"))
    try:
        return await generate_single_npc(
            world_md=str(payload.get("world_md") or ""),
            character_md=str(payload.get("character_md") or ""),
            hint=str(payload.get("hint") or ""),   # 用户给的额外提示，比如"神秘商人"
            client=client,
        )
    except ValueError as e:
        raise HTTPException(502, f"NPC generation parse failed: {e}")


# ──────────────────────────────────────────────
# SSE 流式生成接口
# ──────────────────────────────────────────────

# 把一个异步生成器（每次 yield (事件类型, 数据字典)）包装成 SSE 响应。
# SSE 格式要求每条消息有 event 字段（事件名）和 data 字段（字符串化的数据）。
# ensure_ascii=False 让中文直接输出，不转义成 \uXXXX 形式。
def _sse(gen):
    """Wrap an async generator of (event_type, data_dict) into EventSourceResponse."""
    # 内部包装函数，把 (事件类型, 数据字典) 转换成 SSE 标准格式的 dict
    async def _wrap() -> AsyncIterator[dict]:
        try:
            async for ev_type, data in gen:
                # yield 一条 SSE 消息：event 是事件类型名，data 是 JSON 字符串
                yield {"event": ev_type, "data": json.dumps(data, ensure_ascii=False)}
        except Exception as e:
            # 生成过程中出错，推送一条 error 事件给前端，前端可以显示错误提示
            yield {"event": "error", "data": json.dumps({"message": str(e)})}
    # EventSourceResponse 接收一个异步生成器，自动设置 Content-Type: text/event-stream
    return EventSourceResponse(_wrap())


# POST /wizard/world_brief/stream
# 流式版本：实时推送世界简介的生成过程，前端可以像打字机一样逐字显示
@router.post("/world_brief/stream")
async def world_brief_stream(payload: dict, s: AsyncSession = Depends(get_session_dep)):
    client = await _client_for(s, _require_int(payload, "model_config_id"))
    return _sse(stream_world_brief(
        genre=str(payload.get("genre") or "悬疑探案"),
        theme=str(payload.get("theme") or ""),
        client=client,
    ))


# POST /wizard/world_details/stream
# 流式版本：实时推送世界细节的生成过程
@router.post("/world_details/stream")
async def world_details_stream(payload: dict, s: AsyncSession = Depends(get_session_dep)):
    client = await _client_for(s, _require_int(payload, "model_config_id"))
    return _sse(stream_world_details(
        brief_md=str(payload.get("brief_md") or ""),
        client=client,
    ))


# POST /wizard/character/stream
# 流式版本：实时推送角色生成过程
@router.post("/character/stream")
async def character_stream(payload: dict, s: AsyncSession = Depends(get_session_dep)):
    client = await _client_for(s, _require_int(payload, "model_config_id"))
    return _sse(stream_character(
        world_md=str(payload.get("world_md") or ""),
        archetype=str(payload.get("archetype") or ""),
        client=client,
    ))


# POST /wizard/npcs/stream
# 流式版本：实时推送 NPC 批量生成过程
@router.post("/npcs/stream")
async def npcs_stream(payload: dict, s: AsyncSession = Depends(get_session_dep)):
    client = await _client_for(s, _require_int(payload, "model_config_id"))
    return _sse(stream_npcs(
        world_md=str(payload.get("world_md") or ""),
        character_md=str(payload.get("character_md") or ""),
        client=client,
    ))


# POST /wizard/screenplay/stream
# 流式版本：实时推送剧本大纲生成过程
@router.post("/screenplay/stream")
async def screenplay_stream(payload: dict, s: AsyncSession = Depends(get_session_dep)):
    client = await _client_for(s, _require_int(payload, "model_config_id"))
    return _sse(stream_screenplay(
        world_md=str(payload.get("world_md") or ""),
        character_md=str(payload.get("character_md") or ""),
        npcs=list(payload.get("npcs") or []),
        genre=str(payload.get("genre") or "悬疑探案"),
        client=client,
    ))


# ──────────────────────────────────────────────
# 辅助建议接口（帮助用户填写向导表单）
# ──────────────────────────────────────────────

# POST /wizard/suggest_archetypes
# 根据世界设定，让 LLM 推荐几种适合的角色原型（比如"冷面侦探""热血记者"）
@router.post("/suggest_archetypes")
async def suggest_archetypes_route(payload: dict, s: AsyncSession = Depends(get_session_dep)):
    client = await _client_for(s, _require_int(payload, "model_config_id"))
    try:
        return await suggest_archetypes(
            world_md=str(payload.get("world_md") or ""),
            client=client,
        )
    except Exception as e:
        raise HTTPException(502, f"archetype suggestion failed: {e}") from e


# POST /wizard/suggest_npcs
# 根据世界和角色，让 LLM 推荐适合加入的 NPC 角色名称/类型
@router.post("/suggest_npcs")
async def suggest_npcs_route(payload: dict, s: AsyncSession = Depends(get_session_dep)):
    client = await _client_for(s, _require_int(payload, "model_config_id"))
    try:
        return await suggest_npcs(
            world_md=str(payload.get("world_md") or ""),
            character_md=str(payload.get("character_md") or ""),
            client=client,
        )
    except Exception as e:
        raise HTTPException(502, f"NPC suggestion failed: {e}") from e


# POST /wizard/refine_theme
# 用户输入模糊主题关键词（rough），让 LLM 帮助完善成更具体的主题描述
@router.post("/refine_theme")
async def refine_theme_route(payload: dict, s: AsyncSession = Depends(get_session_dep)):
    client = await _client_for(s, _require_int(payload, "model_config_id"))
    try:
        return await refine_theme(
            genre=str(payload.get("genre") or ""),   # 游戏类型
            rough=str(payload.get("rough") or ""),   # 用户填的粗略主题
            client=client,
        )
    except Exception as e:
        raise HTTPException(502, f"theme refinement failed: {e}") from e


# POST /wizard/suggest
# 向导首页：根据类型（genre_hint），让 LLM 生成几个主题/创意建议供用户选择
@router.post("/suggest")
async def suggest(
    payload: dict,
    s: AsyncSession = Depends(get_session_dep),
):
    client = await _client_for(s, _require_int(payload, "model_config_id"))
    try:
        return await generate_suggestions(
            genre_hint=str(payload.get("genre") or ""),
            client=client,
        )
    except (ValueError, Exception) as e:
        raise HTTPException(502, f"suggestion generation failed: {e}") from e


# ──────────────────────────────────────────────
# 旧版向导最终步骤（已废弃）
# ──────────────────────────────────────────────

# DEPRECATED(Plan-D): Old Screenplay-based wizard finalize.
# Remove once WizardView.vue fully migrates to /wizard/fw/* flow.
# POST /wizard/finalize
# 旧版向导的最后一步：把向导收集的全部数据（世界/角色/NPC/剧本）一次性写入数据库。
# 使用数据库事务（commit/rollback）保证原子性——要么全部写入，要么全部回滚。
@router.post("/finalize")
async def finalize(
    payload: dict,
    s: AsyncSession = Depends(get_session_dep),
):
    try:
        # finalize_wizard 会在数据库里创建 World + Character + Session + NPC + Screenplay
        result = await finalize_wizard(s, payload)
        # commit() 把本次事务的所有改动永久写入数据库
        await s.commit()
    except (KeyError, ValueError, TypeError) as e:
        # 如果数据格式有问题，回滚所有未提交的改动，返回 400 错误
        await s.rollback()
        raise HTTPException(400, f"invalid bundle: {e}") from e
    return result


# ──────────────────────────────────────────────
# 开放世界框架向导（新版 /wizard/fw/*）
# ──────────────────────────────────────────────
# 与旧版向导不同，新版"框架向导"生成的是可复用的"世界框架"（WorldFramework），
# 包含地点网络、派系、NPC 模板、事件库、主线战役等，供多个剧本共用。
from dzmm.service.wizard_framework import (
    generate_locations,
    generate_factions,
    generate_npc_templates,
    generate_events,
    generate_campaign,
    finalize_framework,
)


# POST /wizard/fw/locations
# 框架向导第 2 步：根据世界简介生成地点网络（location network）
# 地点是 NPC 活动和事件发生的场所，比如"废弃的矿山""繁华的港口"
@router.post("/fw/locations")
async def fw_locations(payload: dict, s: AsyncSession = Depends(get_session_dep)):
    """Step 2: Generate location network from world brief."""
    client = await _client_for(s, _require_int(payload, "model_config_id"))
    return await generate_locations(
        genre=str(payload.get("genre", "")),
        world_brief_md=str(payload.get("world_brief_md", "")),  # 世界简介文本
        client=client,
    )


# POST /wizard/fw/factions
# 框架向导第 3 步：根据世界简介和地点列表，生成派系（faction）
# 派系是游戏世界里有组织的势力，比如"皇室守卫""地下盗贼公会"
@router.post("/fw/factions")
async def fw_factions(payload: dict, s: AsyncSession = Depends(get_session_dep)):
    """Step 3: Generate factions from world brief + locations."""
    client = await _client_for(s, _require_int(payload, "model_config_id"))
    return await generate_factions(
        genre=str(payload.get("genre", "")),
        world_brief_md=str(payload.get("world_brief_md", "")),
        locations=payload.get("locations", []),   # 上一步生成的地点列表
        client=client,
    )


# POST /wizard/fw/npc_templates
# 框架向导第 4 步：根据世界、地点、派系，生成 NPC 模板（NPC template）
# 模板是可以在多个存档里复用的 NPC 原型，比如"驻守东城门的老卫士"
@router.post("/fw/npc_templates")
async def fw_npc_templates(payload: dict, s: AsyncSession = Depends(get_session_dep)):
    """Step 4: Generate NPC templates from world + locations + factions."""
    client = await _client_for(s, _require_int(payload, "model_config_id"))
    return await generate_npc_templates(
        genre=str(payload.get("genre", "")),
        world_brief_md=str(payload.get("world_brief_md", "")),
        locations=payload.get("locations", []),
        factions=payload.get("factions", []),     # 上一步生成的派系列表
        client=client,
    )


# POST /wizard/fw/events
# 框架向导第 5 步：生成事件库（event library）
# 事件库是可触发的剧情片段，GM 可以在游戏中随时激活它们
@router.post("/fw/events")
async def fw_events(payload: dict, s: AsyncSession = Depends(get_session_dep)):
    """Step 5: Generate event library."""
    client = await _client_for(s, _require_int(payload, "model_config_id"))
    return await generate_events(
        genre=str(payload.get("genre", "")),
        world_brief_md=str(payload.get("world_brief_md", "")),
        locations=payload.get("locations", []),
        factions=payload.get("factions", []),
        npc_templates=payload.get("npc_templates", []),  # 上一步生成的 NPC 模板列表
        client=client,
    )


# POST /wizard/fw/campaign
# 框架向导第 7 步（可选）：生成战役（campaign）主线阶段
# 战役是横跨多个存档/章节的宏观剧情线，比如"寻找失踪皇子"
@router.post("/fw/campaign")
async def fw_campaign(payload: dict, s: AsyncSession = Depends(get_session_dep)):
    """Step 7 (optional): Generate campaign main-plot phases."""
    client = await _client_for(s, _require_int(payload, "model_config_id"))
    return await generate_campaign(
        genre=str(payload.get("genre", "")),
        world_brief_md=str(payload.get("world_brief_md", "")),
        events=payload.get("events", []),  # 上一步生成的事件库列表
        client=client,
    )


# POST /wizard/fw/finalize
# 框架向导第 8 步（最终步）：把整个世界框架写入数据库，返回新生成的 framework_id
@router.post("/fw/finalize")
async def fw_finalize(payload: dict, s: AsyncSession = Depends(get_session_dep)):
    """Step 8: Commit WorldFramework to DB. Returns {framework_id}."""
    # finalize_framework 会把地点/派系/NPC模板/事件库/战役全部写入数据库
    framework_id = await finalize_framework(s, payload)
    return {"framework_id": framework_id}
