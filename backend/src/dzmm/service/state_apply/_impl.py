"""state_apply dispatcher — routes parsed tags to per-domain handlers.

After the r4-a refactor, every handler lives in its own per-tag module
under `state_apply/`. This file now contains only:
  - `apply_tags(...)` — the dispatcher
  - re-exports for legacy callers that imported handler symbols from `_impl`
    directly (kept stable for `from state_apply._impl import *` users).
"""

import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.db.models import NPC
from dzmm.parsing.events import TagComplete
from dzmm.service.state_apply.character_xp import _apply_character_xp
from dzmm.service.state_apply.hidden_event import _apply_hidden_event
from dzmm.service.state_apply.npc import (
    _NPC_REVEALABLE_FIELDS,
    _apply_npc_update,
    _auto_reveal_for_create,
    _parse_reveal_attr,
)
from dzmm.service.state_apply.npc_relation import _apply_npc_relation
from dzmm.service.state_apply.pc_goal import _apply_pc_goal
from dzmm.service.state_apply.pc_mood import _apply_pc_mood
from dzmm.service.state_apply.plot_event import _apply_plot_event
from dzmm.service.state_apply.recall import _apply_recall
from dzmm.service.state_apply.screenplay import (
    _apply_chapter_advance,
    _apply_ending,
    _apply_event_complete,
    _apply_plot_turn,
)
from dzmm.service.state_apply.doom import _apply_doom
from dzmm.service.state_apply.location import _apply_location_enter
from dzmm.service.state_apply.location_edge import _apply_location_edge
from dzmm.service.state_apply.location_item import _apply_location_item
from dzmm.service.state_apply.state_change import _apply_state_change
from dzmm.service.state_apply.world_time import _apply_time_advance
from dzmm.service.state_apply.factions import _apply_faction_create, _apply_faction_change

# Re-export for callers that imported these names from `_impl` directly
# (e.g. via the `from _impl import *` wildcard in __init__.py).
__all__ = [
    "_NPC_REVEALABLE_FIELDS",
    "_apply_npc_update",
    "_auto_reveal_for_create",
    "_parse_reveal_attr",
    "apply_tags",
]


async def apply_tags(
    session: AsyncSession,
    session_id: int,
    current_turn: int,
    tags: list[TagComplete],
) -> None:
    """Mutate CharState and NPC rows based on parsed tags. Caller commits."""
    topology_warnings: list[str] = []
    for tag in tags:
        if tag.name == "state_change":
            await _apply_state_change(session, session_id, tag.content)
        elif tag.name == "npc_update":
            await _apply_npc_update(
                session, session_id, current_turn, tag.attrs, tag.content
            )
        elif tag.name == "plot_event":
            await _apply_plot_event(session, session_id, current_turn, tag.attrs, tag.content)
        elif tag.name == "character_xp":
            await _apply_character_xp(session, session_id, tag.attrs, tag.content)
        elif tag.name == "recall":
            await _apply_recall(session, session_id, tag.attrs, tag.content)
        elif tag.name == "pc_goal":
            await _apply_pc_goal(session, session_id, current_turn, tag.attrs, tag.content)
        elif tag.name == "pc_mood":
            await _apply_pc_mood(session, session_id, tag.content)
        elif tag.name == "npc_relation":
            await _apply_npc_relation(
                session, session_id, current_turn, tag.attrs, tag.content
            )
        elif tag.name == "hidden_event":
            await _apply_hidden_event(
                session, session_id, current_turn, tag.attrs, tag.content
            )
        elif tag.name == "chapter_advance":
            await _apply_chapter_advance(session, session_id, tag.attrs, current_turn)
        elif tag.name == "event_complete":
            await _apply_event_complete(session, session_id, tag.attrs, current_turn)
        elif tag.name == "plot_turn":
            await _apply_plot_turn(session, session_id, tag.attrs, current_turn)
        elif tag.name == "ending":
            await _apply_ending(session, session_id, tag.attrs, current_turn)
        elif tag.name == "doom":
            await _apply_doom(session, session_id, tag.attrs)
        elif tag.name == "location_enter":
            w = await _apply_location_enter(
                session, session_id, current_turn, tag.attrs, tag.content
            )
            if w:
                topology_warnings.append(w)
        elif tag.name == "location_edge":
            await _apply_location_edge(session, session_id, tag.attrs, current_turn)
        elif tag.name == "location_item":
            await _apply_location_item(session, session_id, current_turn, tag.attrs, tag.content)
        elif tag.name == "time_advance":
            await _apply_time_advance(session, session_id, tag.attrs)
        elif tag.name == "faction_create":
            await _apply_faction_create(session, session_id, tag.attrs, tag.content)
        elif tag.name == "faction_change":
            await _apply_faction_change(session, session_id, tag.attrs)

    # v0.10 T12 — accumulate topology warnings into Session.topology_warning_json
    # so the next turn's _build_key_facts can drain & inject them into the prompt,
    # forcing the GM to emit the missing <location_edge>.
    if topology_warnings:
        from dzmm.db.models import Session as GameSession
        sess = await session.get(GameSession, session_id)
        if sess is not None:
            try:
                existing = json.loads(sess.topology_warning_json or "[]")
                if not isinstance(existing, list):
                    existing = []
            except (TypeError, ValueError):
                existing = []
            existing.extend(topology_warnings)
            sess.topology_warning_json = json.dumps(
                existing[-5:], ensure_ascii=False
            )

    # Post-pass: mark "appeared" for any NPC whose name shows up in this
    # turn's narrative / say / reaction / dice scene content (or in say /
    # reaction speaker= attrs). The GM only emits <npc_update> for first-time
    # named NPCs (iron rule 17) — pre-pinned NPCs from the wizard never get
    # a fresh npc_update, so without this pass their last_seen_turn stays
    # 0 and the panel keeps showing 未登场 even when they're actively in
    # the scene.
    await _bump_appearances_from_narrative(session, session_id, current_turn, tags)


async def _bump_appearances_from_narrative(
    session: AsyncSession,
    session_id: int,
    current_turn: int,
    tags: list[TagComplete],
) -> None:
    npcs = (
        await session.execute(
            select(NPC).where(NPC.session_id == session_id)
        )
    ).scalars().all()
    if not npcs:
        return

    # Concatenate every visible narrative-ish surface from the turn. Speaker
    # attrs go in too (a `<say speaker="丽莎">` is a clear appearance).
    haystacks: list[str] = []
    for tag in tags:
        if tag.name in ("narrative", "say", "reaction", "scene", "dice", "pc_action"):
            if tag.content:
                haystacks.append(tag.content)
            speaker = tag.attrs.get("speaker") if tag.attrs else None
            if speaker:
                haystacks.append(speaker)
    haystack = "\n".join(haystacks)
    if not haystack:
        return

    for npc in npcs:
        name = (npc.name or "").strip()
        if len(name) < 2:
            continue  # skip 1-char names — too risky to false-positive on
        # Match full name OR any 2+ char suffix (handles "记者王欣" → "王欣").
        matched = name in haystack
        if not matched and len(name) > 2:
            for start in range(1, len(name) - 1):
                if name[start:] in haystack:
                    matched = True
                    break
        if matched and (npc.last_seen_turn or 0) < current_turn:
            npc.last_seen_turn = current_turn
