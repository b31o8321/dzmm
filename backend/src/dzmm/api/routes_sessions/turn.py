"""Turn endpoints: POST /turn (SSE), DELETE /last_turn, POST /warmup.

The SSE handler streams NarrativeDelta/TagComplete/ParseError events from
`run_turn`, batching narrative chunks for ~50ms or 20 chars to reduce
flush thrash. Tests monkeypatch `dzmm.api.routes_sessions.build_client`;
the package __init__ mirrors that write down to `build_client` here so
patching keeps working through the run_turn / warmup / summarizer paths."""
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException
from sse_starlette.sse import EventSourceResponse
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
from dzmm.service.summarizer import maybe_summarize
from sqlalchemy import select

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.post("/{session_id}/warmup", status_code=202)
async def warmup_model(
    session_id: int,
    session_maker = Depends(get_session_maker_dep),
):
    """Fire-and-forget: load the GM model into the runtime so the first turn
    doesn't pay the cold load cost (typically 5-20s for a 7B local model)."""
    import asyncio as _asyncio

    async def _do_warmup():
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
                async for _ in client.stream(
                    [Message(role="user", content="ok")],
                    GenerationParams(max_tokens=1, temperature=0.0),
                ):
                    pass
            except Exception:
                pass  # warmup failures are non-fatal

    _asyncio.create_task(_do_warmup())
    return {"status": "started"}


@router.delete("/{session_id}/last_turn", status_code=204)
async def delete_last_turn(
    session_id: int, s: AsyncSession = Depends(get_session_dep)
):
    """Remove the most recent user/assistant message pair and decrement
    turn_count. Frontend uses this for the regenerate / edit-last actions."""
    sess = await s.get(GameSession, session_id)
    if sess is None:
        raise HTTPException(404, "session not found")
    if sess.turn_count <= 0:
        return  # nothing to delete

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
    sess.turn_count = max(0, sess.turn_count - 1)
    await s.commit()


@router.post("/{session_id}/turn")
async def take_turn(
    session_id: int,
    body: TurnRequest,
    session_maker = Depends(get_session_maker_dep),
):
    async def event_stream() -> AsyncIterator[dict]:
        async with session_maker() as s:
            sess = await s.get(GameSession, session_id)
            if sess is None:
                yield {"event": "error",
                       "data": json.dumps({"message": "session not found"})}
                return
            cfg = await s.get(ModelConfig, sess.gm_model_config_id)
            client = build_client(cfg)

            import time as _time
            narrative_buf: list[str] = []
            last_flush = _time.monotonic()
            FLUSH_CHARS = 20
            FLUSH_INTERVAL = 0.05  # 50ms

            def _flush_narrative():
                if narrative_buf:
                    payload = "".join(narrative_buf)
                    narrative_buf.clear()
                    return {"event": "narrative",
                            "data": json.dumps({"text": payload}, ensure_ascii=False)}
                return None

            async for ev in run_turn(s, session_id, body.action, client):
                if isinstance(ev, NarrativeDelta):
                    narrative_buf.append(ev.text)
                    now = _time.monotonic()
                    total = sum(len(x) for x in narrative_buf)
                    if total >= FLUSH_CHARS or (now - last_flush) >= FLUSH_INTERVAL:
                        out = _flush_narrative()
                        if out:
                            yield out
                        last_flush = now
                elif isinstance(ev, TagComplete):
                    out = _flush_narrative()
                    if out:
                        yield out
                    last_flush = _time.monotonic()
                    yield {"event": "tag",
                           "data": json.dumps({"name": ev.name, "attrs": ev.attrs,
                                               "content": ev.content},
                                              ensure_ascii=False)}
                elif isinstance(ev, ParseError):
                    out = _flush_narrative()
                    if out:
                        yield out
                    yield {"event": "parse_error",
                           "data": json.dumps({"message": ev.message},
                                              ensure_ascii=False)}

            # Flush any tail buffer before commit + cleanup.
            out = _flush_narrative()
            if out:
                yield out

            await s.commit()

        async with session_maker() as s:
            sess = await s.get(GameSession, session_id)
            sum_cfg = await s.get(ModelConfig, sess.summarizer_model_config_id)
            sum_client = build_client(sum_cfg)
            try:
                ran = await maybe_summarize(s, session_id, sum_client)
                if ran:
                    await s.commit()
            except Exception as e:  # noqa: BLE001
                yield {"event": "summarize_error",
                       "data": json.dumps({"message": str(e)}, ensure_ascii=False)}

        yield {"event": "done", "data": "{}"}

    return EventSourceResponse(event_stream())
