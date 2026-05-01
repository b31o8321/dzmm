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
    HiddenEvent,
    Location,
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
from dzmm.prompts.outliner_template import build_outliner_messages
from dzmm.service.activity_log import log_event
from dzmm.service.npc_initiative import find_initiative_npc, _COOLDOWN_TURNS
from dzmm.service.state_apply import apply_tags
from dzmm.service.state_apply.dice_monitor import (
    build_stuck_warning,
    detect_stuck_dice,
    extract_d20_values_from_messages,
)


log = logging.getLogger(__name__)

_STYLE_TO_GENRE: dict[str, str] = {
    "dark": "悬疑探案",
    "horror": "灾难求生",
    "healing": "恋爱攻略",
    "comedy": "英雄成长",
    "realistic": "英雄成长",
}
_DEFAULT_GENRE = "英雄成长"

# Recent verbatim turn window used when assembling the GM prompt. v0.2.1 — the
# window shrinks once the session is long enough that summary + key_facts
# already carry the load; this prevents the prompt from growing unboundedly
# as turn_count climbs (live play at turn 70+ saw the GM reciting
# few-shot examples, a textbook long-context collapse symptom).
RECENT_WINDOW_DEFAULT = 12       # < 30 turns
RECENT_WINDOW_LONG_GAME = 8      # 30-60 turns
RECENT_WINDOW_VERY_LONG = 6      # > 60 turns

# Backwards-compat alias kept so external code / tests that imported the old
# name keep working. Treat as deprecated.
RECENT_WINDOW = RECENT_WINDOW_DEFAULT


def _recent_window_for(turn_count: int) -> int:
    """Adaptive verbatim window — see module-level constants for the bands."""
    if turn_count > 60:
        return RECENT_WINDOW_VERY_LONG
    if turn_count > 30:
        return RECENT_WINDOW_LONG_GAME
    return RECENT_WINDOW_DEFAULT


def _rough_token_count(messages: list[Message]) -> int:
    """Rough token estimate without spinning up tiktoken: roughly 1 token per
    1.5 CJK chars and 1 token per 4 ASCII chars. Used only for the long-context
    warning event in activity_log; precision is not required."""
    total = 0
    for m in messages:
        text = m.content or ""
        cjk = sum(1 for c in text if "一" <= c <= "鿿")
        ascii_count = len(text) - cjk
        total += int(cjk / 1.5) + int(ascii_count / 4)
    return total

_THINK_RE = re.compile(r"<think\b[^>]*>.*?</think>", re.DOTALL | re.IGNORECASE)


def _strip_thinking_tags(text: str) -> str:
    """Remove <think>...</think> blocks (DeepSeek-R1 / o1-style reasoning).
    Used in the no-tag fallback so the user sees a clean narrative."""
    return _THINK_RE.sub("", text)


# PC name drift repair extracted to a sibling module (v0.1.6 refactor); the
# names are re-exported here so existing call-sites and tests still see them.
from dzmm.service.name_repair import (
    _NAME_PATTERNS,
    _SAY_BLOCK_RE,
    _repair_pc_name,
)


