"""POST /sessions/{id}/npc_tick — NPC-initiated turn stream.

Called by the frontend after receiving a `npc_initiative` event. Accepts
{npc_name} and streams a full GM turn where the NPC proactively contacts PC.
"""
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse
from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.api.routes_sessions._common import (
    build_client,
    get_session_dep,
    get_session_maker_dep,
)
from dzmm.db.models import ModelConfig, Session as GameSession
from dzmm.parsing.events import NarrativeDelta, ParseError, TagComplete
from dzmm.service.game import run_turn

router = APIRouter(prefix="/sessions", tags=["sessions"])

_NPC_TICK_TEMPLATE = (
    "【NPC主动行动】{npc_name} 主动找到了 PC，请 GM 演出这场互动。"
    "（{npc_name} 按其档案中的动机/情绪自然发起接触；PC 无需事先声明动作，场景完全由 NPC 驱动）"
)


class NpcTickRequest(BaseModel):
    npc_name: str


@router.post("/{session_id}/npc_tick")
async def npc_tick(
    session_id: int,
    body: NpcTickRequest,
    session_maker=Depends(get_session_maker_dep),
):
    """Stream a NPC-initiated GM turn (no player input required)."""

    async def _event_stream() -> AsyncIterator[dict]:
        async with session_maker() as s:
            sess = await s.get(GameSession, session_id)
            if sess is None:
                yield {"event": "error", "data": json.dumps({"message": "session not found"})}
                return
            cfg = await s.get(ModelConfig, sess.gm_model_config_id)
            if cfg is None:
                yield {"event": "error", "data": json.dumps({"message": "model config not found"})}
                return
            client = build_client(cfg)

            action = _NPC_TICK_TEMPLATE.format(npc_name=body.npc_name.strip())

            narrative_buf: list[str] = []
            flush_size = 20

            async for ev in run_turn(s, session_id, action, client):
                if isinstance(ev, NarrativeDelta):
                    narrative_buf.append(ev.text)
                    if sum(len(x) for x in narrative_buf) >= flush_size:
                        yield {
                            "event": "narrative",
                            "data": json.dumps({"text": "".join(narrative_buf)}, ensure_ascii=False),
                        }
                        narrative_buf = []
                elif isinstance(ev, TagComplete):
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
                    yield {
                        "event": "parse_error",
                        "data": json.dumps({"message": ev.message}, ensure_ascii=False),
                    }

            if narrative_buf:
                yield {
                    "event": "narrative",
                    "data": json.dumps({"text": "".join(narrative_buf)}, ensure_ascii=False),
                }

            await s.commit()
            yield {"event": "done", "data": json.dumps({"ok": True})}

    return EventSourceResponse(_event_stream())
