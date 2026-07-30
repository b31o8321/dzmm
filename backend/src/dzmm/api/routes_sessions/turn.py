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

import json
import logging
import uuid
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
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
    Session as GameSession,
)
from dzmm.parsing.events import NarrativeDelta, ParseError, TagComplete
from dzmm.service.game import run_turn
from dzmm.service.screenplay import schedule_pending_rewrites
from dzmm.service.summarizer import maybe_summarize
from dzmm.service.session_turn_coordinator import SessionBusyError
from sqlalchemy import delete, func, select

# APIRouter 是模块化路由注册器，类似 Spring 里的 @RequestMapping 前缀设置
router = APIRouter(prefix="/sessions", tags=["sessions"])

log = logging.getLogger(__name__)


# ── POST /sessions/{session_id}/warmup ───────────────────
@router.post("/{session_id}/warmup", status_code=202)
# status_code=202 → HTTP 202 Accepted：表示"已收到请求，正在后台处理，尚未完成"
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
        # async with 是"异步上下文管理器"，等价于 try/finally 确保资源被释放
        # session_maker() 返回一个数据库会话，退出 with 块时自动关闭
        async with session_maker() as s:
            sess = await s.get(GameSession, session_id)
            if sess is None:
                return  # 存档不存在，静默退出
            cfg = await s.get(ModelConfig, sess.gm_model_config_id)
            if cfg is None:
                return
            client = build_client(cfg)  # 构造 LLM 客户端对象
            try:
                from dzmm.models.client import GenerationParams, Message
                # 发一条最小请求（max_tokens=1）触发模型加载到内存
                # async for 消费异步生成器：每个 _ 是模型输出的一个 token（我们不关心内容）
                async for _ in client.stream(
                    [Message(role="user", content="ok")],
                    GenerationParams(max_tokens=1, temperature=0.0),
                ):
                    pass  # 我们不关心输出，只是让模型预热
            except Exception:
                pass  # 预热失败不影响游戏，忽略所有异常

    # create_task = 在事件循环里启动后台协程，不等待它完成就立刻返回
    # 【Java 对比】类似 CompletableFuture.runAsync(() -> _do_warmup())
    # 【asyncio 机制】asyncio 是 Python 的单线程异步框架。
    #   create_task 把协程提交给事件循环，事件循环会在 IO 等待期间切换执行它。
    _asyncio.create_task(_do_warmup())
    return {"status": "started"}  # 立刻返回，不等待预热完成


# ── DELETE /sessions/{session_id}/last_turn ──────────────
@router.delete("/{session_id}/last_turn", status_code=204)
async def delete_last_turn(
    session_id: int,
    s: AsyncSession = Depends(get_session_dep)  # 注入 DB 会话（自动管理生命周期）
):
    """删除最新一回合的所有消息（含 user + assistant），回滚 turn_count。

    前端"重试"/"编辑上一条"功能调用此接口。

    旧实现"按 id desc 取最近 2 条"在 user 发了输入但 assistant 还没产生
    （或 assistant 流中途出错）时会删错——把 N-1 回合的 assistant 消息当成
    "最近第 2 条"删掉。新实现按 turn 号定位最大回合并清掉那一回合的所有
    消息，自然兼容半截状态。
    """
    sess = await s.get(GameSession, session_id)
    if sess is None:
        raise HTTPException(404, "session not found")

    # func.max(MessageRow.turn) → SQL 的 MAX(turn) 聚合函数
    # 找到当前最大的 turn 号；若没有任何消息则 scalar() 返回 None
    max_turn = (
        await s.execute(
            select(func.max(MessageRow.turn)).where(
                MessageRow.session_id == session_id
            )
        )
    ).scalar()
    if max_turn is None or max_turn <= 0:
        return  # 没有消息或 turn 为 0（系统消息），无事可做

    # v0.10.5: restore snapshot from the assistant message of max_turn
    # before deleting the message rows themselves. Old archives without
    # a snapshot fall through harmlessly (deserialize_snapshot → {}).
    # 在删消息之前，先从该回合的 assistant 消息里恢复快照（undo 机制）
    # 快照记录了这回合开始前的游戏状态，恢复快照相当于"撤销"这一回合的状态变化
    from dzmm.service.turn_snapshot import deserialize_snapshot, restore_snapshot
    last_assistant_snap = (await s.execute(
        select(MessageRow.snapshot_json).where(
            MessageRow.session_id == session_id,
            MessageRow.role == "assistant",
            MessageRow.turn == max_turn,
        ).order_by(MessageRow.id.desc()).limit(1)  # 取最后一条 assistant 消息的快照
    )).scalar_one_or_none()
    if last_assistant_snap:
        snap = deserialize_snapshot(last_assistant_snap)  # JSON 字符串 → 快照对象
        if snap:
            await restore_snapshot(s, session_id, snap)  # 把快照数据写回数据库各表

    # 删除该 turn 号下的全部消息（通常是 user + assistant 两条；半截
    # turn 可能只有 user 一条；理论上的多条 user/assistant 也一并清掉）。
    await s.execute(
        delete(MessageRow).where(
            MessageRow.session_id == session_id,
            MessageRow.turn == max_turn,
        )
    )
    # v0.10: also rewind agent_streams histories (Director + per-NPC).
    # max_keep_turn = max_turn - 1 because turn=max_turn is what we just
    # popped from messages — agent histories must drop the same turn.
    # 同步回滚 Agent（Director/NPC）的流历史，与消息历史保持一致
    from dzmm.service.agents.streams import rollback_to_turn
    await rollback_to_turn(s, session_id, max_keep_turn=max_turn - 1)
    # 把存档的 turn_count 减 1，不能低于 0
    sess.turn_count = max(0, max_turn - 1)
    await s.commit()


