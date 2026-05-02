"""Session export endpoint — split out from _impl.py.

Provides GET /sessions/{session_id}/export?format=json|md plus the
helpers used to build/render the archive payload."""
import json
import os
from datetime import datetime, UTC

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.db.models import (
    Character,
    CharState,
    Feedback,
    HiddenEvent,
    Message as MessageRow,
    NPC,
    NpcRelation,
    PCGoal,
    PlotThread,
    Session as GameSession,
    StorySummary,
    World,
)

from dzmm.api.routes_sessions._common import (
    _npc_to_dict,
    _parse_events_json,
    get_session_dep,
)

router = APIRouter(prefix="/sessions", tags=["sessions"])


def _redact_portrait(p: str | None) -> str:
    """Strip directory prefix from a portrait path so exports don't leak
    absolute filesystem locations. Returns just the basename (or '')."""
    if not p:
        return ""
    return os.path.basename(p)


def _safe_filename(name: str) -> str:
    """Sanitize a session name for use in HTTP Content-Disposition filename.

    HTTP headers are latin-1 only, so we strip non-ASCII (Python's str.isalnum
    returns True for CJK chars but they can't be header-encoded). Callers
    that want to preserve the original CJK name should additionally emit a
    `filename*=UTF-8''<percent-encoded>` per RFC 5987 — see _disposition_header.
    """
    cleaned = "".join(c if (c.isascii() and c.isalnum()) else "_" for c in (name or ""))
    return cleaned.strip("_") or "session"


def _disposition_header(original_name: str, ext: str) -> str:
    """Build a Content-Disposition value with both ASCII fallback and RFC 5987
    UTF-8 encoded filename* so browsers can recover the original CJK name."""
    from urllib.parse import quote
    safe = _safe_filename(original_name)
    fallback = f"dzmm_export_{safe}.{ext}"
    encoded = quote(f"dzmm_export_{original_name or 'session'}.{ext}", safe="")
    return f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{encoded}"


