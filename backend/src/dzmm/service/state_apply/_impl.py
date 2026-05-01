import json
import logging
import re
from datetime import datetime, UTC
from difflib import SequenceMatcher

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

log = logging.getLogger(__name__)

# Similarity threshold for plot_event dedup (new_quest / hook_introduced /
# major_event / location_entered).
# v0.13: lowered 0.7 -> 0.6 after a 9-turn play session where 5 near-identical
# rows still slipped through despite ratios ~0.79-0.95 between them. Root
# cause was a mix of un-normalized whitespace and incidentally-low ratio after
# the GM rephrased entire clauses. 0.6 still rejects clearly-distinct quests
# (e.g. "调查重力场异常" vs "寻找解药救小菱" → ratio 0.0) so false-collapse
# risk is low; the empirical user pair scores 0.79 → safely caught.
_PLOT_DEDUP_RATIO = 0.6

# Plot-event types that create a *new* thread row. Any tag whose type is in
# this set goes through dedup against existing active threads; types not
# listed (e.g. hook_resolved) take a separate path. We deliberately include
# major_event and location_entered: in practice the GM also restates these
# across turns and they end up as duplicate panel entries.
_THREAD_CREATING_TYPES = frozenset(
    {"new_quest", "hook_introduced", "major_event", "location_entered"}
)

from dzmm.db.models import (
    Character,
    CharState,
    Era,
    HiddenEvent,
    NpcRelation,
    PCGoal,
    PlotThread,
    Screenplay,
    ScreenplayRevision,
    Session as GameSession,
)
from dzmm.parsing.events import TagComplete
from dzmm.parsing.repair import parse_loose_json
from dzmm.service.state_apply.npc import (
    _NER_CONTEXT_CUES,
    _NER_STOPWORDS,
    _NPC_REVEALABLE_FIELDS,
    _apply_npc_update,
    _auto_reveal_for_create,
    _explicit_npc_names_from_tags,
    _hanzi_ngrams,
    _ner_extract_candidate_names,
    _parse_reveal_attr,
    _register_npc_ner_fallback,
)

# Re-export for callers that imported these names from `_impl` directly
# (e.g. via the `from _impl import *` wildcard in __init__.py).
__all__ = [
    "_NER_CONTEXT_CUES",
    "_NER_STOPWORDS",
    "_NPC_REVEALABLE_FIELDS",
    "_apply_npc_update",
    "_auto_reveal_for_create",
    "_explicit_npc_names_from_tags",
    "_hanzi_ngrams",
    "_ner_extract_candidate_names",
    "_parse_reveal_attr",
    "_register_npc_ner_fallback",
    "apply_tags",
]


async def apply_tags(
    session: AsyncSession,
    session_id: int,
    current_turn: int,
    tags: list[TagComplete],
    narrative_text: str = "",
) -> None:
    """Mutate CharState and NPC rows based on parsed tags. Caller commits.

    `narrative_text` is the raw narrative (concatenated from streamed
    NarrativeDelta events). It's used by the lightweight NPC NER fallback to
    register stub NPCs the GM mentions but forgets to declare via <npc_update>.
    """
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
        elif tag.name == "era_begin":
            await _apply_era_begin(session, session_id, current_turn, tag.attrs, tag.content)
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

    # Light NER fallback: if narrative mentions names the GM forgot to register
    # via <npc_update>, register them as stubs so the next prompt's NPC list
    # at least surfaces the name (even if details are missing).
    if narrative_text and narrative_text.strip():
        explicit_names = _explicit_npc_names_from_tags(tags)
        await _register_npc_ner_fallback(
            session, session_id, current_turn, narrative_text, explicit_names
        )


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


