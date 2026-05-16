"""GET /sessions/{session_id}/world_state — open-world runtime data."""
import json
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.api.routes_sessions._common import get_session_dep
from dzmm.db.models import (
    Session as GameSession,
    WorldLocation,
    WorldFaction,
    WorldNPCTemplate,
    WorldEvent,
    Campaign,
    SessionLocationState,
    SessionFactionState,
    SessionNpcState,
    SessionEventState,
    SessionCampaignState,
)

router = APIRouter(prefix="/sessions", tags=["sessions"])


def _safe_json(text: str, default):
    try:
        return json.loads(text or "[]")
    except (TypeError, ValueError):
        return default


@router.get("/{session_id}/world_state")
async def get_world_state(session_id: int, s: AsyncSession = Depends(get_session_dep)):
    sess = await s.get(GameSession, session_id)
    if sess is None:
        raise HTTPException(404, "session not found")

    framework_id = sess.framework_id
    if not framework_id:
        # Legacy session — return empty payload
        return {
            "locations": [],
            "factions": [],
            "npcs": [],
            "events": [],
            "pc_location_id": None,
            "campaign": None,
        }

    # ── Locations ──────────────────────────────────────────────────────────
    loc_rows = (await s.execute(
        select(WorldLocation).where(WorldLocation.framework_id == framework_id)
        .order_by(WorldLocation.id)
    )).scalars().all()

    # Build dict of session overrides keyed by location_id
    loc_states: dict[int, SessionLocationState] = {}
    if loc_rows:
        loc_state_rows = (await s.execute(
            select(SessionLocationState).where(
                SessionLocationState.session_id == session_id,
                SessionLocationState.location_id.in_([l.id for l in loc_rows]),
            )
        )).scalars().all()
        loc_states = {r.location_id: r for r in loc_state_rows}

    locations = []
    for loc in loc_rows:
        connections = _safe_json(loc.connections_json, [])
        state_row = loc_states.get(loc.id)
        entry = {
            "id": loc.id,
            "framework_id": loc.framework_id,
            "name": loc.name,
            "description_md": loc.description_md,
            "location_type": loc.location_type,
            "connections": connections,
            "initial_state": loc.initial_state,
        }
        if state_row is not None:
            entry["session_status"] = state_row.status
        locations.append(entry)

    # ── Factions ───────────────────────────────────────────────────────────
    faction_rows = (await s.execute(
        select(WorldFaction).where(WorldFaction.framework_id == framework_id)
        .order_by(WorldFaction.id)
    )).scalars().all()

    faction_states: dict[int, SessionFactionState] = {}
    if faction_rows:
        fs_rows = (await s.execute(
            select(SessionFactionState).where(
                SessionFactionState.session_id == session_id,
                SessionFactionState.faction_id.in_([f.id for f in faction_rows]),
            )
        )).scalars().all()
        faction_states = {r.faction_id: r for r in fs_rows}

    factions = []
    for fac in faction_rows:
        fs = faction_states.get(fac.id)
        factions.append({
            "id": fac.id,
            "name": fac.name,
            "description_md": fac.description_md,
            "tension": fs.tension if fs else 0,
            "pc_reputation": fs.pc_reputation if fs else 0,
        })

    # ── NPCs (revealed only) ───────────────────────────────────────────────
    npc_templates = (await s.execute(
        select(WorldNPCTemplate).where(WorldNPCTemplate.framework_id == framework_id)
        .order_by(WorldNPCTemplate.id)
    )).scalars().all()

    npc_states: dict[int, SessionNpcState] = {}
    if npc_templates:
        ns_rows = (await s.execute(
            select(SessionNpcState).where(
                SessionNpcState.session_id == session_id,
                SessionNpcState.npc_template_id.in_([n.id for n in npc_templates]),
            )
        )).scalars().all()
        npc_states = {r.npc_template_id: r for r in ns_rows}

    npcs = []
    for tmpl in npc_templates:
        ns = npc_states.get(tmpl.id)
        # Only surface revealed NPCs (no state row = not revealed)
        if ns is None or not ns.is_revealed:
            continue
        npcs.append({
            "npc_template_id": tmpl.id,
            "name": tmpl.name,
            "gender": tmpl.gender,
            "role": tmpl.role,
            "current_location_id": ns.current_location_id if ns.current_location_id is not None else tmpl.home_location_id,
            "favor": ns.favor if ns else 0,
            "is_companion": ns.is_companion if ns else False,
            "is_revealed": True,
            "is_alive": ns.is_alive if ns else True,
        })

    # ── Events (triggered + completed only) ───────────────────────────────
    event_rows = (await s.execute(
        select(WorldEvent).where(WorldEvent.framework_id == framework_id)
        .order_by(WorldEvent.id)
    )).scalars().all()

    event_states: dict[int, SessionEventState] = {}
    if event_rows:
        es_rows = (await s.execute(
            select(SessionEventState).where(
                SessionEventState.session_id == session_id,
                SessionEventState.event_id.in_([e.id for e in event_rows]),
                SessionEventState.status.in_(["triggered", "completed"]),
            )
        )).scalars().all()
        event_states = {r.event_id: r for r in es_rows}

    events = []
    for ev in event_rows:
        es = event_states.get(ev.id)
        if es is None:
            continue  # pending → hidden
        events.append({
            "event_id": ev.id,
            "name": ev.name,
            "summary_md": ev.summary_md,
            "importance": ev.importance,
            "scope_type": ev.scope_type,
            "scope_ref": ev.scope_ref,
            "status": es.status,
            "triggered_turn": es.triggered_turn,
        })

    # ── PC location ────────────────────────────────────────────────────────
    # GameSession has no pc_location_id field; return None.
    pc_location_id = None

    # ── Campaign ───────────────────────────────────────────────────────────
    campaign_row = (await s.execute(
        select(Campaign).where(Campaign.framework_id == framework_id)
    )).scalar_one_or_none()

    campaign = None
    if campaign_row is not None:
        camp_state = (await s.execute(
            select(SessionCampaignState).where(
                SessionCampaignState.session_id == session_id
            )
        )).scalar_one_or_none()

        phases_data = _safe_json(campaign_row.phases_json, [])
        triggered_key_events_set: set[int] = set(
            _safe_json(camp_state.triggered_key_events_json, []) if camp_state else []
        )
        current_phase_id = camp_state.current_phase_id if camp_state else None

        # Build set of completed phase IDs to resolve prerequisites.
        # A phase is "completed" if its required_count key events have all been triggered.
        completed_phase_ids: set[int] = set()
        for ph in phases_data:
            ph_id = ph.get("phase_id")
            key_event_ids: list[int] = ph.get("key_event_ids", [])
            required_count: int = ph.get("required_count", len(key_event_ids))
            triggered_in_phase = [eid for eid in key_event_ids if eid in triggered_key_events_set]
            if len(triggered_in_phase) >= required_count:
                completed_phase_ids.add(ph_id)

        phase_progresses = []
        for ph in phases_data:
            ph_id = ph.get("phase_id")
            key_event_ids: list[int] = ph.get("key_event_ids", [])
            required_count: int = ph.get("required_count", len(key_event_ids))
            prereqs: list[int] = ph.get("prerequisite_phase_ids", [])

            triggered_in_phase = [eid for eid in key_event_ids if eid in triggered_key_events_set]
            triggered_count = len(triggered_in_phase)

            if ph_id in completed_phase_ids:
                status = "completed"
            elif ph_id == current_phase_id or all(p in completed_phase_ids for p in prereqs):
                status = "active"
            else:
                status = "locked"

            # Build triggered_key_events list with names
            event_name_map = {ev["event_id"]: ev["name"] for ev in events}
            # Also include events not yet visible (pending) for campaign name lookup
            for ev in event_rows:
                if ev.id not in event_name_map:
                    event_name_map[ev.id] = ev.name

            triggered_key_events = [
                {"event_id": eid, "name": event_name_map.get(eid, str(eid))}
                for eid in triggered_in_phase
            ]

            phase_progresses.append({
                "phase_id": ph_id,
                "name": ph.get("name", ""),
                "description": ph.get("description", ""),
                "status": status,
                "triggered_count": triggered_count,
                "required_count": required_count,
                "triggered_key_events": triggered_key_events,
            })

        campaign = {
            "campaign_name": campaign_row.name,
            "phases": phase_progresses,
        }

    return {
        "locations": locations,
        "factions": factions,
        "npcs": npcs,
        "events": events,
        "pc_location_id": pc_location_id,
        "campaign": campaign,
    }
