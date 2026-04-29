import json
from datetime import datetime, UTC

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.db.models import Character, CharState, NPC, PlotThread, Session as GameSession
from dzmm.parsing.events import TagComplete
from dzmm.parsing.repair import parse_loose_json


async def apply_tags(
    session: AsyncSession,
    session_id: int,
    current_turn: int,
    tags: list[TagComplete],
) -> None:
    """Mutate CharState and NPC rows based on parsed tags. Caller commits."""
    for tag in tags:
        if tag.name == "state_change":
            await _apply_state_change(session, session_id, tag.content)
        elif tag.name == "npc_update":
            await _apply_npc_update(session, session_id, current_turn, tag.content)
        elif tag.name == "plot_event":
            await _apply_plot_event(session, session_id, current_turn, tag.attrs, tag.content)
        elif tag.name == "character_xp":
            await _apply_character_xp(session, session_id, tag.attrs, tag.content)
        elif tag.name == "recall":
            await _apply_recall(session, session_id, tag.attrs, tag.content)


async def _apply_state_change(
    session: AsyncSession, session_id: int, raw: str
) -> None:
    payload = parse_loose_json(raw)
    if not payload:
        return

    cs = (
        await session.execute(
            select(CharState).where(CharState.session_id == session_id)
        )
    ).scalar_one_or_none()
    if cs is None:
        cs = CharState(session_id=session_id, stats_json="{}", inventory_json="[]")
        session.add(cs)

    stats = json.loads(cs.stats_json or "{}")
    inventory = json.loads(cs.inventory_json or "[]")

    for key, val in payload.items():
        if key == "inventory_add" and isinstance(val, list):
            inventory.extend(str(x) for x in val)
        elif key == "inventory_remove" and isinstance(val, list):
            for item in val:
                if item in inventory:
                    inventory.remove(item)
        elif isinstance(val, (int, float)):
            stats[key] = stats.get(key, 0) + val

    cs.stats_json = json.dumps(stats, ensure_ascii=False)
    cs.inventory_json = json.dumps(inventory, ensure_ascii=False)
    cs.updated_at = datetime.now(UTC).replace(tzinfo=None)


async def _apply_npc_update(
    session: AsyncSession, session_id: int, current_turn: int, raw: str
) -> None:
    payload = parse_loose_json(raw)
    name = payload.get("name")
    if not name:
        return

    npc = (
        await session.execute(
            select(NPC).where(NPC.session_id == session_id, NPC.name == name)
        )
    ).scalar_one_or_none()
    if npc is None:
        npc = NPC(
            session_id=session_id,
            name=name,
            description=payload.get("description", ""),
            favor=0,
            state=payload.get("state", "未知"),
            last_seen_turn=current_turn,
            notes_json="[]",
            purpose="",
            archetype="",
            affinity_json="{}",
            pinned=False,
        )
        session.add(npc)

    favor_delta = payload.get("favor_delta", 0)
    if isinstance(favor_delta, (int, float)):
        npc.favor += int(favor_delta)
    if "state" in payload:
        npc.state = str(payload["state"])
    if "description" in payload and not npc.description:
        npc.description = str(payload["description"])

    purpose = payload.get("purpose")
    if purpose is not None:
        npc.purpose = str(purpose)

    archetype = payload.get("archetype")
    if archetype is not None:
        npc.archetype = str(archetype)

    affinity_delta = payload.get("affinity")
    if isinstance(affinity_delta, dict):
        existing = json.loads(npc.affinity_json or "{}")
        if not isinstance(existing, dict):
            existing = {}
        for axis, delta in affinity_delta.items():
            if not isinstance(delta, (int, float)):
                continue
            axis_key = str(axis)
            existing[axis_key] = int(existing.get(axis_key, 0)) + int(delta)
        npc.affinity_json = json.dumps(existing, ensure_ascii=False)

    note = payload.get("note")
    if note:
        notes = json.loads(npc.notes_json or "[]")
        notes.append({"turn": current_turn, "text": str(note)})
        npc.notes_json = json.dumps(notes, ensure_ascii=False)
    npc.last_seen_turn = current_turn


async def _apply_recall(
    session: AsyncSession,
    session_id: int,
    attrs: dict[str, str],
    content: str,
) -> None:
    """GM-driven NPC recall: signals 'this NPC is back, re-inject full dossier
    next turn.' Appends the name to Session.recall_pending_json (a JSON list).
    The list is drained on the next prompt build."""
    name = (attrs.get("name") or "").strip()
    if not name:
        # Tolerate GM placing the name in body text as a fallback.
        name = (content or "").strip()
    if not name:
        return

    sess = await session.get(GameSession, session_id)
    if sess is None:
        return
    pending = json.loads(sess.recall_pending_json or "[]")
    if not isinstance(pending, list):
        pending = []
    if name not in pending:
        pending.append(name)
    sess.recall_pending_json = json.dumps(pending, ensure_ascii=False)


async def _apply_plot_event(
    session: AsyncSession,
    session_id: int,
    current_turn: int,
    attrs: dict[str, str],
    content: str,
) -> None:
    event_type = attrs.get("type", "major_event")
    try:
        importance = int(attrs.get("importance", "2"))
    except ValueError:
        importance = 2
    importance = max(1, min(3, importance))

    description = content.strip()
    if not description:
        return

    if event_type == "hook_resolved":
        thread_id_str = attrs.get("thread_id", "").strip()
        target = None
        if thread_id_str.isdigit():
            target = await session.get(PlotThread, int(thread_id_str))
        if target is None:
            target = (
                await session.execute(
                    select(PlotThread)
                    .where(
                        PlotThread.session_id == session_id,
                        PlotThread.status == "active",
                    )
                    .order_by(PlotThread.introduced_turn.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
        if target is not None:
            target.status = "resolved"
            target.resolution = description
        return

    thread = PlotThread(
        session_id=session_id,
        type=event_type,
        description=description,
        introduced_turn=current_turn,
        importance=importance,
        status="active",
    )
    session.add(thread)


async def _apply_character_xp(
    session: AsyncSession,
    session_id: int,
    attrs: dict[str, str],
    content: str,
) -> None:
    """Apply <character_xp delta="N"> by mutating Character.xp.

    Note: we don't auto-bump Character.level here; the frontend detects when
    the threshold is crossed and routes the user through /levelup, which
    advances the level and applies the player-chosen stat bonus.
    """
    try:
        delta = int(attrs.get("delta", "0"))
    except ValueError:
        return
    if delta == 0:
        return

    sess = await session.get(GameSession, session_id)
    if sess is None:
        return
    char = await session.get(Character, sess.character_id)
    if char is None:
        return
    char.xp = max(0, char.xp + delta)
