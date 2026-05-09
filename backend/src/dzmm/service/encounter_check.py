"""v0.10.5 — soft validation: flag warning when a brand-new NPC appears
outside their primary_location with no recent encounter_setup plot_event.

Reuses sessions.topology_warning_json (already drained by _build_key_facts
each turn) so we don't need a new column. Warnings are prefixed with
'⚠️ NPC 凭空出场' so the GM prompt makes them visible next turn and the
player can distinguish them from topology越界 warnings.

Soft by design: never aborts the SSE stream. The follow-up turn is where
the GM is forced (via injected prompt) to retroactively emit an
`encounter_setup` plot_event explaining the NPC's arrival.
"""
from __future__ import annotations

import json
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.db.models import (
    Location,
    Message as MessageRow,
    NPC,
    Screenplay,
    Session as GameSession,
)
from dzmm.parsing.events import TagComplete

log = logging.getLogger(__name__)


async def _pc_current_location(s: AsyncSession, session_id: int) -> str:
    cur = (await s.execute(
        select(Location).where(
            Location.session_id == session_id,
            Location.is_current == True,  # noqa: E712
        )
    )).scalar_one_or_none()
    return cur.name if cur is not None else ""


async def _primary_location_of_npc(
    s: AsyncSession, session_id: int, npc_name: str,
) -> str:
    """Read the active screenplay's main_characters list to find this NPC's
    primary_location. Returns "" if not declared (legacy screenplays without
    v0.10.5 fields, or NPC not in the main_characters list)."""
    sp = (await s.execute(
        select(Screenplay)
        .where(
            Screenplay.session_id == session_id,
            Screenplay.status == "active",
        )
        .order_by(Screenplay.version.desc())
    )).scalars().first()
    if sp is None:
        return ""
    try:
        chars = json.loads(sp.main_characters_json or "[]")
    except (TypeError, ValueError):
        return ""
    if not isinstance(chars, list):
        return ""
    for c in chars:
        if isinstance(c, dict) and str(c.get("name", "")).strip() == npc_name:
            return str(c.get("primary_location", "")).strip()
    return ""


async def _had_encounter_setup_recently(
    s: AsyncSession,
    session_id: int,
    current_turn: int,
    npc_name: str,
    lookback: int = 2,
) -> bool:
    """Scan the last `lookback` assistant messages' events_json for an
    encounter_setup plot_event mentioning this NPC."""
    rows = (await s.execute(
        select(MessageRow.events_json)
        .where(
            MessageRow.session_id == session_id,
            MessageRow.role == "assistant",
            MessageRow.turn >= max(1, current_turn - lookback),
            MessageRow.turn < current_turn,
        )
    )).scalars().all()
    for raw in rows:
        if not raw:
            continue
        try:
            events = json.loads(raw)
        except (TypeError, ValueError):
            continue
        if not isinstance(events, list):
            continue
        for ev in events:
            if not isinstance(ev, dict):
                continue
            if ev.get("type") != "plot_event":
                continue
            payload = ev.get("payload") or {}
            if not isinstance(payload, dict):
                continue
            if (str(payload.get("type") or "")).strip() != "encounter_setup":
                continue
            content = str(ev.get("content") or "")
            try:
                payload_str = json.dumps(payload, ensure_ascii=False)
            except (TypeError, ValueError):
                payload_str = ""
            # Loose match: NPC name appears somewhere in the payload or content
            if npc_name in content or npc_name in payload_str:
                return True
    return False


async def check_encounter_warnings(
    s: AsyncSession,
    session_id: int,
    completed_tags: list[TagComplete],
    current_turn: int,
) -> None:
    """Walk this turn's tags for newly-introduced NPCs (say speakers or
    npc_update name attrs), and for each one that is a *first* appearance
    (no prior assistant message mentions them) verify it's justified by
    PC location OR a recent encounter_setup. Append warnings to
    Session.topology_warning_json (drained next turn into prompt).

    Soft validation — never raises. Logs internally on unexpected errors.
    """
    sess = await s.get(GameSession, session_id)
    if sess is None:
        return

    # Names mentioned this turn (speakers + freshly named NPCs)
    candidate_names: set[str] = set()
    for tag in completed_tags or []:
        if tag is None:
            continue
        if tag.name == "say":
            speaker = str((tag.attrs or {}).get("speaker", "")).strip()
            if speaker:
                candidate_names.add(speaker)
        elif tag.name == "npc_update":
            name = str((tag.attrs or {}).get("name", "")).strip()
            if name and name.lower() != "none":
                candidate_names.add(name)
    if not candidate_names:
        return

    pc_loc = (await _pc_current_location(s, session_id)).strip()

    warnings: list[str] = []
    for name in candidate_names:
        npc = (await s.execute(
            select(NPC).where(
                NPC.session_id == session_id, NPC.name == name,
            )
        )).scalar_one_or_none()
        if npc is None:
            continue

        # First-appearance heuristic: last_seen_turn was bumped to this turn
        # by apply_tags. We then verify nothing in *prior* assistant messages
        # mentioned this NPC by name — if they did, it's not a first.
        if (npc.last_seen_turn or 0) != current_turn:
            continue

        prior_rows = (await s.execute(
            select(MessageRow.content, MessageRow.events_json)
            .where(
                MessageRow.session_id == session_id,
                MessageRow.role == "assistant",
                MessageRow.turn < current_turn,
            )
        )).all()
        prior_appearance = False
        for content, events_json in prior_rows:
            if (content and name in content) or (events_json and name in events_json):
                prior_appearance = True
                break
        if prior_appearance:
            continue

        primary_loc = await _primary_location_of_npc(s, session_id, name)
        if not primary_loc:
            # Legacy screenplay — no primary_location declared. Skip
            # (backward-compatible: don't warn on data we never asked for).
            continue
        if pc_loc and pc_loc == primary_loc:
            # PC physically at the NPC's home base — natural encounter.
            continue
        if await _had_encounter_setup_recently(s, session_id, current_turn, name):
            # GM already pre-empted the meeting last turn. Fine.
            continue

        warnings.append(
            f"⚠️ NPC 凭空出场：「{name}」是首次登场，但 PC 当前不在其常驻场所"
            f"「{primary_loc}」，且近 2 回合没有 encounter_setup 铺垫。"
            f"下回合开头**必须**先 emit "
            f"`<plot_event type=\"encounter_setup\" importance=\"2\">"
            f"{name} 出现的合理原因（追踪 / 巧遇 / 受邀 / 信件等）"
            f"</plot_event>` 补上语义。"
        )

    if not warnings:
        return

    # Append to topology_warning_json — _build_key_facts already drains
    # this list and renders it under "上一回合拓扑越界" each turn.
    try:
        existing = json.loads(sess.topology_warning_json or "[]")
        if not isinstance(existing, list):
            existing = []
    except (TypeError, ValueError):
        existing = []
    existing.extend(warnings)
    # Keep tail capped (same policy as topology越界 warnings) so unrelated
    # noise doesn't pile up across many turns.
    sess.topology_warning_json = json.dumps(existing[-5:], ensure_ascii=False)
