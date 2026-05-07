# ============================================================
# HTTP 路由：回合相关接口
# ============================================================
# 【架构层次】这是 API 层（Controller 层）。
#   职责：接收 HTTP 请求 → 调用 service 层 → 把结果流式返回给前端。
#
# 【关键技术：Server-Sent Events（SSE）】
#   普通 HTTP：请求→响应，一问一答。
#   SSE：服务器保持连接，持续推送事件，直到流结束。
#   这里用 SSE 把 LLM 逐字输出实时推给前端（用户看到文字"打印机效果"）。
#
# 【Java 对比】
#   FastAPI 路由类似 Spring MVC 的 @RestController + @RequestMapping。
#   Depends() 是 FastAPI 的依赖注入，类似 Spring 的 @Autowired。
#   async def 函数在 Python 里等价于返回 CompletableFuture 的方法，
#   但语法更简洁：await 直接等待，不需要 .thenApply() 链式调用。
# ============================================================

"""Turn endpoints: POST /turn (SSE), DELETE /last_turn, POST /warmup."""

import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException
from sse_starlette.sse import EventSourceResponse   # SSE 响应封装库
from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.api.routes_sessions._common import (
    build_client,
    get_session_dep,
    get_session_maker_dep,
)
from dzmm.api.schemas import TurnRequest
from dzmm.db.models import (
    Message as MessageRow,
    ModelConfig,
    Screenplay,
    ScreenplayRevision,
    Session as GameSession,
)
from dzmm.parsing.events import NarrativeDelta, ParseError, TagComplete
from dzmm.service.game import run_turn
from dzmm.service.screenplay import rewrite_in_background
from dzmm.service.summarizer import maybe_summarize
from sqlalchemy import select

# APIRouter 是模块化路由注册器，类似 Spring 里的 @RequestMapping 前缀设置
router = APIRouter(prefix="/sessions", tags=["sessions"])


# ── POST /sessions/{session_id}/warmup ───────────────────
@router.post("/{session_id}/warmup", status_code=202)
async def warmup_model(
    session_id: int,
    session_maker = Depends(get_session_maker_dep),  # 注入数据库连接工厂
):
    """预热 GM 模型（Fire-and-forget）。

    本地 7B 模型首次加载需要 5-20 秒。用户点"开始游戏"时立刻调用这个接口，
    让模型在后台加载，这样第一回合不用等待冷启动。
    返回 202 Accepted（表示"已收到，正在后台处理"）而不是 200（表示"已完成"）。
    """
    import asyncio as _asyncio  # 延迟导入（只在这个函数首次调用时 import，减少模块加载时间）

    async def _do_warmup():
        """实际预热逻辑，在后台任务中运行。"""
        async with session_maker() as s:
            sess = await s.get(GameSession, session_id)
            if sess is None:
                return
            cfg = await s.get(ModelConfig, sess.gm_model_config_id)
            if cfg is None:
                return
            client = build_client(cfg)
            try:
                from dzmm.models.client import GenerationParams, Message
                # 发一条最小请求（max_tokens=1）触发模型加载到内存
                async for _ in client.stream(
                    [Message(role="user", content="ok")],
                    GenerationParams(max_tokens=1, temperature=0.0),
                ):
                    pass  # 我们不关心输出，只是让模型预热
            except Exception:
                pass  # 预热失败不影响游戏，忽略

    # create_task = 在事件循环里启动后台协程，不等待它完成就立刻返回
    # 【Java 对比】类似 CompletableFuture.runAsync(() -> _do_warmup())
    _asyncio.create_task(_do_warmup())
    return {"status": "started"}


# ── DELETE /sessions/{session_id}/last_turn ──────────────
@router.delete("/{session_id}/last_turn", status_code=204)
async def delete_last_turn(
    session_id: int,
    s: AsyncSession = Depends(get_session_dep)  # 注入 DB 会话（自动管理生命周期）
):
    """删除最新一回合（用户/GM 消息对），回滚 turn_count。

    前端"重试"/"编辑上一条"功能调用此接口。
    """
    sess = await s.get(GameSession, session_id)
    if sess is None:
        raise HTTPException(404, "session not found")  # 相当于 ResponseStatusException(404)
    if sess.turn_count <= 0:
        return  # 没有可删除的回合，直接返回 204

    # 查询最新两条消息（user + assistant），倒序取 2 条
    rows = (
        await s.execute(
            select(MessageRow)
            .where(MessageRow.session_id == session_id)
            .order_by(MessageRow.id.desc())
            .limit(2)
        )
    ).scalars().all()

    for r in rows:
        await s.delete(r)
    sess.turn_count = max(0, sess.turn_count - 1)  # 防止变负数
    await s.commit()


