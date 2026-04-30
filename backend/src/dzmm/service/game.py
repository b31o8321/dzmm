import json
import logging
import re
from collections.abc import AsyncIterator
from datetime import datetime, UTC

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.db.models import (
    Character,
    CharState,
    Era,
    HiddenEvent,
    Message as MessageRow,
    NPC,
    NpcRelation,
    PCGoal,
    PlotThread,
    Screenplay,
    Session as GameSession,
    StorySummary,
    World,
)
from dzmm.models.client import GenerationParams, Message, ModelClient, TokenUsage
from dzmm.parsing.events import NarrativeDelta, ParseEvent, TagComplete
from dzmm.parsing.stream_parser import StreamingTagParser
from dzmm.prompts.gm_template import build_gm_messages
from dzmm.service.state_apply import apply_tags


log = logging.getLogger(__name__)

RECENT_WINDOW = 12

_THINK_RE = re.compile(r"<think\b[^>]*>.*?</think>", re.DOTALL | re.IGNORECASE)


def _strip_thinking_tags(text: str) -> str:
    """Remove <think>...</think> blocks (DeepSeek-R1 / o1-style reasoning).
    Used in the no-tag fallback so the user sees a clean narrative."""
    return _THINK_RE.sub("", text)


# Self-introduction patterns that PC voice opens with. We only rewrite the name
# bound to one of these verbs so we don't touch NPC dialogue or third-person
# narrative. ([一-鿿A-Za-z0-9·_]) accepts hanzi, latin, digits and the
# middle-dot used in transliterated names ("艾米丽·斯通"). Length 1-8 covers
# everything from "我" (rare 1-char nicknames) through 8-char transliterations.
_NAME_PATTERNS = [
    re.compile(
        r"(我叫|我是|在下|鄙人|叫我|本人是?|敝人)([一-鿿A-Za-z0-9·_]{1,8})"
    ),
]

_SAY_BLOCK_RE = re.compile(r"<say\b[^>]*>.*?</say>", flags=re.DOTALL)


def _repair_pc_name(content: str, character_name: str) -> tuple[str, int]:
    """Detect and fix PC name drift in GM output.

    Conservative — only rewrites self-introduction patterns ("我叫 X", "我是 X"
    …) outside of <say speaker="..."> blocks. NPC dialogue inside <say> is
    intentionally left alone (an NPC named "林峰" really should self-introduce
    as "林峰"). Returns (repaired_text, num_fixes)."""
    if not character_name or not content:
        return content, 0

    fixes = 0

    # Mask <say>...</say> blocks first so we never rewrite NPC dialogue.
    say_blocks: list[str] = []

    def _mask(m: re.Match[str]) -> str:
        say_blocks.append(m.group(0))
        return f"\x00SAY{len(say_blocks) - 1}\x00"

    masked = _SAY_BLOCK_RE.sub(_mask, content)

    for pat in _NAME_PATTERNS:
        def _fix(m: re.Match[str]) -> str:
            nonlocal fixes
            verb, name = m.group(1), m.group(2)
            # Only rewrite when the name actually differs from the canonical PC
            # name AND is at least 2 chars (avoids replacing pronouns like 我
            # captured as a 1-char tail). Also skip if the captured name is
            # already the PC name — no-op fix.
            if name == character_name:
                return m.group(0)
            if len(name) < 2:
                return m.group(0)
            fixes += 1
            return f"{verb}{character_name}"

        masked = pat.sub(_fix, masked)

    # Restore say blocks.
    for i, block in enumerate(say_blocks):
        masked = masked.replace(f"\x00SAY{i}\x00", block)

    return masked, fixes


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

    key_facts = await _build_key_facts(session, session_id, sess.turn_count, char)

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
    narrative_parts: list[str] = []
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
                    narrative_parts.append(ev.text)
                yield ev
        if chunk.usage is not None:
            usage = chunk.usage

    for ev in parser.finish():
        if isinstance(ev, TagComplete):
            completed_tags.append(ev)
        if isinstance(ev, NarrativeDelta):
            narrative_emitted = True
            narrative_parts.append(ev.text)
        yield ev

    full_output = "".join(full_output_parts)

    if not narrative_emitted and full_output.strip():
        fallback = _strip_thinking_tags(full_output).strip()
        if fallback:
            narrative_parts.append(fallback)
            yield NarrativeDelta(fallback)

    # PC-name drift repair — fix self-intros that the GM mangled (e.g. PC is
    # "Riku" but turn 7's <pc_action> says "我叫林峰"). Streaming clients have
    # already seen the bad text; the fix lands on the persisted Message and on
    # the narrative_text passed to apply_tags so subsequent renders are clean.
    if char is not None and char.name:
        full_output, n_fixes = _repair_pc_name(full_output, char.name)
        if n_fixes > 0:
            log.info(
                "repaired %d PC name drift(s) in turn %d", n_fixes, sess.turn_count
            )
            # Also repair the captured narrative parts so apply_tags / NER
            # fallback see the corrected text.
            joined = "".join(narrative_parts)
            repaired_joined, _ = _repair_pc_name(joined, char.name)
            narrative_parts = [repaired_joined] if repaired_joined else []

    next_turn = sess.turn_count + 1

    session.add(MessageRow(
        session_id=session_id, role="user", content=user_action, turn=next_turn,
    ))

    # Capture this turn's non-narrative events (state_change / npc_update /
    # dice / plot_event / hidden_event / etc.) so the frontend can render them
    # as inline event chips and so the message history retains structured
    # state transitions for replay/export.
    events_payload = [
        {
            "type": tag.name,
            "payload": dict(tag.attrs or {}),
            "content": tag.content or "",
        }
        for tag in completed_tags
    ]

    session.add(MessageRow(
        session_id=session_id, role="assistant", content=full_output, turn=next_turn,
        tokens_in=usage.input_tokens, tokens_out=usage.output_tokens,
        events_json=json.dumps(events_payload, ensure_ascii=False),
    ))

    narrative_text = "".join(narrative_parts)
    await apply_tags(
        session, session_id, next_turn, completed_tags, narrative_text=narrative_text
    )

    sess.turn_count = next_turn
    sess.last_played = datetime.now(UTC).replace(tzinfo=None)


