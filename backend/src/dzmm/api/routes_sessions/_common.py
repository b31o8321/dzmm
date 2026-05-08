"""Shared helpers + DI placeholders for the routes_sessions sub-modules.

main.py overrides `get_session_dep` / `get_session_maker_dep` at startup;
each sub-router imports them from here so they all share the same key.

`build_client` is re-exported here as well: tests monkeypatch
`dzmm.api.routes_sessions.build_client`, and the package __init__ mirrors
those writes down into every sub-module that captures it (currently only
`turn`). Keeping the canonical reference here avoids each sub-module
needing to import from `factory` directly."""
import json

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.db.models import NPC
from dzmm.models.factory import build_client  # noqa: F401 — re-exported
from dzmm.service.npc_dossier import _effective_reveals

__all__ = [
    "get_session_dep",
    "get_session_maker_dep",
    "build_client",
    "_to_out",
    "_parse_events_json",
    "_npc_to_dict",
    "delete_session_cascade",
]


def get_session_dep():
    raise RuntimeError("override")


def get_session_maker_dep():
    raise RuntimeError("override")


def _to_out(s):
    from dzmm.api.schemas import SessionOut
    return SessionOut(
        id=s.id, name=s.name,
        screenplay_id=s.screenplay_id,
        world_id=s.world_id, character_id=s.character_id,
        gm_model_config_id=s.gm_model_config_id,
        summarizer_model_config_id=s.summarizer_model_config_id,
        turn_count=s.turn_count,
    )


def _parse_events_json(raw: str | None) -> list[dict]:
    """Best-effort decode of Message.events_json to a list of event dicts.
    Empty/null/malformed values yield []."""
    if not raw:
        return []
    try:
        decoded = json.loads(raw)
    except (TypeError, ValueError):
        return []
    if not isinstance(decoded, list):
        return []
    return [e for e in decoded if isinstance(e, dict)]


async def delete_session_cascade(s: AsyncSession, session_id: int) -> None:
    """Delete every per-session row keyed by `session_id`. Caller deletes
    the `Session` row itself + commits.

    SQLite FK cascade isn't enabled on this schema, so each table is wiped
    explicitly. Order matters for screenplays (revisions reference them).

    Also drops every NPC's ChromaDB memory collection — vector memories
    must not outlive the NPC row, otherwise on-disk storage grows
    unbounded as players churn through saves.
    """
    from dzmm.service.npc_memory import delete_npc_memory
    # local import to avoid cycle (db.models imports light, but routes_sessions
    # is loaded before _common from base.py — keeping this import local is
    # consistent with the rest of this file)
    from dzmm.db.models import (
        AgentMessage,
        AgentStream,
        CharState,
        Faction,
        Feedback,
        HiddenEvent,
        Location,
        LocationEdge,
        Message as MessageRow,
        NPC as NPCModel,
        NpcRelation,
        PCGoal,
        PlotThread,
        Screenplay,
        ScreenplayRevision,
        StorySummary,
    )

    # v0.10: drop agent streams + their messages (FK chain) before the SQL
    # rows that reference them via session_id are wiped. Order: messages
    # (child) → streams (parent).
    stream_ids = (await s.execute(
        select(AgentStream.id).where(AgentStream.session_id == session_id)
    )).scalars().all()
    if stream_ids:
        await s.execute(
            delete(AgentMessage).where(AgentMessage.stream_id.in_(stream_ids))
        )
        await s.execute(
            delete(AgentStream).where(AgentStream.session_id == session_id)
        )

    # Two flavors of session-attached screenplays:
    # - world_id IS NULL  → 完全 session-only 的旧档剧本，跟存档一起删
    # - world_id IS NOT NULL → 通过向导/auto-generate 建出来的"世界级模板"，
    #   detach 不 delete，保留 chapters/main_characters/ending 让玩家以后能
    #   再开新存档复用；进度字段（current_chapter / completed_events_json）
    #   重置回初始状态。要彻底清掉剧本，前端走 tier-2 的
    #   DELETE /screenplays/{id}?cascade=true。
    sps = (await s.execute(
        select(Screenplay).where(Screenplay.session_id == session_id)
    )).scalars().all()
    legacy_ids: list[int] = []
    for sp in sps:
        if sp.world_id is None:
            legacy_ids.append(sp.id)
        else:
            sp.session_id = None
            sp.current_chapter = 1
            sp.completed_events_json = "[]"
            sp.status = "active"
    if legacy_ids:
        await s.execute(
            delete(ScreenplayRevision).where(
                ScreenplayRevision.screenplay_id.in_(legacy_ids)
            )
        )
        await s.execute(
            delete(Screenplay).where(Screenplay.id.in_(legacy_ids))
        )

    # Snapshot NPC ids before the delete so we can clean ChromaDB per-NPC
    # collections after the SQL rows are gone (best-effort, swallow errors).
    npc_ids = (await s.execute(
        select(NPCModel.id).where(NPCModel.session_id == session_id)
    )).scalars().all()

    # v0.10 T12: LocationEdge has FKs to Location, must be wiped before
    # the Location rows it references.
    await s.execute(
        delete(LocationEdge).where(LocationEdge.session_id == session_id)
    )

    # NB: Location and Faction were missing from the pre-extraction loop
    # in routes_sessions/base.py — they're session-scoped (FK to sessions)
    # but used to be left orphaned. Adding them here fixes that bug.
    for model in (
        MessageRow, NPCModel, NpcRelation, PlotThread,
        CharState, StorySummary, PCGoal, HiddenEvent, Feedback,
        Location, Faction,
    ):
        await s.execute(
            delete(model).where(model.session_id == session_id)
        )

    for nid in npc_ids:
        delete_npc_memory(nid)


def _npc_to_dict(n: NPC) -> dict:
    try:
        affinity = json.loads(n.affinity_json or "{}")
        if not isinstance(affinity, dict):
            affinity = {}
    except (TypeError, ValueError):
        affinity = {}
    try:
        notes = json.loads(n.notes_json or "[]")
        if not isinstance(notes, list):
            notes = []
    except (TypeError, ValueError):
        notes = []
    try:
        emotion = json.loads(n.emotion_json or "{}")
        if not isinstance(emotion, dict):
            emotion = {}
    except (TypeError, ValueError):
        emotion = {}
    # v0.11: progressive reveal map — frontend masks fields not in this dict.
    # Threshold rules (v0.2.5) live in `_effective_reveals` so the GM dossier
    # builder agrees with what the frontend renders. See npc_dossier.py.
    revealed = _effective_reveals(n)

    return {
        "id": n.id,
        "name": n.name,
        "gender": n.gender or "",
        "description": n.description,
        "favor": n.favor,
        "state": n.state,
        "last_seen_turn": n.last_seen_turn,
        "purpose": n.purpose,
        "archetype": n.archetype,
        "affinity": affinity,
        "emotion": emotion,
        "pinned": bool(n.pinned),
        "notes": notes,
        "revealed": revealed,
        "current_location": n.current_location,
        "tts_voice": n.tts_voice or "",
    }
