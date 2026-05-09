"""Open-world Director agent.

Replaces the screenplay-chapter Director for sessions with framework_id set.
Scores nearby WorldEvents using a spatial decay formula, delivers far events
as rumors, checks NPC proactive contact, then calls the LLM for plot_directive.
"""
from __future__ import annotations

import json
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.models.client import GenerationParams, ModelClient
from dzmm.prompts.director_open_world_template import build_open_world_director_messages
from dzmm.service.agents.streams import (
    append_message,
    get_or_create_stream,
    load_history,
)
from dzmm.service.world_graph import bfs_distance, build_graph

log = logging.getLogger(__name__)

STREAM_KIND_DIRECTOR = "gm_director"
DIRECTOR_HISTORY_MAX = 20
_PARAMS = GenerationParams(temperature=0.4, max_tokens=500)

_RUMOR_COOLDOWN_TURNS = 5
_RUMOR_MIN_IMPORTANCE = 3

_FALLBACK_DIRECTIVE = (
    "<plot_directive>\n"
    "- 本回合主推：推进当前附近最高优先级事件\n"
    "- NPC 重点：（无）\n"
    "- 节奏：常态\n"
    "- 禁止：不要无视玩家本回合输入\n"
    "</plot_directive>"
)

_DIST_FACTORS = {0: 1.0, 1: 0.8, 2: 0.5}


def score_event(
    event: dict,
    pc_location_id: int,
    distance: int,
    companion_npc_ids: set[int],
    faction_rep_npcs: set[int],
    npc_template_ids_in_event: set[int] | None = None,
) -> float:
    """Compute Director priority score for a WorldEvent.

    Returns 0.0 for events at distance ≥ 3 (handled by rumor channel instead).
    Formula: importance × distance_factor + companion_bonus + faction_bonus
    """
    if distance >= 3:
        return 0.0
    dist_factor = _DIST_FACTORS.get(distance, 0.0)
    score = float(event["importance"]) * dist_factor

    npc_ids = npc_template_ids_in_event or set()
    if companion_npc_ids & npc_ids:
        score += 0.3
    if faction_rep_npcs & npc_ids:
        score += 0.2
    return score


def is_rumor_eligible(
    event: dict,
    distance: int,
    delivered: bool,
    turns_since_last: int,
    cooldown: int = _RUMOR_COOLDOWN_TURNS,
) -> bool:
    """Return True if a far event qualifies for rumor delivery."""
    if delivered:
        return False
    if distance < 3:
        return False
    if event["importance"] < _RUMOR_MIN_IMPORTANCE:
        return False
    if turns_since_last < cooldown:
        return False
    return True


def check_npc_proactive_contact(
    npc_states: list[dict],
    pc_location_id: int,
    current_turn: int,
) -> dict | None:
    """Return the best NPC candidate for proactive contact this turn, or None.

    Conditions (all must be true):
    - is_alive
    - not is_companion (companions are always with PC)
    - favor >= contact_favor_threshold
    - current_location_id != pc_location_id (NPC is away)
    - current_turn - last_contact_turn >= contact_cooldown_turns
    """
    candidates = []
    for npc in npc_states:
        if not npc.get("is_alive", True):
            continue
        if npc.get("is_companion", False):
            continue
        if npc.get("favor", 0) < npc.get("contact_favor_threshold", 70):
            continue
        if npc.get("current_location_id") == pc_location_id:
            continue
        last_contact = npc.get("last_contact_turn", 0)
        cooldown = npc.get("contact_cooldown_turns", 10)
        if current_turn - last_contact < cooldown:
            continue
        candidates.append(npc)
    if not candidates:
        return None
    # Pick highest favor
    return max(candidates, key=lambda n: n.get("favor", 0))


