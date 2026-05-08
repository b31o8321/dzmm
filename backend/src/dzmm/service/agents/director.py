"""Director agent — long-term plot decision maker.

Runs every DIRECTOR_INTERVAL_TURNS turns OR on sync triggers (chapter
advance / plot_turn major / hp critical / hidden_event due). Output is
a short <plot_directive> block injected as a system note into Scene
and NPC actor prompts.
"""
from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.models.client import GenerationParams, ModelClient
from dzmm.prompts.director_v2_template import build_director_messages
from dzmm.service.agents.streams import (
    append_message,
    get_or_create_stream,
    load_history,
)

log = logging.getLogger(__name__)

STREAM_KIND_DIRECTOR = "gm_director"
DIRECTOR_HISTORY_MAX = 20

_PARAMS = GenerationParams(temperature=0.4, max_tokens=400)

_FALLBACK_DIRECTIVE = (
    "<plot_directive>\n"
    "- 本回合主推：推进当前主线事件，演出 ≤1 步可见进展\n"
    "- NPC 重点：（无）\n"
    "- 节奏：常态\n"
    "- 禁止：不要无视玩家本回合输入\n"
    "</plot_directive>"
)


async def run_director(
    s: AsyncSession,
    session_id: int,
    client: ModelClient,
    current_turn: int,
    snapshot: str,
) -> str:
    """Run the Director agent with the current snapshot and return its
    plot_directive output. Persists this turn's user/assistant pair into
    the gm_director stream. On any LLM failure, returns the fallback
    directive string and skips persistence.
    """
    stream = await get_or_create_stream(s, session_id, STREAM_KIND_DIRECTOR, "")
    history = await load_history(s, stream.id, max_messages=DIRECTOR_HISTORY_MAX)
    msgs = build_director_messages(history, snapshot)

    try:
        output, usage = await client.complete(msgs, _PARAMS)
    except Exception as exc:  # noqa: BLE001
        log.warning("director: LLM call failed: %s", exc)
        return _FALLBACK_DIRECTIVE

    text = (output or "").strip()
    if not text:
        log.warning("director: LLM returned empty output, using fallback")
        return _FALLBACK_DIRECTIVE

    await append_message(
        s, stream.id, current_turn, "user", snapshot,
        tokens_in=usage.input_tokens if usage else 0,
    )
    await append_message(
        s, stream.id, current_turn, "assistant", text,
        tokens_out=usage.output_tokens if usage else 0,
    )
    stream.last_run_turn = current_turn
    return text
