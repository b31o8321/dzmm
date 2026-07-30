# ============================================================
# NPC 主动行动接口（NPC-initiated Turn）
# ============================================================
# 【模块作用】
#   提供单个 SSE 流式接口：
#   - POST /sessions/{id}/npc_tick
#
# 【什么是 NPC Tick？】
#   普通的 /turn 接口由玩家主动触发（玩家输入行动 → GM 响应）。
#   NPC Tick 是反过来的：NPC 主动找玩家接触，不需要玩家先说话。
#
#   典型触发场景：
#   - GM 在上一回合输出了 `npc_initiative` 事件标签（某 NPC 要主动行动）
#   - 前端接收到该事件后，调用 POST /npc_tick 触发 NPC 的主动行为
#
#   实现方式：
#   把 NPC 的主动行动编码成一条伪造的"玩家行动"文字
#   （格式：「【NPC主动行动】{npc_name} 主动找到了 PC...」），
#   然后正常调用 run_turn 处理这条行动，GM 会根据 NPC 的档案和动机
#   演出这场 NPC 驱动的互动。
#
# 【为什么用这种方式而不单独实现？】
#   run_turn 已经包含了完整的上下文构建（NPC 档案/剧情线/历史摘要/状态标签处理）。
#   复用它可以确保 NPC Tick 和普通回合在机制上完全一致，不需要维护两套逻辑。
# ============================================================
"""POST /sessions/{id}/npc_tick — NPC-initiated turn stream.

Called by the frontend after receiving a `npc_initiative` event. Accepts
{npc_name} and streams a full GM turn where the NPC proactively contacts PC.
"""
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse  # SSE 响应封装库

from dzmm.api.routes_sessions._common import (
    build_client,
    get_session_maker_dep,
)
from dzmm.db.models import ModelConfig, Session as GameSession
from dzmm.parsing.events import NarrativeDelta, ParseError, TagComplete
from dzmm.service.game import run_turn

router = APIRouter(prefix="/sessions", tags=["sessions"])

# 伪造的"玩家行动"模板，用于告诉 GM 这是 NPC 主动行动的场景
# {npc_name} 会在运行时被替换为实际的 NPC 名字
_NPC_TICK_TEMPLATE = (
    "【NPC主动行动】{npc_name} 主动找到了 PC，请 GM 演出这场互动。"
    "（{npc_name} 按其档案中的动机/情绪自然发起接触；PC 无需事先声明动作，场景完全由 NPC 驱动）"
)


# ── 请求体模型 ─────────────────────────────────────────────────────
class NpcTickRequest(BaseModel):
    # 前端告诉后端哪个 NPC 要主动行动
    npc_name: str


# ── POST /sessions/{session_id}/npc_tick ─────────────────────────────
@router.post("/{session_id}/npc_tick")
async def npc_tick(
    session_id: int,
    body: NpcTickRequest,
    session_maker=Depends(get_session_maker_dep),
    # 用 session_maker 而不是 get_session_dep，原因同 turn.py：
    # 流式响应需要自己管理数据库会话的生命周期
):
    """Stream a NPC-initiated GM turn (no player input required)."""

    # _event_stream 是异步生成器，逐条产出 SSE 事件
    async def _event_stream() -> AsyncIterator[dict]:
        async with session_maker() as s:
            # 校验存档和模型配置存在
            sess = await s.get(GameSession, session_id)
            if sess is None:
                yield {"event": "error", "data": json.dumps({"message": "session not found"})}
                return
            cfg = await s.get(ModelConfig, sess.gm_model_config_id)
            if cfg is None:
                yield {"event": "error", "data": json.dumps({"message": "model config not found"})}
                return
            client = build_client(cfg)

            # 把 NPC 名字填入模板，生成伪造的"玩家行动"文字
            # .strip() 去除名字两端的空格（防止前端传入的名字有多余空格导致 NPC 找不到）
            action = _NPC_TICK_TEMPLATE.format(npc_name=body.npc_name.strip())

            # 叙事缓冲区（同 turn.py，积累 20 字符后批量推送，减少 SSE 帧数）
            narrative_buf: list[str] = []
            flush_size = 20

            # 调用 run_turn（复用普通回合逻辑）处理这条 NPC 主动行动
            # 注意：这里没有传 session_maker，所以 run_turn 不能在内部开新 DB 会话
            async for ev in run_turn(s, session_id, action, client):
                if isinstance(ev, NarrativeDelta):
                    # 叙事片段：加入缓冲，满足字数阈值就推送
                    narrative_buf.append(ev.text)
                    if sum(len(x) for x in narrative_buf) >= flush_size:
                        yield {
                            "event": "narrative",
                            "data": json.dumps({"text": "".join(narrative_buf)}, ensure_ascii=False),
                        }
                        narrative_buf = []  # 推送后清空缓冲

                elif isinstance(ev, TagComplete):
                    # 结构化标签：先推出缓冲中的叙事文字，再推标签事件
                    if narrative_buf:
                        yield {
                            "event": "narrative",
                            "data": json.dumps({"text": "".join(narrative_buf)}, ensure_ascii=False),
                        }
                        narrative_buf = []
                    yield {
                        "event": "tag",
                        "data": json.dumps(
                            {"name": ev.name, "attrs": dict(ev.attrs or {}),
                             "content": ev.content or ""},
                            ensure_ascii=False,
                        ),
                    }

                elif isinstance(ev, ParseError):
                    # 解析错误：直接推送错误事件（不清空缓冲，继续处理后续输出）
                    yield {
                        "event": "parse_error",
                        "data": json.dumps({"message": ev.message}, ensure_ascii=False),
                    }

            # run_turn 结束后：推出缓冲区剩余的叙事文字
            if narrative_buf:
                yield {
                    "event": "narrative",
                    "data": json.dumps({"text": "".join(narrative_buf)}, ensure_ascii=False),
                }

            # 提交本回合数据库变更
            await s.commit()
            # done 事件：通知前端 NPC Tick 完成
            yield {"event": "done", "data": json.dumps({"ok": True})}

    # 把异步生成器包装成 SSE HTTP 响应返回
    return EventSourceResponse(_event_stream())