def _normalize_for_dedup(text: str) -> str:
    """Aggressive normalize before similarity comparison.

    The GM frequently emits visually-similar descriptions that the raw
    SequenceMatcher under-rates because they differ in punctuation width,
    whitespace, or letter case. We:
      - replace full-width spaces (U+3000) and NBSP (U+00A0) with ASCII space
      - collapse runs of any whitespace to a single space
      - strip leading/trailing whitespace
      - normalize a few common CJK punctuation marks to ASCII
      - lowercase (helps when GM mixes English locale words)
    """
    if not text:
        return ""
    # Full-width space (U+3000) + NBSP (U+00A0) -> ASCII space
    text = text.replace("　", " ").replace(" ", " ")
    # Collapse all whitespace runs (also handles tabs, line breaks)
    text = re.sub(r"\s+", " ", text)
    text = text.strip()
    # Punctuation: CJK forms -> ASCII so "A，B" and "A,B" compare equal
    text = (
        text.replace("，", ",")
        .replace("。", ".")
        .replace("！", "!")
        .replace("？", "?")
        .replace("：", ":")
        .replace("；", ";")
    )
    return text.lower()


def _is_duplicate_thread(
    new_desc: str, existing_threads: list[PlotThread]
) -> int | None:
    """If `new_desc` is substantially the same as an existing active thread's
    description (SequenceMatcher ratio >= _PLOT_DEDUP_RATIO after
    normalization), return its id; else None. Empty descriptions never match.
    Exact post-normalization equality short-circuits to a hit."""
    new_norm = _normalize_for_dedup(new_desc)
    if not new_norm:
        return None
    for t in existing_threads:
        old_norm = _normalize_for_dedup(t.description or "")
        if not old_norm:
            continue
        if new_norm == old_norm:
            return t.id
        ratio = SequenceMatcher(None, new_norm, old_norm).ratio()
        if ratio >= _PLOT_DEDUP_RATIO:
            return t.id
    return None


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

    # Dedup against existing *active* threads for any thread-creating type —
    # GM frequently re-emits the same quest description across turns with
    # minor wording tweaks, which previously inflated the plot_threads table.
    # v0.13: extended from {new_quest, hook_introduced} to also cover
    # major_event + location_entered (same problem in production logs).
    # Resolved threads are intentionally NOT considered (a re-opened version
    # of an old quest deserves a fresh row).
    if event_type in _THREAD_CREATING_TYPES:
        existing = list(
            (
                await session.execute(
                    select(PlotThread).where(
                        PlotThread.session_id == session_id,
                        PlotThread.status == "active",
                    )
                )
            ).scalars()
        )
        dup_id = _is_duplicate_thread(description, existing)
        if dup_id is not None:
            log.info(
                "plot_event dedup: skip new %r (matches existing thread #%d, turn %d)",
                description[:60],
                dup_id,
                current_turn,
            )
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


async def _apply_era_begin(
    session: AsyncSession,
    session_id: int,
    current_turn: int,
    attrs: dict[str, str],
    content: str,
) -> None:
    name = attrs.get("name", "").strip()
    if not name:
        return
    era = Era(
        session_id=session_id,
        name=name,
        started_turn=current_turn,
        description=content.strip(),
    )
    session.add(era)


async def _apply_pc_goal(
    session: AsyncSession,
    session_id: int,
    current_turn: int,
    attrs: dict[str, str],
    content: str,
) -> None:
    op = attrs.get("type", "add").strip().lower()
    text = content.strip()

    if op == "add":
        if not text:
            return
        priority = attrs.get("priority", "normal").strip().lower()
        if priority not in ("high", "normal", "low"):
            priority = "normal"
        goal = PCGoal(
            session_id=session_id,
            description=text,
            priority=priority,
            status="active",
            introduced_turn=current_turn,
        )
        session.add(goal)
        return

    if op in ("complete", "abandon"):
        goal_id_str = attrs.get("id", "").strip()
        if not goal_id_str.isdigit():
            return
        goal = await session.get(PCGoal, int(goal_id_str))
        if goal is None or goal.session_id != session_id:
            return
        goal.status = "completed" if op == "complete" else "abandoned"
        goal.completed_turn = current_turn
        if text:
            goal.completion_note = text


async def _apply_pc_mood(
    session: AsyncSession,
    session_id: int,
    raw: str,
) -> None:
    """Accumulate PC mood deltas into Session.pc_mood_json.

    Mood is a free-form keyword→int map (GM picks keywords like 紧张/兴奋/疲惫).
    Values clamp to [0, 100]. Missing keys start at 0."""
    payload = parse_loose_json(raw)
    if not isinstance(payload, dict):
        return
    sess = await session.get(GameSession, session_id)
    if sess is None:
        return
    moods = json.loads(sess.pc_mood_json or "{}")
    if not isinstance(moods, dict):
        moods = {}
    for axis, delta in payload.items():
        if not isinstance(delta, (int, float)):
            continue
        axis_key = str(axis)
        new_val = int(moods.get(axis_key, 0) + delta)
        moods[axis_key] = max(0, min(100, new_val))
    sess.pc_mood_json = json.dumps(moods, ensure_ascii=False)