async def run_open_world_director(
    s: AsyncSession,
    session_id: int,
    framework_id: int,
    client: ModelClient,
    current_turn: int,
    pc_location_id: int,
    character_name: str,
    character_md: str,
) -> tuple[str, int, int]:
    """Run the open-world Director for one turn.

    Loads WorldLocations + pending WorldEvents + SessionNpcStates from DB,
    computes scoring, builds snapshot, calls LLM, returns (directive, tok_in, tok_out).
    """
    from dzmm.db.models import (
        WorldLocation,
        WorldEvent,
        WorldNPCTemplate,
        WorldFaction,
        SessionNpcState,
        SessionEventState,
        SessionFactionState,
        SessionCampaignState,
        Campaign,
    )
    from sqlalchemy import select as _select

    # 1. Load all world locations for this framework
    locs = (await s.execute(
        _select(WorldLocation).where(WorldLocation.framework_id == framework_id)
    )).scalars().all()
    loc_dicts = [
        {"id": loc.id, "connections_json": loc.connections_json, "name": loc.name}
        for loc in locs
    ]
    graph = build_graph(loc_dicts)

    # 2. Load pending world events
    events = (await s.execute(
        _select(WorldEvent).where(WorldEvent.framework_id == framework_id)
    )).scalars().all()

    # 3. Load session event states (triggered/completed → skip)
    ev_states_rows = (await s.execute(
        _select(SessionEventState).where(SessionEventState.session_id == session_id)
    )).scalars().all()
    done_event_ids = {
        es.event_id for es in ev_states_rows
        if es.status in ("triggered", "completed")
    }
    rumor_event_ids = {
        es.event_id for es in ev_states_rows if es.rumor_delivered
    }
    last_rumor_turns = {es.event_id: es.rumor_delivered_turn for es in ev_states_rows}

    # 4. Load NPC states for proactive contact check
    npc_states_rows = (await s.execute(
        _select(SessionNpcState, WorldNPCTemplate)
        .join(WorldNPCTemplate, SessionNpcState.npc_template_id == WorldNPCTemplate.id)
        .where(SessionNpcState.session_id == session_id)
    )).all()
    companion_npc_ids = {
        row.SessionNpcState.npc_template_id
        for row in npc_states_rows
        if row.SessionNpcState.is_companion
    }
    npc_state_dicts = [
        {
            "npc_template_id": row.SessionNpcState.npc_template_id,
            "favor": row.SessionNpcState.favor,
            "current_location_id": row.SessionNpcState.current_location_id,
            "last_contact_turn": row.SessionNpcState.last_contact_turn,
            "contact_favor_threshold": row.WorldNPCTemplate.contact_favor_threshold,
            "contact_cooldown_turns": row.WorldNPCTemplate.contact_cooldown_turns,
            "is_alive": row.SessionNpcState.is_alive,
            "is_companion": row.SessionNpcState.is_companion,
            "name": row.WorldNPCTemplate.name,
        }
        for row in npc_states_rows
    ]

    # 5. Load faction tensions
    faction_states = (await s.execute(
        _select(SessionFactionState, WorldFaction)
        .join(WorldFaction, SessionFactionState.faction_id == WorldFaction.id)
        .where(SessionFactionState.session_id == session_id)
    )).all()
    faction_tensions = [
        {"name": row.WorldFaction.name, "tension": row.SessionFactionState.tension}
        for row in faction_states
        if row.SessionFactionState.tension > 0
    ]

    # 6. Score candidate events
    candidate_events = []
    rumor_events = []
    for ev in events:
        if ev.id in done_event_ids:
            continue
        # Determine location distance
        try:
            scope_loc_id = int(ev.scope_ref) if ev.scope_type == "location" else None
        except (ValueError, TypeError):
            scope_loc_id = None
        dist = bfs_distance(graph, pc_location_id, scope_loc_id) if scope_loc_id else 0

        sc = score_event(
            {"id": ev.id, "importance": ev.importance, "scope_ref": ev.scope_ref,
             "scope_type": ev.scope_type},
            pc_location_id=pc_location_id,
            distance=dist,
            companion_npc_ids=companion_npc_ids,
            faction_rep_npcs=set(),
        )
        if sc > 0:
            candidate_events.append({
                "id": ev.id, "name": ev.name, "score": sc,
                "importance": ev.importance, "summary_md": ev.summary_md,
            })
        elif is_rumor_eligible(
            {"importance": ev.importance},
            distance=dist,
            delivered=ev.id in rumor_event_ids,
            turns_since_last=current_turn - last_rumor_turns.get(ev.id, 0),
        ):
            rumor_events.append({
                "id": ev.id, "name": ev.name,
                "importance": ev.importance, "summary_md": ev.summary_md,
            })

    candidate_events.sort(key=lambda e: e["score"], reverse=True)
    candidate_events = candidate_events[:5]

    # 7. NPC proactive contact
    proactive = check_npc_proactive_contact(
        npc_state_dicts, pc_location_id=pc_location_id, current_turn=current_turn
    )
    proactive_name = proactive["name"] if proactive else None

    # 8. Campaign phase
    campaign_phase_str: str | None = None
    camp_state = await s.get(SessionCampaignState, session_id)
    if camp_state and camp_state.current_phase_id:
        camp_row = (await s.execute(
            _select(Campaign).where(Campaign.framework_id == framework_id)
        )).scalars().first()
        if camp_row:
            phases = json.loads(camp_row.phases_json or "[]")
            phase = next((p for p in phases if p["phase_id"] == camp_state.current_phase_id), None)
            if phase:
                triggered = json.loads(camp_state.triggered_key_events_json or "[]")
                campaign_phase_str = (
                    f"{phase['name']}（{len(triggered)}/{phase['required_count']} 关键事件）"
                )

    # 9. Build snapshot + call LLM
    snapshot = {
        "current_location": next((l["name"] for l in loc_dicts if l["id"] == pc_location_id), "未知"),
        "pc_summary": f"{character_name}",
        "companions": [n["name"] for n in npc_state_dicts if n["is_companion"]],
        "candidate_events": candidate_events,
        "rumor_events": rumor_events[:3],
        "proactive_npc": proactive_name,
        "campaign_phase": campaign_phase_str,
        "faction_tensions": faction_tensions,
    }

    stream = await get_or_create_stream(s, session_id, STREAM_KIND_DIRECTOR, "")
    history = await load_history(s, stream.id, max_messages=DIRECTOR_HISTORY_MAX)
    msgs = build_open_world_director_messages(history, snapshot)

    try:
        output, usage = await client.complete(msgs, _PARAMS)
    except Exception as exc:  # noqa: BLE001
        log.warning("open-world director: LLM call failed: %s", exc)
        return _FALLBACK_DIRECTIVE, 0, 0

    text = (output or "").strip()
    if not text:
        return _FALLBACK_DIRECTIVE, 0, 0

    tok_in = usage.input_tokens if usage else 0
    tok_out = usage.output_tokens if usage else 0

    snapshot_str = _json_snapshot(snapshot)
    await append_message(s, stream.id, current_turn, "user", snapshot_str, tokens_in=tok_in)
    await append_message(s, stream.id, current_turn, "assistant", text, tokens_out=tok_out)
    stream.last_run_turn = current_turn
    return text, tok_in, tok_out


def _json_snapshot(snapshot: dict) -> str:
    return json.dumps(snapshot, ensure_ascii=False, indent=None)