def _extract_pc_hooks(profile_md: str) -> dict[str, list[str]]:
    """Heuristic extraction of abilities/items/weaknesses from profile_md.

    Looks for markdown headings, bold runs, or key:value lines whose key
    matches a known PC-hook category, then captures the trailing list items
    or comma-separated phrases until the next section break."""
    out: dict[str, list[str]] = {"abilities": [], "items": [], "weaknesses": []}
    if not profile_md:
        return out
    section_pat = {
        "abilities": r"(?:能力|技能|绝技|擅长|专精)",
        "items": r"(?:物品|装备|道具|随身|身上)",
        "weaknesses": r"(?:弱点|弱项|禁忌|忌讳|害怕|畏惧)",
    }
    for key, kw in section_pat.items():
        m = re.search(
            rf"(?:^#+\s*{kw}|\*\*\s*{kw}\s*\*\*|{kw}[:：])",
            profile_md,
            re.M,
        )
        if not m:
            continue
        rest = profile_md[m.end():]
        next_heading = re.search(
            r"^#+\s|\*\*\s*[一-鿿]{2,4}\s*\*\*", rest, re.M
        )
        block = rest[: next_heading.start()] if next_heading else rest
        items = re.findall(r"[-•*]\s*(.+?)(?:$|\n)", block)
        if not items:
            items = [
                s.strip()
                for s in re.split(r"[,，、；;]", block.strip())
                if s.strip()
            ][:6]
        out[key] = [it.strip()[:50] for it in items if it.strip()][:6]
    return out


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


def _npc_revealed(npc: NPC) -> dict[str, bool]:
    """Decode npc.revealed_json with safe fallback. name is always revealed —
    GM has to be able to refer to the NPC even when other fields are hidden."""
    try:
        revealed = json.loads(npc.revealed_json or '{"name": true}')
        if not isinstance(revealed, dict):
            revealed = {}
    except (TypeError, ValueError):
        revealed = {}
    revealed["name"] = True  # always — anchor for GM reference
    return revealed


