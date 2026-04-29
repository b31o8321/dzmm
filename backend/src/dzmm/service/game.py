import json
import re
from collections.abc import AsyncIterator
from datetime import datetime, UTC

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.db.models import (
    Character,
    CharState,
    Message as MessageRow,
    NPC,
    PCGoal,
    PlotThread,
    Session as GameSession,
    StorySummary,
    World,
)
from dzmm.models.client import GenerationParams, Message, ModelClient, TokenUsage
from dzmm.parsing.events import NarrativeDelta, ParseEvent, TagComplete
from dzmm.parsing.stream_parser import StreamingTagParser
from dzmm.prompts.gm_template import build_gm_messages
from dzmm.service.state_apply import apply_tags


RECENT_WINDOW = 12

_THINK_RE = re.compile(r"<think\b[^>]*>.*?</think>", re.DOTALL | re.IGNORECASE)


def _strip_thinking_tags(text: str) -> str:
    """Remove <think>...</think> blocks (DeepSeek-R1 / o1-style reasoning).
    Used in the no-tag fallback so the user sees a clean narrative."""
    return _THINK_RE.sub("", text)


async def run_turn(
    session: AsyncSession,
    session_id: int,
    user_action: str,
    client: ModelClient,
    params: GenerationParams | None = None,
) -> AsyncIterator[ParseEvent]:
    """Yield parse events to caller (for SSE streaming) while running a full turn:
    builds prompt, streams model output, applies tags, persists messages.

    Caller must call session.commit() after the generator is exhausted."""
    params = params or GenerationParams()

    sess = await session.get(GameSession, session_id)
    if sess is None:
        raise ValueError(f"Session {session_id} not found")
    world = await session.get(World, sess.world_id)
    char = await session.get(Character, sess.character_id)

    char_state = (
        await session.execute(
            select(CharState).where(CharState.session_id == session_id)
        )
    ).scalar_one_or_none()
    live_state = _build_live_state(char, char_state)

    summary_row = (
        await session.execute(
            select(StorySummary).where(StorySummary.session_id == session_id)
        )
    ).scalar_one_or_none()
    story_summary = summary_row.summary_text if summary_row else ""

    key_facts = await _build_key_facts(session, session_id, sess.turn_count)

    recent = await _load_recent_messages(session, session_id, summary_row)

    rules_mode = json.loads(world.rules_json or '{"mode":"light"}').get("mode", "light")

    character_md = _format_character_card(char)

    msgs = build_gm_messages(
        world_md=world.content_md,
        character_md=character_md,
        live_state=live_state,
        rules_mode=rules_mode,
        style=world.style,
        story_summary=story_summary,
        key_facts=key_facts,
        recent_messages=recent,
        current_action=user_action,
    )

    parser = StreamingTagParser()
    full_output_parts: list[str] = []
    completed_tags: list[TagComplete] = []
    usage = TokenUsage()
    narrative_emitted = False

    async for chunk in client.stream(msgs, params):
        if chunk.delta:
            full_output_parts.append(chunk.delta)
            for ev in parser.feed(chunk.delta):
                if isinstance(ev, TagComplete):
                    completed_tags.append(ev)
                if isinstance(ev, NarrativeDelta):
                    narrative_emitted = True
                yield ev
        if chunk.usage is not None:
            usage = chunk.usage

    for ev in parser.finish():
        if isinstance(ev, TagComplete):
            completed_tags.append(ev)
        if isinstance(ev, NarrativeDelta):
            narrative_emitted = True
        yield ev

    full_output = "".join(full_output_parts)

    if not narrative_emitted and full_output.strip():
        fallback = _strip_thinking_tags(full_output).strip()
        if fallback:
            yield NarrativeDelta(fallback)

    next_turn = sess.turn_count + 1

    session.add(MessageRow(
        session_id=session_id, role="user", content=user_action, turn=next_turn,
    ))
    session.add(MessageRow(
        session_id=session_id, role="assistant", content=full_output, turn=next_turn,
        tokens_in=usage.input_tokens, tokens_out=usage.output_tokens,
    ))

    await apply_tags(session, session_id, next_turn, completed_tags)

    sess.turn_count = next_turn
    sess.last_played = datetime.now(UTC).replace(tzinfo=None)


def _format_character_card(char: Character) -> str:
    """Prepend `等级: Lv N` so the GM knows PC progression when narrating
    challenges, NPC reactions, and XP awards."""
    profile = (char.profile_md or "").strip()
    level_line = f"等级: Lv {char.level}"
    if profile:
        return f"{level_line}\n\n{profile}"
    return level_line


def _build_live_state(char: Character, cs: CharState | None) -> dict:
    if cs is None:
        return json.loads(char.base_stats_json or "{}")
    out = json.loads(cs.stats_json or "{}")
    out["inventory"] = json.loads(cs.inventory_json or "[]")
    return out


async def _load_recent_messages(
    session: AsyncSession,
    session_id: int,
    summary_row: StorySummary | None,
) -> list[Message]:
    high_water = summary_row.last_summarized_msg_id if summary_row else 0
    rows = (
        await session.execute(
            select(MessageRow)
            .where(MessageRow.session_id == session_id)
            .where(MessageRow.id > high_water)
            .order_by(MessageRow.id.desc())
            .limit(RECENT_WINDOW)
        )
    ).scalars().all()
    rows = list(reversed(rows))
    return [Message(role=r.role, content=r.content) for r in rows]


