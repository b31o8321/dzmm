"""
service/event_evaluator.py — Check and auto-trigger WorldEvents each turn.

check_and_trigger_events() is called at end of run_turn() after state tags
are applied. For each pending SessionEventState whose WorldEvent has a
structured predicate, evaluates the predicate and marks status="triggered"
if it passes.

Old free-text trigger_conditions_json (not a parseable dict) is treated as
a "manual_trigger" sentinel that never auto-fires.
"""

from __future__ import annotations

import json
import logging
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.db.models import (
    Campaign,
    Session as GameSession,
    SessionCampaignState,
    SessionEventState,
    WorldEvent,
)
from dzmm.engine.predicates import evaluate, parse_predicate

logger = logging.getLogger(__name__)


async def check_and_trigger_events(
    s: AsyncSession,
    session_id: int,
    current_turn: int,
) -> list[int]:
    """Evaluate all pending WorldEvents linked to this session.

    For each pending SessionEventState:
      1. Load the associated WorldEvent.trigger_conditions_json.
      2. Try to parse as structured predicate (must be a JSON dict).
      3. Evaluate it. If True → mark status='triggered', triggered_turn=current_turn.
      4. Old free-text / non-dict JSON → treated as inert (never auto-fires).

    Returns list of event_ids that were newly triggered this call.
    """
    # Campaign events may only auto-trigger in the active phase. Events that
    # are not part of a campaign remain globally eligible.
    campaign_event_phases: dict[int, set[int]] = {}
    active_phase_id: int | None = None
    sess = await s.get(GameSession, session_id)
    if sess is not None and sess.framework_id is not None:
        campaign = (await s.execute(
            select(Campaign).where(Campaign.framework_id == sess.framework_id)
        )).scalars().first()
        campaign_state = await s.get(SessionCampaignState, session_id)
        active_phase_id = campaign_state.current_phase_id if campaign_state else None
        if campaign is not None:
            try:
                phases = json.loads(campaign.phases_json or "[]")
            except (TypeError, ValueError):
                phases = []
            for phase in phases if isinstance(phases, list) else []:
                phase_id = phase.get("phase_id")
                if not isinstance(phase_id, int):
                    continue
                for event_id in phase.get("key_event_ids") or []:
                    if isinstance(event_id, int):
                        campaign_event_phases.setdefault(event_id, set()).add(phase_id)

    # Load all pending event states for this session
    result = await s.execute(
        select(SessionEventState).where(
            SessionEventState.session_id == session_id,
            SessionEventState.status == "pending",
        )
    )
    pending_states: Sequence[SessionEventState] = result.scalars().all()

    newly_triggered: list[int] = []

    for ev_state in pending_states:
        event_phases = campaign_event_phases.get(ev_state.event_id)
        if event_phases is not None and active_phase_id not in event_phases:
            continue

        # Load the world event
        event = await s.get(WorldEvent, ev_state.event_id)
        if event is None:
            continue

        # Parse trigger_conditions_json
        raw = event.trigger_conditions_json or "[]"
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            # Non-JSON free-text → inert
            logger.debug(
                "event_evaluator: event %d has non-JSON trigger_conditions_json — treating as inert",
                event.id,
            )
            continue

        # Must be a dict to parse as structured predicate
        if not isinstance(data, dict):
            # Old format (list, string, etc.) → inert
            logger.debug(
                "event_evaluator: event %d trigger_conditions_json is %s, not dict — inert",
                event.id, type(data).__name__,
            )
            continue

        # Parse and evaluate
        pred = parse_predicate(data)
        try:
            fired = await evaluate(s, session_id, pred)
        except Exception as exc:
            logger.warning(
                "event_evaluator: exception evaluating event %d for session %d: %s",
                event.id, session_id, exc,
            )
            continue

        if fired:
            ev_state.status = "triggered"
            ev_state.triggered_turn = current_turn
            newly_triggered.append(event.id)
            logger.info(
                "event_evaluator: event %d (%r) triggered for session %d at turn %d",
                event.id, event.name, session_id, current_turn,
            )

    if newly_triggered:
        await s.flush()

    return newly_triggered