def _format_npc_dossier(npc: NPC) -> str:
    """Full 3-5 line dossier block for pinned/recalled NPCs.

    v0.11: fields not present in npc.revealed_json are NOT printed with their
    actual value — instead the GM is told the field exists but is unrevealed,
    so it can choose to surface it organically through narrative."""
    revealed = _npc_revealed(npc)

    archetype = (npc.archetype or "").strip()
    state = (npc.state or "").strip() or "未知"
    head = f"- {npc.name}"
    if archetype and revealed.get("archetype"):
        head += f" [{archetype}]"
    if revealed.get("state"):
        head += f" 状态：{state}"

    lines: list[str] = [head]

    purpose = (npc.purpose or "").strip()
    if purpose and revealed.get("purpose"):
        lines.append(f"  动机：{purpose}")

    affinity_parts: list[str] = []
    if revealed.get("favor"):
        affinity_parts.append(f"好感{npc.favor:+d}")
    if revealed.get("affinity"):
        try:
            affinity = json.loads(npc.affinity_json or "{}")
        except (TypeError, ValueError):
            affinity = {}
        if isinstance(affinity, dict):
            for axis, val in affinity.items():
                if isinstance(val, (int, float)):
                    affinity_parts.append(f"{axis}{int(val):+d}")
    if affinity_parts:
        lines.append("  " + "｜".join(affinity_parts))

    try:
        notes = json.loads(npc.notes_json or "[]")
    except (TypeError, ValueError):
        notes = []
    if isinstance(notes, list) and notes:
        # Notes are GM-authored shorthand like "分享了童年阴影" — they're
        # internal continuity markers, not raw NPC fields, so we don't gate
        # them on revealed_json. They're written by the GM after a scene the
        # player just witnessed.
        last = notes[-1]
        text = ""
        if isinstance(last, dict):
            text = str(last.get("text", "")).strip()
        elif isinstance(last, str):
            text = last.strip()
        if text:
            lines.append(f"  最近：{text}")
    elif npc.description and revealed.get("description"):
        desc = npc.description.strip()
        if desc:
            lines.append(f"  备注：{desc[:60]}")

    # Surface a list of fields that exist but are NOT yet revealed. Lets the
    # GM know there's hidden setting around this NPC it can choose to unveil
    # naturally — without leaking the values.
    hidden_fields: list[str] = []
    if (npc.description or "").strip() and not revealed.get("description"):
        hidden_fields.append("description")
    if (npc.purpose or "").strip() and not revealed.get("purpose"):
        hidden_fields.append("purpose")
    if (npc.archetype or "").strip() and not revealed.get("archetype"):
        hidden_fields.append("archetype")
    if (npc.state or "").strip() and not revealed.get("state"):
        hidden_fields.append("state")
    if not revealed.get("favor") and npc.favor != 0:
        hidden_fields.append("favor")
    if not revealed.get("affinity"):
        try:
            aff = json.loads(npc.affinity_json or "{}")
        except (TypeError, ValueError):
            aff = {}
        if isinstance(aff, dict) and aff:
            hidden_fields.append("affinity")
    if not revealed.get("emotion"):
        try:
            emo = json.loads(npc.emotion_json or "{}")
        except (TypeError, ValueError):
            emo = {}
        if isinstance(emo, dict) and emo:
            hidden_fields.append("emotion")
    if hidden_fields:
        lines.append(
            "  [未揭示：" + "/".join(hidden_fields)
            + " — 玩家尚未通过对话或调查获悉，请勿在叙述中直接说出]"
        )

    return "\n".join(lines)


def _format_npc_short(npc: NPC) -> str:
    """One-line summary for recently-seen NPCs (legacy compact format).

    v0.11: only print fields the player has already learned. Description goes
    verbatim if revealed; favor and state are hidden behind '?' otherwise so
    the GM still knows the NPC exists without leaking the value."""
    revealed = _npc_revealed(npc)
    favor_str = f"{npc.favor:+d}" if revealed.get("favor") else "??"
    state_str = npc.state if revealed.get("state") else "??"
    desc = (npc.description or "").strip() if revealed.get("description") else ""
    parts = f"- {npc.name}（好感{favor_str}，状态：{state_str}）"
    if desc:
        parts += desc[:40]
    return parts