def _format_npc_dossier(npc: NPC) -> str:
    """Full 3-5 line dossier block for pinned/recalled NPCs."""
    archetype = (npc.archetype or "").strip()
    state = (npc.state or "").strip() or "未知"
    head = f"- {npc.name}"
    if archetype:
        head += f" [{archetype}]"
    head += f" 状态：{state}"

    lines: list[str] = [head]

    purpose = (npc.purpose or "").strip()
    if purpose:
        lines.append(f"  动机：{purpose}")

    affinity_parts = [f"好感{npc.favor:+d}"]
    try:
        affinity = json.loads(npc.affinity_json or "{}")
    except (TypeError, ValueError):
        affinity = {}
    if isinstance(affinity, dict):
        for axis, val in affinity.items():
            if isinstance(val, (int, float)):
                affinity_parts.append(f"{axis}{int(val):+d}")
    lines.append("  " + "｜".join(affinity_parts))

    try:
        notes = json.loads(npc.notes_json or "[]")
    except (TypeError, ValueError):
        notes = []
    if isinstance(notes, list) and notes:
        last = notes[-1]
        text = ""
        if isinstance(last, dict):
            text = str(last.get("text", "")).strip()
        elif isinstance(last, str):
            text = last.strip()
        if text:
            lines.append(f"  最近：{text}")
    elif npc.description:
        desc = npc.description.strip()
        if desc:
            lines.append(f"  备注：{desc[:60]}")

    return "\n".join(lines)


def _format_npc_short(npc: NPC) -> str:
    """One-line summary for recently-seen NPCs (legacy compact format)."""
    desc = (npc.description or "").strip()
    return f"- {npc.name}（好感{npc.favor:+d}，状态：{npc.state}）{desc[:40]}"


async def _build_key_facts(
    session: AsyncSession, session_id: int, current_turn: int
) -> str:
    """Build NPC + plot context with a 3-pass union:
    1. Pinned NPCs (no limit) — full dossier
    2. Recently-seen NPCs (top 8 by last_seen_turn, excluding pinned) — short line
    3. Recalled NPCs — drained from Session.recall_pending_json — full dossier"""
    pinned_npcs = (
        await session.execute(
            select(NPC)
            .where(NPC.session_id == session_id, NPC.pinned == True)  # noqa: E712
            .order_by(NPC.last_seen_turn.desc())
        )
    ).scalars().all()
    pinned_ids = {n.id for n in pinned_npcs}

    recent_npcs = (
        await session.execute(
            select(NPC)
            .where(NPC.session_id == session_id)
            .order_by(NPC.last_seen_turn.desc())
            .limit(16)
        )
    ).scalars().all()
    recent_filtered: list[NPC] = []
    for n in recent_npcs:
        if n.id in pinned_ids:
            continue
        recent_filtered.append(n)
        if len(recent_filtered) >= 8:
            break

    sess = await session.get(GameSession, session_id)
    recalled_names: list[str] = []
    if sess is not None:
        try:
            raw = json.loads(sess.recall_pending_json or "[]")
            if isinstance(raw, list):
                recalled_names = [str(x) for x in raw if x]
        except (TypeError, ValueError):
            recalled_names = []
        # Drain — recall is one-shot.
        if recalled_names:
            sess.recall_pending_json = "[]"

    recalled_npcs: list[NPC] = []
    seen_ids = pinned_ids | {n.id for n in recent_filtered}
    for name in recalled_names:
        npc = (
            await session.execute(
                select(NPC).where(
                    NPC.session_id == session_id, NPC.name == name
                )
            )
        ).scalar_one_or_none()
        if npc is not None and npc.id not in seen_ids:
            recalled_npcs.append(npc)
            seen_ids.add(npc.id)

    threads = (
        await session.execute(
            select(PlotThread)
            .where(PlotThread.session_id == session_id, PlotThread.status == "active")
            .order_by(PlotThread.importance.desc(), PlotThread.id.desc())
            .limit(8)
        )
    ).scalars().all()

    parts: list[str] = []

    if pinned_npcs:
        parts.append("📌 重点 NPC（始终在场或玩家关注）：")
        for n in pinned_npcs:
            parts.append(_format_npc_dossier(n))

    if recent_filtered:
        parts.append("\nNPC 列表：" if not pinned_npcs else "\n最近出现的其他 NPC：")
        for n in recent_filtered:
            parts.append(_format_npc_short(n))

    if recalled_npcs:
        parts.append("\n🔁 本回合回归的 NPC（请重新带入设定）：")
        for n in recalled_npcs:
            parts.append(_format_npc_dossier(n))

    if threads:
        parts.append("\n进行中的剧情线：")
        for t in threads:
            stars = "★" * t.importance
            parts.append(f"- [{t.type} {stars}] {t.description}")

    active_goals = (
        await session.execute(
            select(PCGoal).where(
                PCGoal.session_id == session_id,
                PCGoal.status == "active",
            ).order_by(PCGoal.priority.desc(), PCGoal.id.desc()).limit(8)
        )
    ).scalars().all()

    if active_goals:
        parts.append("\nPC 当前目标：")
        for g in active_goals:
            prio_mark = {"high": "★★★", "normal": "★★", "low": "★"}.get(g.priority, "★★")
            parts.append(f"- [id={g.id}] {prio_mark} {g.description}")
    return "\n".join(parts)
