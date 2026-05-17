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
import logging
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
from dzmm.service.screenplay import rewrite_in_background, schedule_pending_rewrites
from dzmm.service.summarizer import maybe_summarize
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


# ── POST /sessions/{session_id}/turn ─────────────────────
@router.post("/{session_id}/turn")
async def take_turn(
    session_id: int,
    body: TurnRequest,              # 请求体：包含玩家的行动描述文本
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

    # event_stream 是一个 async generator（异步生成器函数）
    # 用 yield 逐条产出 SSE 事件，FastAPI 会把它封装成 HTTP 流式响应
    async def event_stream() -> AsyncIterator[dict]:
        # ── 第一个 DB 会话：处理回合，流式输出 ─────────
        # async with session_maker() as s: 每次进入 with 块创建新会话，退出时关闭
        async with session_maker() as s:
            sess = await s.get(GameSession, session_id)
            if sess is None:
                # yield 一个错误事件后 return，终止生成器
                yield {"event": "error",
                       "data": json.dumps({"message": "session not found"})}
                return

            cfg = await s.get(ModelConfig, sess.gm_model_config_id)
            client = build_client(cfg)  # 根据配置构造对应的 LLM 客户端

            # ── 叙事合并缓冲 ──────────────────────────────
            # 问题：LLM 每次 yield 可能只有 1-2 个字符，导致 SSE 发包频率极高，
            # 浏览器端解析开销大，网络层也有每个 SSE 帧有固定头部开销。
            # 解决：每累积 20 个字符或每 50ms 批量推送一次，减少推送频率。
            import time as _time
            narrative_buf: list[str] = []  # 文本片段缓冲区
            last_flush = _time.monotonic()  # 上次推送的时间戳（单调时钟，不受系统时间影响）
            FLUSH_CHARS = 20           # 积累超过 20 字符就推送
            FLUSH_INTERVAL = 0.05      # 或者超过 50ms 就推送

            def _flush_narrative():
                """把缓冲区的叙事文本合并成一个 SSE 事件并清空缓冲区。"""
                if narrative_buf:
                    payload = "".join(narrative_buf)  # 把列表里的片段拼成字符串
                    narrative_buf.clear()              # 清空缓冲区
                    # ensure_ascii=False: 让 json.dumps 保留中文字符（不转义为 \uXXXX）
                    return {"event": "narrative",
                            "data": json.dumps({"text": payload}, ensure_ascii=False)}
                return None  # 缓冲区为空，无需推送

            # run_turn 是异步生成器（async generator），用 async for 消费
            # 它边调用 LLM 边产出 ParseEvent 事件
            # 传入 session_maker 是因为 run_turn 内部可能需要独立的数据库会话
            async for ev in run_turn(s, session_id, body.action, client,
                                     ollama_base_url=cfg.base_url if cfg else None,
                                     session_maker=session_maker):
                if isinstance(ev, NarrativeDelta):
                    # NarrativeDelta：LLM 输出的叙事文字片段
                    narrative_buf.append(ev.text)
                    now = _time.monotonic()
                    total = sum(len(x) for x in narrative_buf)
                    # 满足"字数阈值"或"时间阈值"之一就推送
                    if total >= FLUSH_CHARS or (now - last_flush) >= FLUSH_INTERVAL:
                        out = _flush_narrative()
                        if out:
                            yield out   # ← yield 给 SSE 流（推送给前端）
                        last_flush = now

                elif isinstance(ev, TagComplete):
                    # TagComplete：一个完整的 XML 标签（结构化事件）
                    # 先把缓冲区里的叙事文本推出去，保证叙事文字先于标签事件到达前端
                    out = _flush_narrative()
                    if out:
                        yield out
                    last_flush = _time.monotonic()
                    # 推送结构化标签事件（前端据此更新状态面板、处理掷骰等）
                    yield {"event": "tag",
                           "data": json.dumps(
                               {"name": ev.name, "attrs": ev.attrs, "content": ev.content},
                               ensure_ascii=False
                           )}

                elif isinstance(ev, ParseError):
                    # ParseError：XML 解析出错（通常是 LLM 输出了不完整的标签）
                    out = _flush_narrative()
                    if out:
                        yield out
                    yield {"event": "parse_error",
                           "data": json.dumps({"message": ev.message}, ensure_ascii=False)}

            # LLM 流结束：推出缓冲区剩余的叙事文字
            out = _flush_narrative()
            if out:
                yield out

            # 把本回合的所有数据库变更持久化（消息行、状态更新等）
            await s.commit()

        # ── 后台触发：本回合 GM 留下的 plot_turn 重写（fire-and-forget） ──
        # 当 GM 输出了 <plot_turn impact="major"> 标签时，意味着剧情发生重大转折，
        # 需要重写剧本章节大纲。这个重写是耗时操作（需要再调一次 LLM），
        # 所以主提交后扫描待处理的 revision，启动后台任务异步完成，不阻塞 SSE 流。
        try:
            async with session_maker() as _s_bg:
                # 找当前存档激活的剧本
                _active_sp = (await _s_bg.execute(
                    select(Screenplay)
                    .where(
                        Screenplay.session_id == session_id,
                        Screenplay.status == "active",
                    )
                    .order_by(Screenplay.version.desc())  # 取最新版本
                )).scalars().first()
                if _active_sp is not None:
                    # 找所有"待处理"的剧本修订行（before == after 且 diff_summary 含 "pending"）
                    _pending = (await _s_bg.execute(
                        select(ScreenplayRevision).where(
                            ScreenplayRevision.screenplay_id == _active_sp.id,
                            # before_chapters_json == after_chapters_json 说明还没真正重写
                            ScreenplayRevision.before_chapters_json
                                == ScreenplayRevision.after_chapters_json,
                        )
                    )).scalars().all()
                    for _rev in _pending:
                        if "pending" not in (_rev.diff_summary or "").lower():
                            continue
                        # asyncio.create_task：启动后台协程，不等待结果
                        # rewrite_in_background 会异步重写章节并更新 revision 行
                        asyncio.create_task(rewrite_in_background(
                            session_maker, session_id, _rev.id, _rev.trigger_description,
                        ))
        except Exception:  # noqa: BLE001
            pass  # background scheduling failure must never block the turn

        # ── 第二个 DB 会话：运行摘要器 ───────────────────
        # 用新会话而非上面那个，因为 commit 后数据已持久化，
        # 摘要器需要读取最新状态（含刚保存的消息）。
        # 【为什么摘要要在 SSE 流结束前运行？】
        # maybe_summarize 如果触发压缩，会删除旧消息、生成摘要，
        # 这些操作需要在本回合数据提交后才能看到最新数据。
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

            # v0.10: agent stream history compression. Walk all streams for
            # this session; if any has > threshold messages, fold the oldest
            # into a single summary row.
            # 压缩 Agent（Director/NPC）的流历史，防止历史无限增长
            try:
                from dzmm.db.models import AgentStream
                from dzmm.service.agents.streams import compress_if_needed
                stream_rows = (await s.execute(
                    select(AgentStream).where(AgentStream.session_id == session_id)
                )).scalars().all()
                for st in stream_rows:
                    # Director 保留更多历史（30 条触发，保留 10 条），NPC 少一些（25/8）
                    threshold = 30 if st.kind == "gm_director" else 25
                    keep = 10 if st.kind == "gm_director" else 8
                    await compress_if_needed(s, st.id, sum_client, threshold, keep)
                await s.commit()
            except Exception as e:  # noqa: BLE001
                log.warning("agent_stream compress failed: %s", e)

        # 查询刚保存的最后一条 assistant 消息的 id，通知前端
        async with session_maker() as _s2:
            _last_id = (
                await _s2.execute(
                    select(MessageRow.id)
                    .where(
                        MessageRow.session_id == session_id,
                        MessageRow.role == "assistant",
                    )
                    .order_by(MessageRow.id.desc())
                    .limit(1)  # 只取最新的一条
                )
            ).scalar_one_or_none()
        # done 事件：通知前端本回合完全结束，携带 assistant 消息 id（用于前端关联）
        yield {"event": "done", "data": json.dumps({"assistant_msg_id": _last_id})}

    # EventSourceResponse 把 async generator 包装成符合 SSE 协议的 HTTP 响应
    # 【SSE 协议格式】每个事件格式为：
    #   event: 事件类型\n
    #   data: JSON 字符串\n
    #   \n（空行表示事件结束）
    # sse_starlette 库自动处理这个格式，我们只需要 yield dict 即可
    return EventSourceResponse(event_stream())