def _build_export_payload(
    sess: GameSession,
    world: World | None,
    char: Character | None,
    messages: list[MessageRow],
    summary: StorySummary | None,
    cs: CharState | None,
    npcs: list[NPC],
    relations: list[NpcRelation],
    threads: list[PlotThread],
    goals: list[PCGoal],
    hidden: list[HiddenEvent],
    feedbacks: list[Feedback],
) -> dict:
    return {
        "version": "0.10",
        "exported_at": datetime.now(UTC).replace(tzinfo=None).isoformat(),
        "session": {
            "id": sess.id,
            "name": sess.name,
            "world_id": sess.world_id,
            "character_id": sess.character_id,
            "turn_count": sess.turn_count,
            "schema_version": sess.schema_version,
            "pc_mood_json": sess.pc_mood_json,
            "created_at": sess.created_at.isoformat() if sess.created_at else None,
            "last_played": sess.last_played.isoformat() if sess.last_played else None,
        },
        "world": (
            {
                "id": world.id,
                "name": world.name,
                "content_md": world.content_md,
                "rules_json": world.rules_json,
                "style": world.style,
            } if world else None
        ),
        "character": (
            {
                "id": char.id,
                "name": char.name,
                "profile_md": char.profile_md,
                "base_stats_json": char.base_stats_json,
                "level": char.level,
                "xp": char.xp,
                "portrait_path": _redact_portrait(char.portrait_path),
            } if char else None
        ),
        "messages": [
            {
                "id": m.id,
                "role": m.role,
                "content": m.content,
                "turn": m.turn,
                "tokens_in": m.tokens_in,
                "tokens_out": m.tokens_out,
                "events": _parse_events_json(m.events_json),
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in messages
        ],
        "story_summary": (
            {
                "summary_text": summary.summary_text,
                "last_summarized_msg_id": summary.last_summarized_msg_id,
                "summary_tokens": summary.summary_tokens,
                "updated_at": summary.updated_at.isoformat() if summary.updated_at else None,
            } if summary else None
        ),
        "char_state": (
            {
                "stats_json": cs.stats_json,
                "inventory_json": cs.inventory_json,
                "updated_at": cs.updated_at.isoformat() if cs.updated_at else None,
            } if cs else None
        ),
        "npcs": [_npc_to_dict(n) for n in npcs],
        "npc_relations": [
            {
                "id": r.id, "npc_a": r.npc_a, "npc_b": r.npc_b,
                "kind": r.kind, "description": r.description,
                "introduced_turn": r.introduced_turn,
            }
            for r in relations
        ],
        "plot_threads": [
            {
                "id": t.id, "type": t.type, "description": t.description,
                "introduced_turn": t.introduced_turn,
                "importance": t.importance, "status": t.status,
                "resolution": t.resolution,
            }
            for t in threads
        ],
        "pc_goals": [
            {
                "id": g.id, "description": g.description,
                "priority": g.priority, "status": g.status,
                "introduced_turn": g.introduced_turn,
                "completed_turn": g.completed_turn,
                "completion_note": g.completion_note,
            }
            for g in goals
        ],
        "hidden_events": [
            {
                "id": h.id, "subject": h.subject, "kind": h.kind,
                "severity": h.severity, "description": h.description,
                "consequence": h.consequence,
                "introduced_turn": h.introduced_turn,
                "trigger_turn": h.trigger_turn,
                "status": h.status, "resolution": h.resolution,
                "resolved_turn": h.resolved_turn,
            }
            for h in hidden
        ],
        "feedbacks": [
            {
                "id": f.id, "turn": f.turn, "message_id": f.message_id,
                "kind": f.kind, "content": f.content,
                "created_at": f.created_at.isoformat() if f.created_at else None,
            }
            for f in feedbacks
        ],
    }


def _render_export_md(payload: dict) -> str:
    """Render a human/LLM readable Markdown archive from the JSON payload."""
    sess = payload["session"]
    world = payload.get("world") or {}
    char = payload.get("character") or {}
    summary = payload.get("story_summary") or {}
    cs = payload.get("char_state") or {}
    npcs = payload.get("npcs") or []
    relations = payload.get("npc_relations") or []
    threads = payload.get("plot_threads") or []
    goals = payload.get("pc_goals") or []
    hidden = payload.get("hidden_events") or []
    feedbacks = payload.get("feedbacks") or []
    messages = payload.get("messages") or []

    lines: list[str] = []
    lines.append(f"# {sess.get('name', '')}")
    lines.append("")
    lines.append(f"- 世界：{world.get('name', '(未知)')}（{world.get('style', '')}）")
    char_name = char.get("name", "(未知)")
    lines.append(
        f"- 角色：{char_name} (Lv {char.get('level', 1)}, {char.get('xp', 0)} XP)"
    )
    lines.append(f"- 创建时间：{sess.get('created_at', '')}")
    lines.append(f"- 总回合：{sess.get('turn_count', 0)}")
    lines.append(f"- 导出时间：{payload.get('exported_at', '')}")
    lines.append("")

    lines.append("## 故事概要")
    lines.append(summary.get("summary_text") or "（暂无）")
    lines.append("")

    lines.append("## 当前状态")
    try:
        stats = json.loads(cs.get("stats_json") or "{}")
    except (TypeError, ValueError):
        stats = {}
    try:
        inventory = json.loads(cs.get("inventory_json") or "[]")
    except (TypeError, ValueError):
        inventory = []
    if stats:
        stats_str = ", ".join(f"{k}={v}" for k, v in stats.items())
    else:
        stats_str = "（无）"
    lines.append(f"- 属性：{stats_str}")
    lines.append(
        "- 物品：" + (", ".join(str(x) for x in inventory) if inventory else "（无）")
    )
    active_goals = [g for g in goals if g.get("status") == "active"]
    if active_goals:
        lines.append("- 当前任务：")
        for g in active_goals:
            lines.append(f"  - [{g.get('priority', 'normal')}] {g.get('description', '')}")
    else:
        lines.append("- 当前任务：（无）")
    active_hidden = [h for h in hidden if h.get("status") == "active"]
    if active_hidden:
        lines.append("- 暗中状态：")
        for h in active_hidden:
            lines.append(
                f"  - [{h.get('kind', '')}/sev{h.get('severity', 0)}] "
                f"{h.get('subject', '')}: {h.get('description', '')}"
            )
    else:
        lines.append("- 暗中状态：（无）")
    lines.append("")

    lines.append("## 角色档案")
    lines.append(f"### {char_name}")
    lines.append(char.get("profile_md", "") or "（无）")
    lines.append("")

    if npcs:
        lines.append("## 主要 NPC")
        for n in npcs:
            lines.append(f"### {n.get('name', '')}")
            lines.append(
                f"- 好感: {n.get('favor', 0)}, 状态: {n.get('state', '')}, "
                f"原型: {n.get('archetype', '')}"
            )
            if n.get("description"):
                lines.append(f"- 描述: {n['description']}")
            if n.get("purpose"):
                lines.append(f"- 动机: {n['purpose']}")
            emo = n.get("emotion") or {}
            if isinstance(emo, dict) and emo:
                emo_str = ", ".join(f"{k}={v}" for k, v in emo.items())
                lines.append(f"- 情绪: {emo_str}")
            lines.append("")

    if relations:
        lines.append("## 关系网")
        for r in relations:
            desc = r.get("description") or ""
            tail = f": {desc}" if desc else ""
            lines.append(
                f"- {r.get('npc_a', '')} ←→ {r.get('npc_b', '')} "
                f"({r.get('kind', '')}){tail}"
            )
        lines.append("")

    if threads:
        lines.append("## 剧情线 (Plot Threads)")
        for t in threads:
            lines.append(
                f"- [{t.get('status', '')}/{t.get('type', '')}] "
                f"{t.get('description', '')}"
            )
        lines.append("")

    # Group messages into turns: user action + GM response.
    if messages:
        lines.append("## 跑团记录")
        # Bucket by turn number — first user message + first assistant message
        # within that turn make a "回合 N" block. Fall back to per-message dump
        # if turns aren't paired.
        turns: dict[int, dict] = {}
        order: list[int] = []
        for m in messages:
            t = int(m.get("turn", 0) or 0)
            if t not in turns:
                turns[t] = {"user": None, "assistant": None, "events": []}
                order.append(t)
            slot = m.get("role")
            if slot in ("user", "assistant") and turns[t][slot] is None:
                turns[t][slot] = m
            for ev in (m.get("events") or []):
                turns[t]["events"].append(ev)
        for t in order:
            if t == 0:
                continue  # turn 0 is pre-game/system noise
            entry = turns[t]
            lines.append(f"### 回合 {t}")
            u = entry.get("user")
            a = entry.get("assistant")
            if u:
                lines.append(f"**玩家行动**：{u.get('content', '')}")
            if a:
                lines.append(f"**GM**：{a.get('content', '')}")
            evs = entry.get("events") or []
            if evs:
                ev_summaries = []
                for ev in evs:
                    et = ev.get("type", "?")
                    payload_obj = ev.get("payload")
                    ev_summaries.append(
                        f"{et}={json.dumps(payload_obj, ensure_ascii=False)}"
                    )
                lines.append(f"事件：{', '.join(ev_summaries)}")
            lines.append("")

    if feedbacks:
        lines.append("## 玩家反馈")
        for f in feedbacks:
            lines.append(
                f"- [{f.get('kind', 'other')} @ 回合 {f.get('turn', 0)} / "
                f"{f.get('created_at', '')}] {f.get('content', '')}"
            )
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


@router.get("/{session_id}/export")
async def export_session(
    session_id: int,
    format: str = "json",
    s: AsyncSession = Depends(get_session_dep),
):
    """Full archive export. format=json (default) returns a structured dump
    suitable for re-import / external LLM analysis. format=md returns a
    human-readable Markdown report with Content-Disposition for download."""
    if format not in ("json", "md"):
        raise HTTPException(400, "format must be 'json' or 'md'")

    sess = await s.get(GameSession, session_id)
    if sess is None:
        raise HTTPException(404, "session not found")

    world = await s.get(World, sess.world_id)
    char = await s.get(Character, sess.character_id)

    messages = (await s.execute(
        select(MessageRow).where(MessageRow.session_id == session_id)
        .order_by(MessageRow.id)
    )).scalars().all()
    summary = (await s.execute(
        select(StorySummary).where(StorySummary.session_id == session_id)
    )).scalar_one_or_none()
    cs = (await s.execute(
        select(CharState).where(CharState.session_id == session_id)
    )).scalar_one_or_none()
    npcs = (await s.execute(
        select(NPC).where(NPC.session_id == session_id).order_by(NPC.id)
    )).scalars().all()
    relations = (await s.execute(
        select(NpcRelation).where(NpcRelation.session_id == session_id)
        .order_by(NpcRelation.id)
    )).scalars().all()
    threads = (await s.execute(
        select(PlotThread).where(PlotThread.session_id == session_id)
        .order_by(PlotThread.id)
    )).scalars().all()
    goals = (await s.execute(
        select(PCGoal).where(PCGoal.session_id == session_id)
        .order_by(PCGoal.id)
    )).scalars().all()
    # hidden_events: include both active + resolved for archival/analysis.
    hidden = (await s.execute(
        select(HiddenEvent).where(HiddenEvent.session_id == session_id)
        .order_by(HiddenEvent.introduced_turn, HiddenEvent.id)
    )).scalars().all()
    feedbacks = (await s.execute(
        select(Feedback).where(Feedback.session_id == session_id)
        .order_by(Feedback.created_at, Feedback.id)
    )).scalars().all()

    payload = _build_export_payload(
        sess=sess, world=world, char=char, messages=messages,
        summary=summary, cs=cs, npcs=npcs, relations=relations,
        threads=threads, goals=goals,
        hidden=hidden, feedbacks=feedbacks,
    )

    if format == "md":
        md_text = _render_export_md(payload)
        return Response(
            content=md_text,
            media_type="text/markdown; charset=utf-8",
            headers={
                "Content-Disposition": _disposition_header(sess.name, "md"),
            },
        )

    return JSONResponse(
        content=payload,
        headers={
            "Content-Disposition": _disposition_header(sess.name, "json"),
        },
    )