# ── POST /sessions/{session_id}/turn ─────────────────────
@router.post("/{session_id}/turn")
async def take_turn(
    session_id: int,
    body: TurnRequest,              # 请求体：包含玩家的行动描述文本
    session_maker = Depends(get_session_maker_dep),
):
    """核心接口：处理玩家一回合的行动，流式返回 GM 的叙事响应。

    返回 EventSourceResponse（SSE），前端用 EventSource API 接收事件流。
    每个事件都是一个 JSON 字典：{"event": 事件类型, "data": JSON字符串}

    事件类型：
      narrative   → 叙事文本片段（流式）
      tag         → 完整 XML 标签（state_change / dice / npc_update 等）
      parse_error → 解析错误（通常可忽略）
      summarize_error → 摘要失败（非致命）
      done        → 本回合结束
    """
    # event_stream 是一个 async generator（异步生成器函数）
    # 用 yield 逐条产出 SSE 事件，FastAPI 会把它封装成 HTTP 流式响应
    async def event_stream() -> AsyncIterator[dict]:
        # ── 第一个 DB 会话：处理回合，流式输出 ─────────
        async with session_maker() as s:
            sess = await s.get(GameSession, session_id)
            if sess is None:
                # yield 一个错误事件后 return，终止生成器
                yield {"event": "error",
                       "data": json.dumps({"message": "session not found"})}
                return

            cfg = await s.get(ModelConfig, sess.gm_model_config_id)
            client = build_client(cfg)

            # ── 叙事合并缓冲 ──────────────────────────────
            # 问题：LLM 每次 yield 可能只有 1-2 个字符，导致 SSE 发包频率极高，
            # 浏览器端解析开销大。解决：每累积 20 个字符或每 50ms 批量推送一次。
            import time as _time
            narrative_buf: list[str] = []
            last_flush = _time.monotonic()
            FLUSH_CHARS = 20           # 积累超过 20 字符就推送
            FLUSH_INTERVAL = 0.05      # 或者超过 50ms 就推送

            def _flush_narrative():
                """把缓冲区的叙事文本合并成一个 SSE 事件并清空缓冲区。"""
                if narrative_buf:
                    payload = "".join(narrative_buf)
                    narrative_buf.clear()
                    return {"event": "narrative",
                            "data": json.dumps({"text": payload}, ensure_ascii=False)}
                return None  # 缓冲区为空，无需推送

            # run_turn 是异步生成器（async generator），用 async for 消费
            # 它边调用 LLM 边产出 ParseEvent 事件
            async for ev in run_turn(s, session_id, body.action, client,
                                     ollama_base_url=cfg.base_url if cfg else None):
                if isinstance(ev, NarrativeDelta):
                    # 叙事片段：加入缓冲，满足条件时推送
                    narrative_buf.append(ev.text)
                    now = _time.monotonic()
                    total = sum(len(x) for x in narrative_buf)
                    if total >= FLUSH_CHARS or (now - last_flush) >= FLUSH_INTERVAL:
                        out = _flush_narrative()
                        if out:
                            yield out   # ← yield 给 SSE 流
                        last_flush = now

                elif isinstance(ev, TagComplete):
                    # 结构化标签（dice/state_change 等）：先把缓冲区的文本推出去，
                    # 然后再推标签事件，保证顺序正确
                    out = _flush_narrative()
                    if out:
                        yield out
                    last_flush = _time.monotonic()
                    yield {"event": "tag",
                           "data": json.dumps(
                               {"name": ev.name, "attrs": ev.attrs, "content": ev.content},
                               ensure_ascii=False
                           )}

                elif isinstance(ev, ParseError):
                    out = _flush_narrative()
                    if out:
                        yield out
                    yield {"event": "parse_error",
                           "data": json.dumps({"message": ev.message}, ensure_ascii=False)}

            # LLM 流结束：推出剩余叙事
            out = _flush_narrative()
            if out:
                yield out

            await s.commit()  # 提交本回合数据到数据库

        # ── 后台触发：本回合 GM 留下的 plot_turn 重写（fire-and-forget） ──
        # _apply_plot_turn 把 <plot_turn impact="major"> 的 revision 行先存
        # 为占位（before == after, diff_summary 含 "pending"）。这里在主提交
        # 后扫一次，把待处理的 revision 全部派给后台异步重写——不阻塞 SSE 流，
        # 用户继续玩；下次打开 ScreenplayView 看到的就是重写后的章节。
        try:
            async with session_maker() as _s_bg:
                _active_sp = (await _s_bg.execute(
                    select(Screenplay)
                    .where(
                        Screenplay.session_id == session_id,
                        Screenplay.status == "active",
                    )
                    .order_by(Screenplay.version.desc())
                )).scalars().first()
                if _active_sp is not None:
                    _pending = (await _s_bg.execute(
                        select(ScreenplayRevision).where(
                            ScreenplayRevision.screenplay_id == _active_sp.id,
                            ScreenplayRevision.before_chapters_json
                                == ScreenplayRevision.after_chapters_json,
                        )
                    )).scalars().all()
                    for _rev in _pending:
                        if "pending" not in (_rev.diff_summary or "").lower():
                            continue
                        asyncio.create_task(rewrite_in_background(
                            session_maker, session_id, _rev.id, _rev.trigger_description,
                        ))
        except Exception:  # noqa: BLE001
            pass  # background scheduling failure must never block the turn

        # ── 第二个 DB 会话：运行摘要器 ───────────────────
        # 用新会话而非上面那个，因为 commit 后数据已持久化，
        # 摘要器需要读取最新状态（含刚保存的消息）。
        async with session_maker() as s:
            sess = await s.get(GameSession, session_id)
            sum_cfg = await s.get(ModelConfig, sess.summarizer_model_config_id)
            sum_client = build_client(sum_cfg)
            try:
                # maybe_summarize：检查是否需要压缩旧消息；如需要则调用 LLM 生成摘要
                ran = await maybe_summarize(s, session_id, sum_client)
                if ran:
                    await s.commit()
            except Exception as e:  # noqa: BLE001
                # 摘要失败不影响游戏，把错误推给前端（前端可选择显示或忽略）
                yield {"event": "summarize_error",
                       "data": json.dumps({"message": str(e)}, ensure_ascii=False)}

        async with session_maker() as _s2:
            _last_id = (
                await _s2.execute(
                    select(MessageRow.id)
                    .where(
                        MessageRow.session_id == session_id,
                        MessageRow.role == "assistant",
                    )
                    .order_by(MessageRow.id.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
        yield {"event": "done", "data": json.dumps({"assistant_msg_id": _last_id})}  # 告知前端本回合完全结束

    # EventSourceResponse 把 async generator 包装成 HTTP SSE 响应
    return EventSourceResponse(event_stream())
