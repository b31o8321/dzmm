"""Per-NPC stateful actor — produces <say> + <npc_update> for one NPC."""
from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.models.client import GenerationParams, ModelClient
from dzmm.parsing.events import ParseEvent, TagComplete
from dzmm.parsing.stream_parser import StreamingTagParser
from dzmm.prompts.npc_actor_template import build_npc_actor_messages
from dzmm.service.agents.streams import (
    append_message,
    get_or_create_stream,
    load_history,
)

log = logging.getLogger(__name__)

STREAM_KIND_NPC = "npc"
NPC_HISTORY_MAX = 15

_PARAMS = GenerationParams(temperature=0.75, max_tokens=300)
_KEPT_TAGS = {"say", "npc_update"}


async def run_npc_actor(
    s: AsyncSession,
    npc,
    session_id: int,
    plot_directive: str,
    scene_narrative: str,
    user_action: str,
    client: ModelClient,
    current_turn: int,
) -> list[ParseEvent]:
    """Run one NPC's stateful agent. Returns parsed <say> + <npc_update>
    events (or [] for noop / failure / empty output). Persists this turn
    into the NPC's stream regardless — even noop is signal."""
    stream = await get_or_create_stream(s, session_id, STREAM_KIND_NPC, npc.name)
    history = await load_history(s, stream.id, max_messages=NPC_HISTORY_MAX)

    msgs = build_npc_actor_messages(
        npc=npc, history=history, plot_directive=plot_directive,
        scene_narrative=scene_narrative, user_action=user_action,
    )

    try:
        output, usage = await client.complete(msgs, _PARAMS)
    except Exception as exc:  # noqa: BLE001
        log.warning("npc_actor(%s): LLM failed: %s", npc.name, exc)
        return []

    text = (output or "").strip()
    if not text:
        return []

    # Persist regardless of parsed events — the user-side snapshot
    # is what we need for next-turn context, not the cleaned events.
    turn_input = (
        f"# directive\n{plot_directive[:200]}\n\n"
        f"# scene\n{scene_narrative[:400]}\n\n"
        f"# user\n{user_action}"
    )
    await append_message(s, stream.id, current_turn, "user", turn_input,
                         tokens_in=usage.input_tokens if usage else 0)
    await append_message(s, stream.id, current_turn, "assistant", text,
                         tokens_out=usage.output_tokens if usage else 0)
    stream.last_run_turn = current_turn

    if "<noop" in text:
        return []

    parser = StreamingTagParser()
    events: list[ParseEvent] = []
    for ev in parser.feed(text):
        if isinstance(ev, TagComplete) and ev.name in _KEPT_TAGS:
            if ev.name == "say":
                ev.attrs.setdefault("speaker", npc.name)
            elif ev.name == "npc_update":
                ev.attrs["name"] = npc.name
            events.append(ev)
    for ev in parser.finish():
        if isinstance(ev, TagComplete) and ev.name in _KEPT_TAGS:
            if ev.name == "say":
                ev.attrs.setdefault("speaker", npc.name)
            elif ev.name == "npc_update":
                ev.attrs["name"] = npc.name
            events.append(ev)
    return events