async def _auto_generate_screenplay(
    session: AsyncSession,
    sess: GameSession,
    world: World,
    char: Character,
    client: ModelClient,
) -> None:
    """Generate and persist a Screenplay outline on the first turn.

    Non-fatal: if LLM output can't be parsed as JSON, logs and returns.
    """
    genre = _STYLE_TO_GENRE.get(world.style or "", _DEFAULT_GENRE)
    char_name = char.name or "PC"

    msgs = build_outliner_messages(
        world_name=world.name or "",
        world_md=world.content_md or "",
        character_name=char_name,
        character_md=_format_character_card(char),
        genre=genre,
    )

    buf: list[str] = []
    async for chunk in client.stream(msgs, GenerationParams(max_tokens=2000, temperature=0.7)):
        if chunk.delta:
            buf.append(chunk.delta)

    raw = "".join(buf).strip()
    # Strip optional markdown code fences the model sometimes adds
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1]
    if raw.endswith("```"):
        raw = raw.rsplit("\n", 1)[0]

    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        log.warning("auto_screenplay: JSON parse failed — proceeding without outline")
        return

    chapters = data.get("chapters", [])
    main_characters = data.get("main_characters", [])

    session.add(Screenplay(
        session_id=sess.id,
        version=1,
        genre=genre,
        chapters_json=json.dumps(chapters, ensure_ascii=False),
        main_characters_json=json.dumps(main_characters, ensure_ascii=False),
        ending_md=data.get("ending", ""),
        opening_hook=data.get("opening_hook", ""),
        current_chapter=1,
        completed_events_json="[]",
        status="active",
    ))
    await session.flush()
    log.info(
        "auto_screenplay: created for session %d (genre: %s, chapters: %d)",
        sess.id, genre, len(chapters),
    )


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

    # v0.2.7 — auto-generate screenplay on first turn if none exists
    if sess.turn_count == 0:
        existing_sp = (await session.execute(
            select(Screenplay).where(
                Screenplay.session_id == session_id,
                Screenplay.status == "active",
            )
        )).scalar_one_or_none()
        if existing_sp is None:
            await _auto_generate_screenplay(session, sess, world, char, client)

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

    # v0.2.1 — long-context observability. Estimate prompt token cost and
    # emit a warning event when the total crosses ~12k (most local 7B models
    # start truncating recent context and reciting few-shot examples beyond
    # this size). Non-fatal — purely advisory for the activity log UI.
    prompt_tokens = _rough_token_count(msgs)
    log_event(session_id, "turn_prompt_size",
              tokens=prompt_tokens, msgs=len(msgs))
    if prompt_tokens > 12000:
        log_event(session_id, "turn_prompt_warning",
                  tokens=prompt_tokens,
                  msg="prompt > 12k tokens, model may struggle with long context")

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

    await apply_tags(
        session,
        session_id,
        next_turn,
        completed_tags,
    )

    sess.turn_count = next_turn
    sess.last_played = datetime.now(UTC).replace(tzinfo=None)

    # v0.2.7 — NPC initiative check. After this turn completes, find if any
    # NPC is eligible to proactively contact PC. If yes, yield a synthetic
    # npc_initiative tag event; frontend will auto-trigger a /npc_tick call.
    initiative_npc = await find_initiative_npc(session, session_id, next_turn)
    if initiative_npc is not None:
        initiative_npc.last_initiative_turn = next_turn
        yield TagComplete(
            name="npc_initiative",
            attrs={"npc": initiative_npc.name},
            content="",
        )
        log.info(
            "npc_initiative scheduled: %s (turn %d)", initiative_npc.name, next_turn
        )


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
    sess = await session.get(GameSession, session_id)
    turn_count = sess.turn_count if sess is not None else 0
    window = _recent_window_for(turn_count)

    high_water = summary_row.last_summarized_msg_id if summary_row else 0
    rows = (
        await session.execute(
            select(MessageRow)
            .where(MessageRow.session_id == session_id)
            .where(MessageRow.id > high_water)
            .order_by(MessageRow.id.desc())
            .limit(window)
        )
    ).scalars().all()
    rows = list(reversed(rows))
    return [Message(role=r.role, content=r.content) for r in rows]


