"""v0.10.5 turn-effect rollback via state snapshots.

`take_snapshot` is called by run_turn at turn START (before LLM); it
serializes every mutable field that this turn's GM/NPC outputs might
modify. The snapshot is stored on MessageRow.snapshot_json.

`restore_snapshot` is called by delete_last_turn; it reads the snapshot
and reverses everything: restores mutable fields, deletes rows that
were created during the turn (matched by 'rows not in snapshot id sets'),
and re-activates rows that were resolved/marked done during the turn.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.db.models import (
    CharState,
    Faction,
    HiddenEvent,
    Location,
    LocationEdge,
    NPC,
    PCGoal,
    PlotThread,
    Screenplay,
    Session as GameSession,
)

log = logging.getLogger(__name__)


async def take_snapshot(s: AsyncSession, session_id: int) -> dict[str, Any]:
    """Serialize all mutable state for this turn into a JSON-able dict."""
    sess = await s.get(GameSession, session_id)
    cs = (await s.execute(
        select(CharState).where(CharState.session_id == session_id)
    )).scalar_one_or_none()
    sp = (await s.execute(
        select(Screenplay).where(
            Screenplay.session_id == session_id,
            Screenplay.status == "active",
        ).order_by(Screenplay.version.desc())
    )).scalars().first()
    npcs = (await s.execute(
        select(NPC).where(NPC.session_id == session_id)
    )).scalars().all()
    locations = (await s.execute(
        select(Location).where(Location.session_id == session_id)
    )).scalars().all()
    edges = (await s.execute(
        select(LocationEdge).where(LocationEdge.session_id == session_id)
    )).scalars().all()
    hidden = (await s.execute(
        select(HiddenEvent).where(HiddenEvent.session_id == session_id)
    )).scalars().all()
    factions = (await s.execute(
        select(Faction).where(Faction.session_id == session_id)
    )).scalars().all()
    threads = (await s.execute(
        select(PlotThread).where(PlotThread.session_id == session_id)
    )).scalars().all()
    goals = (await s.execute(
        select(PCGoal).where(PCGoal.session_id == session_id)
    )).scalars().all()

    return {
        "session": {
            "doom_score": sess.doom_score if sess else 0,
            "scene_turn_count": sess.scene_turn_count if sess else 0,
            "turn_count": sess.turn_count if sess else 0,
            "world_time_json": (sess.world_time_json if sess else "") or "",
            "pc_mood_json": (sess.pc_mood_json if sess else "") or "",
            "recall_pending_json": (sess.recall_pending_json if sess else "") or "",
            "topology_warning_json": (sess.topology_warning_json if sess else "") or "",
        },
        "char_state": {
            "stats_json": cs.stats_json or "" if cs else "",
            "inventory_json": cs.inventory_json or "" if cs else "",
        } if cs else None,
        "screenplay": {
            "id": sp.id, "current_chapter": sp.current_chapter,
            "completed_events_json": sp.completed_events_json or "",
            "chapters_json": sp.chapters_json or "",
            "status": sp.status,
        } if sp else None,
        "npcs": [
            {
                "id": n.id, "favor": n.favor, "emotion_json": n.emotion_json or "",
                "affinity_json": n.affinity_json or "", "state": n.state or "",
                "last_seen_turn": n.last_seen_turn,
                "current_location": n.current_location or "",
                "last_initiative_turn": n.last_initiative_turn,
                "notes_json": n.notes_json or "",
                "revealed_json": n.revealed_json or "",
                "faction_id": n.faction_id,
            } for n in npcs
        ],
        "npc_ids": sorted(n.id for n in npcs),
        "locations": [
            {
                "id": loc.id, "is_current": bool(loc.is_current),
                "last_visited_turn": loc.last_visited_turn,
                "items_json": loc.items_json or "",
            } for loc in locations
        ],
        "location_ids": sorted(loc.id for loc in locations),
        "location_edge_ids": sorted(e.id for e in edges),
        "hidden_events": [
            {"id": h.id, "status": h.status} for h in hidden
        ],
        "hidden_event_ids": sorted(h.id for h in hidden),
        "factions": [
            {"id": f.id, "pc_reputation": f.pc_reputation} for f in factions
        ],
        "faction_ids": sorted(f.id for f in factions),
        "plot_threads": [
            {"id": t.id, "status": t.status} for t in threads
        ],
        "plot_thread_ids": sorted(t.id for t in threads),
        "pc_goals": [
            {"id": g.id, "status": g.status} for g in goals
        ],
        "pc_goal_ids": sorted(g.id for g in goals),
    }


async def restore_snapshot(
    s: AsyncSession, session_id: int, snap: dict[str, Any],
) -> None:
    """Reverse all turn effects by:
    1) Restoring mutable fields on rows that existed at turn START
    2) Deleting rows created during the turn (id not in snapshot's id sets)
    3) Restoring statuses for rows that were resolved/done during the turn
    """
    if not snap:
        return

    # --- Session ---
    sess = await s.get(GameSession, session_id)
    if sess is not None and snap.get("session"):
        ss = snap["session"]
        sess.doom_score = ss.get("doom_score", sess.doom_score)
        sess.scene_turn_count = ss.get("scene_turn_count", sess.scene_turn_count)
        sess.turn_count = ss.get("turn_count", sess.turn_count)
        sess.world_time_json = ss.get("world_time_json", sess.world_time_json)
        sess.pc_mood_json = ss.get("pc_mood_json", sess.pc_mood_json)
        sess.recall_pending_json = ss.get("recall_pending_json", sess.recall_pending_json)
        sess.topology_warning_json = ss.get("topology_warning_json", sess.topology_warning_json)

    # --- CharState ---
    if snap.get("char_state"):
        cs = (await s.execute(
            select(CharState).where(CharState.session_id == session_id)
        )).scalar_one_or_none()
        if cs is not None:
            cs.stats_json = snap["char_state"].get("stats_json", cs.stats_json)
            cs.inventory_json = snap["char_state"].get("inventory_json", cs.inventory_json)

    # --- Screenplay ---
    if snap.get("screenplay"):
        sp_snap = snap["screenplay"]
        sp = await s.get(Screenplay, sp_snap["id"])
        if sp is not None:
            sp.current_chapter = sp_snap.get("current_chapter", sp.current_chapter)
            sp.completed_events_json = sp_snap.get("completed_events_json", sp.completed_events_json)
            sp.chapters_json = sp_snap.get("chapters_json", sp.chapters_json)
            sp.status = sp_snap.get("status", sp.status)

    # --- NPCs: restore mutable fields for snapshot ids; delete new NPCs ---
    snap_npcs_by_id = {n["id"]: n for n in snap.get("npcs", [])}
    snap_npc_ids = set(snap.get("npc_ids", []))
    current_npcs = (await s.execute(
        select(NPC).where(NPC.session_id == session_id)
    )).scalars().all()
    for n in current_npcs:
        if n.id in snap_npcs_by_id:
            d = snap_npcs_by_id[n.id]
            n.favor = d.get("favor", n.favor)
            n.emotion_json = d.get("emotion_json", n.emotion_json)
            n.affinity_json = d.get("affinity_json", n.affinity_json)
            n.state = d.get("state", n.state)
            n.last_seen_turn = d.get("last_seen_turn", n.last_seen_turn)
            n.current_location = d.get("current_location", n.current_location)
            n.last_initiative_turn = d.get("last_initiative_turn", n.last_initiative_turn)
            n.notes_json = d.get("notes_json", n.notes_json)
            n.revealed_json = d.get("revealed_json", n.revealed_json)
            n.faction_id = d.get("faction_id", n.faction_id)
    # Delete NPCs created this turn (id not in snapshot)
    new_npc_ids = [n.id for n in current_npcs if n.id not in snap_npc_ids]
    if new_npc_ids:
        await s.execute(delete(NPC).where(NPC.id.in_(new_npc_ids)))

    # --- Locations ---
    snap_locs_by_id = {l["id"]: l for l in snap.get("locations", [])}
    snap_loc_ids = set(snap.get("location_ids", []))
    current_locs = (await s.execute(
        select(Location).where(Location.session_id == session_id)
    )).scalars().all()
    for loc in current_locs:
        if loc.id in snap_locs_by_id:
            d = snap_locs_by_id[loc.id]
            loc.is_current = d.get("is_current", loc.is_current)
            loc.last_visited_turn = d.get("last_visited_turn", loc.last_visited_turn)
            loc.items_json = d.get("items_json", loc.items_json)
    # Delete locations created this turn — but first delete dangling LocationEdges
    new_loc_ids = [loc.id for loc in current_locs if loc.id not in snap_loc_ids]
    if new_loc_ids:
        await s.execute(delete(LocationEdge).where(
            (LocationEdge.from_loc_id.in_(new_loc_ids)) | (LocationEdge.to_loc_id.in_(new_loc_ids))
        ))
        await s.execute(delete(Location).where(Location.id.in_(new_loc_ids)))

    # --- LocationEdges: delete edges created this turn (id not in snapshot) ---
    snap_edge_ids = set(snap.get("location_edge_ids", []))
    current_edge_ids = (await s.execute(
        select(LocationEdge.id).where(LocationEdge.session_id == session_id)
    )).scalars().all()
    new_edge_ids = [eid for eid in current_edge_ids if eid not in snap_edge_ids]
    if new_edge_ids:
        await s.execute(delete(LocationEdge).where(LocationEdge.id.in_(new_edge_ids)))

    # --- HiddenEvents ---
    snap_hidden_by_id = {h["id"]: h for h in snap.get("hidden_events", [])}
    snap_hidden_ids = set(snap.get("hidden_event_ids", []))
    current_hidden = (await s.execute(
        select(HiddenEvent).where(HiddenEvent.session_id == session_id)
    )).scalars().all()
    for h in current_hidden:
        if h.id in snap_hidden_by_id:
            h.status = snap_hidden_by_id[h.id].get("status", h.status)
    new_hidden_ids = [h.id for h in current_hidden if h.id not in snap_hidden_ids]
    if new_hidden_ids:
        await s.execute(delete(HiddenEvent).where(HiddenEvent.id.in_(new_hidden_ids)))

    # --- Factions: restore pc_reputation; delete created-this-turn ---
    snap_facs_by_id = {f["id"]: f for f in snap.get("factions", [])}
    snap_fac_ids = set(snap.get("faction_ids", []))
    current_factions = (await s.execute(
        select(Faction).where(Faction.session_id == session_id)
    )).scalars().all()
    for f in current_factions:
        if f.id in snap_facs_by_id:
            f.pc_reputation = snap_facs_by_id[f.id].get("pc_reputation", f.pc_reputation)
    new_fac_ids = [f.id for f in current_factions if f.id not in snap_fac_ids]
    if new_fac_ids:
        await s.execute(delete(Faction).where(Faction.id.in_(new_fac_ids)))

    # --- PlotThreads: restore status; delete created-this-turn ---
    snap_threads_by_id = {t["id"]: t for t in snap.get("plot_threads", [])}
    snap_thread_ids = set(snap.get("plot_thread_ids", []))
    current_threads = (await s.execute(
        select(PlotThread).where(PlotThread.session_id == session_id)
    )).scalars().all()
    for t in current_threads:
        if t.id in snap_threads_by_id:
            t.status = snap_threads_by_id[t.id].get("status", t.status)
    new_thread_ids = [t.id for t in current_threads if t.id not in snap_thread_ids]
    if new_thread_ids:
        await s.execute(delete(PlotThread).where(PlotThread.id.in_(new_thread_ids)))

    # --- PCGoals: restore status; delete created-this-turn ---
    snap_goals_by_id = {g["id"]: g for g in snap.get("pc_goals", [])}
    snap_goal_ids = set(snap.get("pc_goal_ids", []))
    current_goals = (await s.execute(
        select(PCGoal).where(PCGoal.session_id == session_id)
    )).scalars().all()
    for g in current_goals:
        if g.id in snap_goals_by_id:
            g.status = snap_goals_by_id[g.id].get("status", g.status)
    new_goal_ids = [g.id for g in current_goals if g.id not in snap_goal_ids]
    if new_goal_ids:
        await s.execute(delete(PCGoal).where(PCGoal.id.in_(new_goal_ids)))


def serialize_snapshot(snap: dict[str, Any]) -> str:
    return json.dumps(snap, ensure_ascii=False)


def deserialize_snapshot(raw: str) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return {}