async def stream_turn_events(
    session_maker,
    session_id: int,
    action: str,
) -> AsyncIterator[dict]:
    """Run one game turn and expose the transport-neutral event stream."""
    async with session_maker() as session:
        game_session = await session.get(GameSession, session_id)
        if game_session is None:
            yield {
                "event": "error",
                "data": json.dumps(
                    {"code": "session_not_found", "message": "session not found"}
                ),
            }
            return

        config = await session.get(ModelConfig, game_session.gm_model_config_id)
        if config is None:
            yield {
                "event": "error",
                "data": json.dumps(
                    {"code": "model_error", "message": "model config not found"}
                ),
            }
            return
        client = build_client(config)

        import time as _time

        narrative_buffer: list[str] = []
        last_flush = _time.monotonic()

        def flush_narrative() -> dict | None:
            if not narrative_buffer:
                return None
            payload = "".join(narrative_buffer)
            narrative_buffer.clear()
            return {
                "event": "narrative",
                "data": json.dumps({"text": payload}, ensure_ascii=False),
            }

        async def parsed_events():
            try:
                async for event in run_turn(
                    session,
                    session_id,
                    action,
                    client,
                    ollama_base_url=config.base_url,
                    session_maker=session_maker,
                ):
                    yield event
            except Exception as exc:  # noqa: BLE001
                log.exception("turn stream failed for session %s", session_id)
                yield exc

        async for event in parsed_events():
            if isinstance(event, Exception):
                narrative_buffer.clear()
                await session.rollback()
                yield {
                    "event": "error",
                    "data": json.dumps(
                        {"code": "model_error", "message": str(event)},
                        ensure_ascii=False,
                    ),
                }
                return
            if isinstance(event, NarrativeDelta):
                narrative_buffer.append(event.text)
                now = _time.monotonic()
                if (
                    sum(len(part) for part in narrative_buffer) >= 20
                    or now - last_flush >= 0.05
                ):
                    output = flush_narrative()
                    if output:
                        yield output
                    last_flush = now
            elif isinstance(event, TagComplete):
                output = flush_narrative()
                if output:
                    yield output
                last_flush = _time.monotonic()
                yield {
                    "event": "tag",
                    "data": json.dumps(
                        {
                            "name": event.name,
                            "attrs": event.attrs,
                            "content": event.content,
                        },
                        ensure_ascii=False,
                    ),
                }
            elif isinstance(event, ParseError):
                output = flush_narrative()
                if output:
                    yield output
                yield {
                    "event": "parse_error",
                    "data": json.dumps(
                        {"message": event.message}, ensure_ascii=False
                    ),
                }

        output = flush_narrative()
        if output:
            yield output
        await session.commit()

    await schedule_pending_rewrites(session_maker, session_id)

    async with session_maker() as session:
        game_session = await session.get(GameSession, session_id)
        summary_config = await session.get(
            ModelConfig, game_session.summarizer_model_config_id
        )
        summary_client = build_client(summary_config)
        try:
            if await maybe_summarize(session, session_id, summary_client):
                await session.commit()
        except Exception as exc:  # noqa: BLE001
            yield {
                "event": "summarize_error",
                "data": json.dumps({"message": str(exc)}, ensure_ascii=False),
            }

        try:
            from dzmm.db.models import AgentStream
            from dzmm.service.agents.streams import compress_if_needed

            streams = (
                await session.execute(
                    select(AgentStream).where(AgentStream.session_id == session_id)
                )
            ).scalars().all()
            for stream in streams:
                if stream.kind == "scene":
                    continue
                threshold = 30 if stream.kind == "gm_director" else 25
                keep = 10 if stream.kind == "gm_director" else 8
                await compress_if_needed(
                    session, stream.id, summary_client, threshold, keep
                )
            await session.commit()
        except Exception as exc:  # noqa: BLE001
            log.warning("agent_stream compress failed: %s", exc)

    async with session_maker() as session:
        assistant_message_id = (
            await session.execute(
                select(MessageRow.id)
                .where(
                    MessageRow.session_id == session_id,
                    MessageRow.role == "assistant",
                )
                .order_by(MessageRow.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
    yield {
        "event": "done",
        "data": json.dumps({"assistant_msg_id": assistant_message_id}),
    }


# ── POST /sessions/{session_id}/turn ─────────────────────
@router.post("/{session_id}/turn")
async def take_turn(
    session_id: int,
    body: TurnRequest,              # 请求体：包含玩家的行动描述文本
    request: Request,
    session_maker = Depends(get_session_maker_dep),
    # 【为什么用 session_maker 而不是 get_session_dep？】
    # get_session_dep 注入一个已打开的 AsyncSession，请求结束时自动关闭。
    # 但 SSE 需要多个独立的数据库事务（主回合 + 摘要 + Agent 压缩），
    # 每个事务用完即关，不能共用同一个 session。
    # session_maker 是工厂函数，路由自己决定何时创建/关闭会话，更灵活。
):
    """核心接口：处理玩家一回合的行动，流式返回 GM 的叙事响应。

    返回 EventSourceResponse（SSE），前端用 EventSource API 接收事件流。
    每个事件都是一个 JSON 字典：{"event": 事件类型, "data": JSON字符串}

    事件类型：
      narrative   → 叙事文本片段（流式，多次推送拼成完整 GM 回复）
      tag         → 完整 XML 标签（state_change / dice / npc_update 等结构化事件）
      parse_error → 解析错误（通常可忽略）
      summarize_error → 摘要失败（非致命）
      done        → 本回合结束，携带最后一条 assistant 消息的 id
    """
    # ── 为什么游戏 turn 要用流式响应（SSE）？ ──────────────────────────
    # LLM 生成文字需要 5-30 秒。如果等 LLM 全部生成完再一次性返回，
    # 用户会盯着空白屏幕等待，体验极差。
    # SSE 让服务器"边生成边发送"，用户看到文字像被人实时打出来，
    # 感觉响应快，实际等待时间不变但心理体验好很多。
    # 这是现代 AI 聊天产品（ChatGPT/Claude 等）的标准做法。
    #
    # 【SSE vs WebSocket】
    # WebSocket 是双向的，服务器和客户端都能主动发消息。
    # SSE 是单向的（服务器 → 客户端），但更简单，HTTP/1.1 就支持，
    # 对于"AI 回复"这种单向场景已经足够。

    coordinator = request.app.state.turn_coordinator
    try:
        lease = await coordinator.acquire(
            session_id,
            f"legacy-{uuid.uuid4()}",
            "turn",
        )
    except SessionBusyError as exc:
        return JSONResponse(
            status_code=409,
            content={
                "code": "session_busy",
                "message": "This session already has an active turn",
                "active_run": exc.active.to_dict(),
            },
        )

    async def guarded_event_stream() -> AsyncIterator[dict]:
        try:
            async for event in stream_turn_events(
                session_maker, session_id, body.action
            ):
                yield event
        finally:
            await lease.release()

    # EventSourceResponse 把 async generator 包装成符合 SSE 协议的 HTTP 响应
    # 【SSE 协议格式】每个事件格式为：
    #   event: 事件类型\n
    #   data: JSON 字符串\n
    #   \n（空行表示事件结束）
    # sse_starlette 库自动处理这个格式，我们只需要 yield dict 即可
    return EventSourceResponse(guarded_event_stream())