async def _build_key_facts(
    session: AsyncSession,
    session_id: int,
    current_turn: int,
    character: Character | None = None,
) -> str:
    """Build NPC + plot context with a 3-pass union:
    1. Pinned NPCs (no limit) — full dossier
    2. Recently-seen NPCs (top 8 by last_seen_turn, excluding pinned) — short line
    3. Recalled NPCs — drained from Session.recall_pending_json — full dossier

    Also: pin the PC identity at the very top (anti-drift — fixes a v0.9 bug
    where the GM started referring to PC by a different name after ~3 turns)
    and append GM-only "暗中状态" (hidden events) at the bottom.
    """
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

    current_era = (
        await session.execute(
            select(Era).where(Era.session_id == session_id)
            .order_by(Era.started_turn.desc()).limit(1)
        )
    ).scalar_one_or_none()

    parts: list[str] = []

    # PC identity lock — top priority, prevents the GM drifting to a different
    # PC name after a few turns. character.name is the load-bearing field;
    # everything else is a hint.
    if character is not None:
        identity_lines = [
            "## PC 身份（最高优先级，永不可改）",
            f"姓名: {character.name}",
        ]
        profile = (character.profile_md or "").strip()
        if profile:
            # Keep it short — first 80 chars of the profile, single line.
            snippet = profile.replace("\n", " ").strip()[:80]
            if snippet:
                identity_lines.append(f"身份: {snippet}")
        identity_lines.append(
            "无论后文如何，PC 的姓名必须始终是上面这个，不得改名、不得替换、不得简称为别的名字。"
        )
        parts.append("\n".join(identity_lines))

    if current_era:
        parts.append(f"当前章节：{current_era.name}（自第 {current_era.started_turn} 回合起）")

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

    # PC mood — surfaced so GM tunes language to current emotional state.
    if sess is not None:
        try:
            moods = json.loads(sess.pc_mood_json or "{}")
        except (TypeError, ValueError):
            moods = {}
        if isinstance(moods, dict) and moods:
            sorted_moods = sorted(
                ((str(k), int(v)) for k, v in moods.items() if isinstance(v, (int, float))),
                key=lambda x: -x[1],
            )[:5]
            if sorted_moods:
                parts.append("\nPC 当前心情：")
                parts.append("- " + " / ".join(f"{k}({v})" for k, v in sorted_moods))

    # Active NPC↔NPC relations — keep recent 10 so worldbuilding stays consistent.
    relations = (
        await session.execute(
            select(NpcRelation)
            .where(NpcRelation.session_id == session_id)
            .order_by(NpcRelation.introduced_turn.desc(), NpcRelation.id.desc())
            .limit(10)
        )
    ).scalars().all()
    if relations:
        parts.append("\nNPC 关系：")
        for r in relations:
            parts.append(f"- {r.npc_a} ↔ {r.npc_b} [{r.kind}]")

    # v0.1.0 — Screenplay progress (active screenplay only). Placed before the
    # hidden_events block so the GM sees "what main events are still pending"
    # alongside "what hidden timers are running" — both are GM-only operational
    # state. Legacy sessions without a Screenplay row simply skip this block.
    sp = (
        await session.execute(
            select(Screenplay)
            .where(
                Screenplay.session_id == session_id,
                Screenplay.status == "active",
            )
            .order_by(Screenplay.version.desc())
        )
    ).scalars().first()
    if sp is not None:
        try:
            chapters = json.loads(sp.chapters_json or "[]")
        except (TypeError, ValueError):
            chapters = []
        if not isinstance(chapters, list):
            chapters = []
        try:
            completed = json.loads(sp.completed_events_json or "[]")
        except (TypeError, ValueError):
            completed = []
        if not isinstance(completed, list):
            completed = []
        try:
            main_chars = json.loads(sp.main_characters_json or "[]")
        except (TypeError, ValueError):
            main_chars = []
        if not isinstance(main_chars, list):
            main_chars = []

        if chapters:
            cur_idx = max(0, min(sp.current_chapter - 1, len(chapters) - 1))
            cur_ch = chapters[cur_idx] if isinstance(chapters[cur_idx], dict) else {}

            sp_lines: list[str] = [
                "\n## 当前剧本进度（GM 严格遵守主线，分支由 PC 探索触发）",
                f"当前章节：第 {sp.current_chapter} 章「{cur_ch.get('title', '')}」"
                f"（共 {len(chapters)} 章）",
            ]

            main_events = cur_ch.get("main_events") or []
            if isinstance(main_events, list) and main_events:
                sp_lines.append("本章主线（必须演完才能推进下章）：")
                for i, ev in enumerate(main_events):
                    done = any(
                        isinstance(c, dict)
                        and c.get("chapter") == sp.current_chapter
                        and c.get("event_idx") == i
                        and c.get("type") == "main"
                        for c in completed
                    )
                    flag = "[done]" if done else "[pending]"
                    sp_lines.append(f"- {flag} {ev}")

            optional_events = cur_ch.get("optional_events") or []
            if isinstance(optional_events, list) and optional_events:
                sp_lines.append("本章可选支线（PC 主动探索才触发，不强制）：")
                for i, ev in enumerate(optional_events):
                    done = any(
                        isinstance(c, dict)
                        and c.get("chapter") == sp.current_chapter
                        and c.get("event_idx") == i
                        and c.get("type") == "optional"
                        for c in completed
                    )
                    flag = "[done]" if done else "[optional]"
                    sp_lines.append(f"- {flag} {ev}")

            # Main NPCs whose intro_chapter is on or before current — surface
            # only the names; details should already exist in the NPC list above
            # once the GM declares them. Cap at 5 to keep the block compact.
            existing_names = {n.name for n in (pinned_npcs or [])} | {
                n.name for n in (recent_filtered or [])
            }
            pending_intro: list[str] = []
            for c in main_chars:
                if not isinstance(c, dict):
                    continue
                name = str(c.get("name") or "").strip()
                if not name or name in existing_names:
                    continue
                try:
                    intro_ch = int(c.get("intro_chapter", 1))
                except (TypeError, ValueError):
                    intro_ch = 1
                if intro_ch <= sp.current_chapter:
                    pending_intro.append(name)
            if pending_intro:
                names_str = " / ".join(pending_intro[:5])
                sp_lines.append(f"重要 NPC（应在不晚于本章出场）：{names_str}")

            ending_md = (sp.ending_md or "").strip()
            if ending_md:
                sp_lines.append(f"完结条件：{ending_md}")

            sp_lines.append(
                "（推进规则：主线 [pending] 事件每 1-3 回合至少演一个；"
                "支线 [optional] 等 PC 触发；演完后 emit "
                "<event_complete chapter=N event=M type=main/optional/>。"
                "本章主线全部 [done] 后 emit <chapter_advance/>。"
                "完结条件达成 emit <ending/>。"
                "重大决策（杀关键 NPC / 选阵营 / 放弃主线）"
                " emit <plot_turn impact=\"major\" description=\"...\"/>）"
            )
            parts.append("\n".join(sp_lines))

    # Hidden events — GM-only state with a fuse. Re-inject every turn so the
    # GM remembers an injury is still bleeding, a poison is still spreading,
    # a deadline is still ticking. The player never sees this section
    # directly; it's part of the system prompt.
    hidden = (
        await session.execute(
            select(HiddenEvent)
            .where(
                HiddenEvent.session_id == session_id,
                HiddenEvent.status == "active",
            )
            .order_by(HiddenEvent.introduced_turn)
        )
    ).scalars().all()
    if hidden:
        lines = ["\n## 暗中状态(GM only)"]
        for ev in hidden:
            age = current_turn - ev.introduced_turn
            sub = (ev.subject or "").strip() or "?"
            kind = (ev.kind or "").strip()
            desc = (ev.description or "").strip()
            cons = (ev.consequence or "").strip()
            tail = desc
            if cons:
                tail = f"{tail}。{cons}" if tail else cons
            lines.append(f"- [{sub}·{kind}·t+{age}] {tail}")
        parts.append("\n".join(lines))

    # PC hooks — abilities / items / weaknesses extracted from profile_md so
    # GM is reminded to actually use them in scenes.
    if character is not None:
        hooks = _extract_pc_hooks(character.profile_md or "")
        hook_lines: list[str] = []
        if hooks["abilities"]:
            hook_lines.append(
                "能力（应该被场景调用）：" + " / ".join(hooks["abilities"])
            )
        if hooks["items"]:
            hook_lines.append(
                "物品（应在剧情节点起作用）：" + " / ".join(hooks["items"])
            )
        if hooks["weaknesses"]:
            hook_lines.append(
                "弱点（应触发挑战）：" + " / ".join(hooks["weaknesses"])
            )
        if hook_lines:
            parts.append("## PC 钩子（用上它们）\n" + "\n".join(hook_lines))

    # PC numerical state — current attributes / level / inventory, surfaced
    # specifically as a "use this for DC and NPC attitude" reference.
    if character is not None:
        state_row = (
            await session.execute(
                select(CharState).where(CharState.session_id == session_id)
            )
        ).scalar_one_or_none()
        stats: dict = {}
        if state_row and state_row.stats_json:
            try:
                stats = json.loads(state_row.stats_json)
            except (TypeError, ValueError):
                stats = {}
        attr_pairs = [
            (k, v)
            for k, v in stats.items()
            if isinstance(v, (int, float))
            and k not in ("hp", "max_hp", "sanity", "max_sanity")
        ]
        level = character.level or 1
        inventory: list = []
        if state_row and state_row.inventory_json:
            try:
                inv_raw = json.loads(state_row.inventory_json)
                if isinstance(inv_raw, list):
                    inventory = inv_raw
            except (TypeError, ValueError):
                inventory = []

        if attr_pairs or level > 1 or inventory:
            num_lines = ["## PC 当前数值（dice / NPC 态度参考）"]
            if level > 1:
                num_lines.append(f"等级: Lv {level}")
            if attr_pairs:
                attr_str = " / ".join(f"{k}={v}" for k, v in attr_pairs)
                num_lines.append(f"属性: {attr_str}")
            if inventory:
                inv_str = "、".join(str(it) for it in inventory[:8])
                num_lines.append(f"物品: {inv_str}")
            num_lines.append(
                "（dice 检定的 DC 应基于属性合理设置；物品要在 narrative 显式引用；等级影响 NPC 态度。）"
            )
            parts.append("\n".join(num_lines))

    return "\n".join(parts)
