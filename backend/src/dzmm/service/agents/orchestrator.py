"""v0.10 per-turn orchestrator.

Sequence per turn:
  1. Build session snapshot for Director triggers
  2. If Director should run -> run Director sync; else reuse last directive
  3. Stream Scene; collect narrative as it arrives
  4. After Scene completes, fan-out NPC actors in parallel; yield their tags
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.db.models import (
    AgentMessage,
    AgentStream,
    Character,
    NPC,
    Session as GameSession,
)
from dzmm.models.client import GenerationParams, Message, ModelClient
from dzmm.parsing.events import NarrativeDelta, ParseEvent
from dzmm.service.agents.director import (
    STREAM_KIND_DIRECTOR,
    run_director,
)
from dzmm.service.agents.npc_actor import run_npc_actor
from dzmm.service.agents.scene import run_scene
from dzmm.service.agents.streams import get_or_create_stream
from dzmm.service.agents.triggers import should_run_director

log = logging.getLogger(__name__)

NPC_MAX_PARALLEL = 4


async def _build_director_snapshot(
    s: AsyncSession, session_id: int, current_turn: int,
) -> str:
    """Compress current session state into a Director-readable text snapshot."""
    sess = await s.get(GameSession, session_id)
    if sess is None:
        return f"第 {current_turn} 回合（无 session 数据）"
    return "\n".join([
        f"# Snapshot @ turn {current_turn}",
        f"- doom: {sess.doom_score}",
        f"- scene_turn_count: {sess.scene_turn_count}",
    ])


async def _last_director_directive(s: AsyncSession, stream_id: int) -> str:
    """Read the most recent assistant message from the director stream as
    a fallback directive when this turn isn't running Director."""
    row = (await s.execute(
        select(AgentMessage)
        .where(AgentMessage.stream_id == stream_id,
               AgentMessage.role == "assistant")
        .order_by(AgentMessage.id.desc())
        .limit(1)
    )).scalar_one_or_none()
    if row is None:
        return (
            "<plot_directive>\n- 本回合主推：自然推进\n- NPC 重点：（无）\n"
            "- 节奏：常态\n- 禁止：（无）\n</plot_directive>"
        )
    return row.content


async def _select_on_stage_npcs(
    s: AsyncSession, session_id: int, current_turn: int, max_count: int,
) -> list[NPC]:
    """Pinned + recently-seen NPCs (top-K by last_seen_turn)."""
    pinned = (await s.execute(
        select(NPC).where(
            NPC.session_id == session_id, NPC.pinned == True,  # noqa: E712
        )
    )).scalars().all()
    recent = (await s.execute(
        select(NPC).where(
            NPC.session_id == session_id,
            NPC.last_seen_turn >= max(0, current_turn - 3),
        )
        .order_by(NPC.last_seen_turn.desc())
    )).scalars().all()
    seen: dict[int, NPC] = {}
    for n in pinned:
        seen[n.id] = n
    for n in recent:
        if len(seen) >= max_count:
            break
        seen.setdefault(n.id, n)
    return list(seen.values())[:max_count]


async def run_turn_v10(
    s: AsyncSession,
    *,
    session_id: int,
    user_action: str,
    scene_client: ModelClient,
    director_client: ModelClient,
    npc_client: ModelClient,
    world_md: str,
    character_md: str,
    live_state_text: str,
    key_facts: str,
    recent_messages: list[Message],
    scene_params: GenerationParams | None = None,
) -> AsyncIterator[ParseEvent]:
    """Per-turn coordination. Runs Director (sync if triggered) ->
    streams Scene -> fan-out NPC actors in parallel. Yields ParseEvents
    in arrival order."""
    sess = await s.get(GameSession, session_id)
    if sess is None:
        return
    current_turn = sess.turn_count + 1

    director_stream = await get_or_create_stream(
        s, session_id, STREAM_KIND_DIRECTOR, "",
    )

    cs_obj = type("S", (), {
        "turn_count": sess.turn_count,
        "doom_score": sess.doom_score,
        "scene_turn_count": sess.scene_turn_count,
        "chapter_advanced_last_turn": False,
        "major_plot_turn_last_turn": False,
        "hp": 99,
        "sanity": 99,
        "hidden_event_due": False,
    })()

    fire, reason = should_run_director(director_stream, cs_obj, current_turn)
    if fire:
        log.info("director firing (reason=%s) at turn %d", reason, current_turn)
        snapshot = await _build_director_snapshot(s, session_id, current_turn)
        directive = await run_director(
            s, session_id, director_client, current_turn, snapshot,
        )
    else:
        directive = await _last_director_directive(s, director_stream.id)

    # PC name from Character row (anti-drift)
    pc_name = "PC"
    char = await s.get(Character, sess.character_id)
    if char and char.name:
        pc_name = char.name

    narrative_buf: list[str] = []
    async for ev in run_scene(
        client=scene_client,
        pc_name=pc_name,
        plot_directive=directive,
        world_md=world_md, character_md=character_md,
        live_state_text=live_state_text, key_facts=key_facts,
        recent_messages=recent_messages,
        current_action=user_action,
        params=scene_params,
    ):
        if isinstance(ev, NarrativeDelta):
            narrative_buf.append(ev.text)
        yield ev

    scene_narrative = "".join(narrative_buf)

    # NPC fan-out (parallel)
    on_stage = await _select_on_stage_npcs(
        s, session_id, current_turn, NPC_MAX_PARALLEL,
    )
    if on_stage:
        results = await asyncio.gather(*[
            run_npc_actor(
                s, npc=npc, session_id=session_id,
                plot_directive=directive, scene_narrative=scene_narrative,
                user_action=user_action, client=npc_client,
                current_turn=current_turn,
            )
            for npc in on_stage
        ], return_exceptions=True)
        for events in results:
            if isinstance(events, Exception):
                log.warning("npc_actor failed: %s", events)
                continue
            for ev in events:
                yield ev