# NPC dossier formatters extracted to a sibling module (v0.1.6 refactor); the
# names are re-exported here so existing call-sites and tests still see them.
from dzmm.service.npc_dossier import (
    _format_npc_dossier,
    _format_npc_short,
    _npc_revealed,
)


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

    # v0.2.6 — current scene context (location + in-scene NPCs + items).
    current_loc = (
        await session.execute(
            select(Location).where(
                Location.session_id == session_id,
                Location.is_current == True,  # noqa: E712
            )
        )
    ).scalar_one_or_none()
    if current_loc is not None:
        loc_lines = [f"\n## 当前场地：{current_loc.name}"]
        if current_loc.description:
            loc_lines.append(f"描述：{current_loc.description}")

        # NPCs physically present in this location (from all three NPC lists)
        all_collected_npcs = list(pinned_npcs) + list(recent_filtered) + list(recalled_npcs)
        scene_npcs = [
            n for n in all_collected_npcs
            if (n.current_location or "").lower() == current_loc.name.lower()
        ]
        if scene_npcs:
            loc_lines.append("在场 NPC：" + "、".join(n.name for n in scene_npcs))
        else:
            loc_lines.append("在场 NPC：无")

        # Items in this location
        try:
            items = json.loads(current_loc.items_json or "[]")
            if not isinstance(items, list):
                items = []
        except (TypeError, ValueError):
            items = []
        if items:
            item_strs = []
            for i in items:
                item_name = i.get("name", "")
                if not item_name:
                    continue
                item_desc = i.get("description", "")
                item_strs.append(f"{item_name}（{item_desc}）" if item_desc else item_name)
            if item_strs:
                loc_lines.append("关键物品：" + "、".join(item_strs))

        loc_lines.append(
            "（NPC 离开此地时 emit `<npc_update name=\"X\" location=\"\"/>`；"
            "进入新地点时 emit `<npc_update name=\"X\" location=\"新地名\"/>`；"
            "引入新物品 emit `<location_item name=\"物品\" description=\"描述\" action=\"add\"/>`；"
            "物品被取走/消耗 emit `<location_item name=\"物品\" action=\"remove\"/>`）"
        )
        parts.append("\n".join(loc_lines))

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
                "（推进规则：主线 [pending] 事件每 1-2 回合至少演一个；"
                "支线 [optional] 等 PC 触发；演完后 emit "
                "<event_complete chapter=N event=M type=main/optional/>。"
                "本章主线全部 [done] 后 emit <chapter_advance/>。"
                "完结条件达成 emit <ending/>。"
                "重大决策（杀关键 NPC / 选阵营 / 放弃主线）"
                " emit <plot_turn impact=\"major\" description=\"...\"/>）"
            )
            parts.append("\n".join(sp_lines))

            # v0.2.2 P1.2 — 剧情强推:detect when the GM has gone several
            # turns without completing a main event in the current chapter
            # and inject a hard-priority directive naming the next pending
            # main event. Real play (72 turns stuck on chapter 1 of 3)
            # showed rule 24 alone wasn't enough; this section is read by
            # the GM each turn and effectively overrides the soft "1-2 回合"
            # rhythm with a concrete "演这一个，立刻 emit" instruction.
            if isinstance(main_events, list) and main_events:
                done_main_idxs = {
                    c.get("event_idx")
                    for c in completed
                    if isinstance(c, dict)
                    and c.get("chapter") == sp.current_chapter
                    and (c.get("type") or "main") == "main"
                    and isinstance(c.get("event_idx"), int)
                }
                pending_main_pairs = [
                    (i, ev) for i, ev in enumerate(main_events)
                    if i not in done_main_idxs
                ]
                if pending_main_pairs:
                    # Estimate how long ago we last completed a main event in
                    # this chapter. Prefer the recorded `turn` field on the
                    # most-recent completion; fall back to a coarse estimate
                    # for legacy rows that predate the turn field
                    # (current_turn - 3 * already-completed-main-count).
                    turns_recorded = [
                        c.get("turn")
                        for c in completed
                        if isinstance(c, dict)
                        and c.get("chapter") == sp.current_chapter
                        and (c.get("type") or "main") == "main"
                        and isinstance(c.get("turn"), int)
                    ]
                    if turns_recorded:
                        last_progress_turn = max(turns_recorded)
                    else:
                        # No turn metadata — legacy completed_events_json
                        # rows predating v0.2.2. We can't recover the real
                        # turn so we treat the last progress as turn 0,
                        # which means turns_since_progress == current_turn.
                        # This is conservative but correct: if a session has
                        # been alive for many turns and only recently been
                        # upgraded to v0.2.2, it almost certainly is stuck
                        # (matches the 72-turn-stuck real-play scenario that
                        # motivated this feature).
                        last_progress_turn = 0
                    turns_since_progress = current_turn - last_progress_turn

                    if turns_since_progress >= 3:
                        next_idx, next_event = pending_main_pairs[0]
                        emit_tag = (
                            f'<event_complete chapter="{sp.current_chapter}" '
                            f'event="{next_idx}" type="main"/>'
                        )
                        urgency = "❗❗ 极度紧急" if turns_since_progress >= 6 else "⚠️ 剧情强推"
                        parts.append(
                            f"## {urgency}（已 {turns_since_progress} 回合无主线进展）\n"
                            f"**本回合必须完成主线事件**：「{next_event}」\n\n"
                            f"操作步骤：\n"
                            f"1. 无论 PC 当前在做什么，立刻安排 NPC 或环境将 PC 引向该事件\n"
                            f"2. 在 narrative 中演出该事件的核心场景（不超过 200 字）\n"
                            f"3. 演完后立即在输出末尾 emit 以下 tag（原样复制，勿修改）：\n"
                            f"```\n{emit_tag}\n```\n"
                            f"**如不 emit 该 tag，系统将认为事件未完成，下回合继续强推。**"
                        )

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

    # v0.2.2 — dice monitoring. Pull recent assistant messages, extract any
    # d20 values from their events_json dice tags, and if the last 3+ are the
    # same value, surface a GM-only warning. Live play observed d20=9 repeated
    # 8 turns in a row, a textbook sign the model latched onto a constant.
    recent_msgs = (
        await session.execute(
            select(MessageRow)
            .where(
                MessageRow.session_id == session_id,
                MessageRow.role == "assistant",
            )
            .order_by(MessageRow.id.desc())
            .limit(5)
        )
    ).scalars().all()
    recent_msgs = list(reversed(recent_msgs))
    d20_values = extract_d20_values_from_messages(recent_msgs)
    stuck = detect_stuck_dice(d20_values, min_streak=2)
    if stuck is not None:
        parts.append(build_stuck_warning(d20_values, stuck))

    return "\n".join(parts)