async def _apply_npc_relation(
    session: AsyncSession,
    session_id: int,
    current_turn: int,
    attrs: dict[str, str],
    content: str,
) -> None:
    """Register an NPC↔NPC relationship. The pair is treated as unordered:
    (A,B,kind) is equivalent to (B,A,kind), so re-declarations don't duplicate.

    If a row already exists and the new declaration carries a description while
    the old one is empty, fill in the description as a one-shot upgrade."""
    between = (attrs.get("between") or "").strip()
    parts = [p.strip() for p in between.split(",") if p.strip()]
    if len(parts) != 2:
        return
    a, b = parts[0], parts[1]
    kind = (attrs.get("kind") or "").strip() or "未定义"

    existing = (
        await session.execute(
            select(NpcRelation).where(
                NpcRelation.session_id == session_id,
                NpcRelation.kind == kind,
                ((NpcRelation.npc_a == a) & (NpcRelation.npc_b == b))
                | ((NpcRelation.npc_a == b) & (NpcRelation.npc_b == a)),
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        if content.strip() and not existing.description:
            existing.description = content.strip()
        return

    rel = NpcRelation(
        session_id=session_id,
        npc_a=a,
        npc_b=b,
        kind=kind,
        description=content.strip(),
        introduced_turn=current_turn,
    )
    session.add(rel)


async def _apply_hidden_event(
    session: AsyncSession,
    session_id: int,
    current_turn: int,
    attrs: dict[str, str],
    content: str,
) -> None:
    """Process <hidden_event> tag — implicit story state with a fuse.

    Two modes:
      1. Create: requires `kind` in attrs (or in JSON body). Subject/severity/
         description/consequence are optional; defaults applied.
      2. Resolve: attrs has `resolve` (any value) or `type="resolve"`. Marks
         all currently-active rows for the given subject as resolved.

    Tolerant input: payload may live in attrs OR be JSON in body. Body wins
    on conflict because GM tends to be more deliberate when emitting JSON.
    """
    payload: dict = {}
    payload.update({k: v for k, v in (attrs or {}).items()})
    body = (content or "").strip()
    if body:
        parsed = parse_loose_json(body)
        if isinstance(parsed, dict):
            payload.update(parsed)

    is_resolve = (
        "resolve" in payload
        or str(payload.get("type", "")).strip().lower() == "resolve"
    )
    if is_resolve:
        subject = str(payload.get("subject", "")).strip()
        if not subject:
            return
        stmt = select(HiddenEvent).where(
            HiddenEvent.session_id == session_id,
            HiddenEvent.subject == subject,
            HiddenEvent.status == "active",
        )
        rows = (await session.execute(stmt)).scalars().all()
        if not rows:
            return  # silent skip — non-existent subject is not an error
        resolution = str(payload.get("resolution", "")).strip()
        for ev in rows:
            ev.status = "resolved"
            ev.resolved_turn = current_turn
            if resolution:
                ev.resolution = resolution
        return

    kind = str(payload.get("kind", "")).strip()
    if not kind:
        return  # invalid create — kind is required

    try:
        severity = int(payload.get("severity", 2) or 2)
    except (TypeError, ValueError):
        severity = 2
    severity = max(1, min(3, severity))

    ev = HiddenEvent(
        session_id=session_id,
        subject=str(payload.get("subject", "")).strip()[:120],
        kind=kind[:60],
        severity=severity,
        description=str(payload.get("description", ""))[:1000],
        consequence=str(payload.get("consequence", ""))[:1000],
        introduced_turn=current_turn,
        status="active",
    )
    session.add(ev)


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


# ---------------------------------------------------------------------------
# v0.1.0 — screenplay-driven tag handlers
#
# Four lightweight handlers that mutate the session's *active* Screenplay row
# in response to <chapter_advance/>, <event_complete/>, <plot_turn/>,
# <ending/>. All four share the same "lookup active screenplay then mutate"
# shape; if no active screenplay exists they no-op silently (legacy sessions
# created before v0.1.0 simply never see these tags applied).
#
# attrs is a string→string dict from XML attribute parsing — chapter / event
# indices need explicit int conversion with try/except since the GM may emit
# them as decorative text.
# ---------------------------------------------------------------------------


async def _get_active_screenplay(
    session: AsyncSession, session_id: int
) -> Screenplay | None:
    """Return the highest-version active Screenplay for the session, or None."""
    return (
        await session.execute(
            select(Screenplay)
            .where(
                Screenplay.session_id == session_id,
                Screenplay.status == "active",
            )
            .order_by(Screenplay.version.desc())
        )
    ).scalars().first()


async def _apply_chapter_advance(
    session: AsyncSession,
    session_id: int,
    attrs: dict[str, str],
    current_turn: int,
) -> None:
    """<chapter_advance/> → bump current_chapter by 1, clamped to total chapters
    (last chapter is a no-op so we don't go past the planned outline)."""
    sp = await _get_active_screenplay(session, session_id)
    if sp is None:
        return
    try:
        chapters = json.loads(sp.chapters_json or "[]")
    except (TypeError, ValueError):
        chapters = []
    if not isinstance(chapters, list):
        chapters = []
    if sp.current_chapter < len(chapters):
        sp.current_chapter += 1


async def _apply_event_complete(
    session: AsyncSession,
    session_id: int,
    attrs: dict[str, str],
    current_turn: int,
) -> None:
    """<event_complete chapter=N event=M type=main|optional/> →
    append {"chapter": N, "event_idx": M, "type": "main|optional"} to
    completed_events_json. Idempotent: re-emitting same triple is a no-op."""
    sp = await _get_active_screenplay(session, session_id)
    if sp is None:
        return

    try:
        chapter = int(attrs.get("chapter", ""))
        event_idx = int(attrs.get("event", ""))
    except (TypeError, ValueError):
        return  # attrs missing or non-numeric — silently skip

    type_ = (attrs.get("type") or "main").strip().lower()
    if type_ not in ("main", "optional"):
        type_ = "main"

    try:
        completed = json.loads(sp.completed_events_json or "[]")
    except (TypeError, ValueError):
        completed = []
    if not isinstance(completed, list):
        completed = []

    rec = {"chapter": chapter, "event_idx": event_idx, "type": type_}
    if rec not in completed:
        completed.append(rec)
        sp.completed_events_json = json.dumps(completed, ensure_ascii=False)


async def _apply_plot_turn(
    session: AsyncSession,
    session_id: int,
    attrs: dict[str, str],
    current_turn: int,
) -> None:
    """<plot_turn impact=major|minor description=...> → only major creates a
    ScreenplayRevision row. The actual rewrite (after_chapters_json + diff_summary)
    is left to a later async outliner pass; we just stash the trigger and the
    *before* snapshot so the chain has provenance. minor is observational and
    intentionally a no-op here (we may pipe it into messages.events_json later).
    """
    impact = (attrs.get("impact") or "minor").strip().lower()
    if impact != "major":
        return

    sp = await _get_active_screenplay(session, session_id)
    if sp is None:
        return

    description = str(attrs.get("description", ""))[:500]

    rev = ScreenplayRevision(
        screenplay_id=sp.id,
        revision_num=1,
        trigger_turn=current_turn,
        trigger_description=description,
        before_chapters_json=sp.chapters_json or "[]",
        after_chapters_json=sp.chapters_json or "[]",
        diff_summary="(pending outliner rewrite)",
    )
    session.add(rev)


async def _apply_ending(
    session: AsyncSession,
    session_id: int,
    attrs: dict[str, str],
    current_turn: int,
) -> None:
    """<ending/> → mark active screenplay status="concluded" + concluded_at=now.
    Player can later launch a fresh chapter from the same session if desired."""
    sp = await _get_active_screenplay(session, session_id)
    if sp is None:
        return
    sp.status = "concluded"
    sp.concluded_at = datetime.now(UTC).replace(tzinfo=None)
