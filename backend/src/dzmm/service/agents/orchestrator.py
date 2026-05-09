"""v0.10 per-turn orchestrator.

Sequence per turn:
  1. Build session snapshot for Director triggers
  2. If Director should run -> run Director sync; else reuse last directive
  3. Stream Scene; collect narrative as it arrives
  4. After Scene completes, fan-out NPC actors in parallel; yield their tags
"""
from __future__ import annotations

import asyncio
import json as _json
import logging
import re
from collections.abc import AsyncIterator

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.db.models import (
    AgentMessage,
    AgentStream,
    Character,
    CharState,
    HiddenEvent,
    Message as MessageRow,
    NPC,
    Screenplay,
    Session as GameSession,
)
from dzmm.models.client import GenerationParams, Message, ModelClient
from dzmm.parsing.events import NarrativeDelta, ParseEvent, TagComplete, UsageSummary
from dzmm.service.agents.director import (
    STREAM_KIND_DIRECTOR,
    run_director,
)
from dzmm.service.agents.npc_actor import run_npc_actor
from dzmm.service.agents.scene import run_scene
from dzmm.service.agents.streams import append_message, get_or_create_stream

STREAM_KIND_SCENE = "scene"
from dzmm.service.agents.triggers import should_run_director

log = logging.getLogger(__name__)

NPC_MAX_PARALLEL = 4

_TAG_STRIP_RE = re.compile(r"<[^>]+>")


def _format_recent_dialogue(recent_messages: list[Message], max_turns: int = 4) -> str:
    """Compact last N user/assistant pairs into NPC-readable lines.
    Strips XML tags so each entry is plain prose, capped at 200 chars."""
    if not recent_messages:
        return ""
    take = recent_messages[-(max_turns * 2):]
    lines: list[str] = []
    for m in take:
        prefix = "玩家" if m.role == "user" else "GM"
        text = _TAG_STRIP_RE.sub(" ", m.content)
        text = " ".join(text.split())[:200]
        if text:
            lines.append(f"[{prefix}] {text}")
    return "\n".join(lines)


async def _format_npc_relationship(
    s: AsyncSession, session_id: int, npc, recent_messages: list[Message],
) -> str:
    """Build a per-NPC relationship snapshot for the actor's prompt.

    Includes:
    - current favor (+/- with label: 友好/中立/冷淡/敌对)
    - affinity dimensions (信任/羁绊/恋慕 etc., if any)
    - last 2-3 PC↔this-NPC exchanges (extracted from recent assistant
      messages filtered by speaker=this NPC, paired with adjacent PC user
      messages)
    """
    parts: list[str] = []

    favor = int(getattr(npc, "favor", 0) or 0)
    if favor >= 30:
        favor_label = "深度信任 / 友好"
    elif favor >= 10:
        favor_label = "正面 / 友善"
    elif favor >= -9:
        favor_label = "中立 / 一般认识"
    elif favor >= -29:
        favor_label = "冷淡 / 警惕"
    else:
        favor_label = "敌对"
    parts.append(f"- favor = {favor:+d}（{favor_label}）")

    try:
        aff = _json.loads(getattr(npc, "affinity_json", None) or "{}")
        if isinstance(aff, dict) and aff:
            aff_str = " / ".join(
                f"{k}:{int(v):+d}" for k, v in aff.items()
                if isinstance(v, (int, float))
            )
            if aff_str:
                parts.append(f"- 多维亲密度: {aff_str}")
    except (TypeError, ValueError):
        pass

    npc_name = getattr(npc, "name", "") or ""
    exchanges: list[str] = []
    take = recent_messages[-12:]  # last ~6 turns of pairs
    last_user = ""
    for m in take:
        if m.role == "user":
            last_user = _TAG_STRIP_RE.sub(" ", m.content).strip()[:120]
        elif m.role == "assistant":
            text = m.content or ""
            for match in re.finditer(
                r'<say\s+speaker="([^"]+)"[^>]*>([\s\S]*?)</say>',
                text,
            ):
                if match.group(1).strip() == npc_name:
                    line = _TAG_STRIP_RE.sub(" ", match.group(2)).strip()[:120]
                    if line:
                        if last_user:
                            exchanges.append(f"PC: {last_user}  → 你: {line}")
                        else:
                            exchanges.append(f"你: {line}")
    if exchanges:
        parts.append("- 近期与 PC 的交互（按时序）:")
        for e in exchanges[-3:]:
            parts.append(f"  · {e}")
    else:
        parts.append("- 近期与 PC 的交互: （还没在叙事里直接互动过）")

    return "\n".join(parts)


async def _format_scene_context(
    s: AsyncSession, session_id: int, on_stage: list[NPC],
) -> str:
    """Build a scene-context block: current location + on-stage NPCs.
    Topology / world_time blocks already live in key_facts (which Scene
    sees); NPC actors get a smaller subset here."""
    from dzmm.db.models import Location
    current = (await s.execute(
        select(Location).where(
            Location.session_id == session_id,
            Location.is_current == True,  # noqa: E712
        )
    )).scalar_one_or_none()
    parts: list[str] = []
    if current is not None:
        parts.append(f"地点：{current.name}")
        if (current.description or "").strip():
            parts.append(f"描述：{current.description.strip()[:120]}")
    if on_stage:
        names = "、".join(n.name for n in on_stage)
        parts.append(f"同台 NPC：{names}")
    return "\n".join(parts)


async def _build_director_snapshot(
    s: AsyncSession, session_id: int, current_turn: int,
) -> str:
    """Build a richer state snapshot for Director's prompt.

    Includes: turn / doom / scene_turn_count（旧），plus 剧本章节进度、
    本章 [pending]/[done] 主线事件、active hidden_events 倒计时、PC vital
    state、最近 plot_turn major 决策。Keeps it under ~600 chars to leave
    room for history + system prompt.
    """
    sess = await s.get(GameSession, session_id)
    if sess is None:
        return f"第 {current_turn} 回合（无 session 数据）"

    parts = [
        f"# Snapshot @ turn {current_turn}",
        f"- doom: {sess.doom_score}",
        f"- scene_turn_count: {sess.scene_turn_count}",
    ]

    # PC vital state
    cs = (await s.execute(
        select(CharState).where(CharState.session_id == session_id)
    )).scalar_one_or_none()
    char = await s.get(Character, sess.character_id) if sess.character_id else None
    if cs and cs.stats_json:
        try:
            stats = _json.loads(cs.stats_json)
            hp = stats.get("hp")
            sanity = stats.get("sanity")
            stam = stats.get("stamina")
            kvs = [
                (k, v) for k, v in (("hp", hp), ("sanity", sanity), ("stamina", stam))
                if v is not None
            ]
            if kvs:
                parts.append("- PC: " + " / ".join(f"{k}={v}" for k, v in kvs))
        except (TypeError, ValueError):
            pass
    if char and char.level and char.level > 1:
        parts.append(f"- PC level: {char.level}")

    # Active screenplay progress
    sp = (await s.execute(
        select(Screenplay)
        .where(Screenplay.session_id == session_id, Screenplay.status == "active")
        .order_by(Screenplay.version.desc())
    )).scalars().first()
    if sp is not None:
        try:
            chapters = _json.loads(sp.chapters_json or "[]")
        except (TypeError, ValueError):
            chapters = []
        try:
            completed = _json.loads(sp.completed_events_json or "[]")
        except (TypeError, ValueError):
            completed = []
        if isinstance(chapters, list) and chapters:
            ch_idx = max(0, min(sp.current_chapter - 1, len(chapters) - 1))
            cur_ch = chapters[ch_idx] if isinstance(chapters[ch_idx], dict) else {}
            title = str(cur_ch.get("title", "")).strip()
            main_events = cur_ch.get("main_events") or []
            done_idxs = {
                c.get("event_idx") for c in completed
                if isinstance(c, dict)
                and c.get("chapter") == sp.current_chapter
                and (c.get("type") or "main") == "main"
            }
            n_done = sum(1 for i, _ in enumerate(main_events) if i in done_idxs)
            n_total = len(main_events) if isinstance(main_events, list) else 0
            parts.append(
                f"- 章节: 第{sp.current_chapter}章「{title}」 主线 {n_done}/{n_total}"
            )
            # Full event list with done/pending status and 1-based index
            if isinstance(main_events, list):
                parts.append(f"- 本章主线事件列表（章节={sp.current_chapter}）:")
                for i, e in enumerate(main_events):
                    if not isinstance(e, dict):
                        continue
                    status = "[done]" if i in done_idxs else "[pending]"
                    desc = str(e.get("description", ""))[:80]
                    parts.append(f"  事件{i+1} {status} {desc}")
            # Optional events
            opt_events = cur_ch.get("optional_events") or []
            done_opt_idxs = {
                c.get("event_idx") for c in completed
                if isinstance(c, dict)
                and c.get("chapter") == sp.current_chapter
                and c.get("type") == "optional"
            }
            if isinstance(opt_events, list) and opt_events:
                parts.append("- 本章支线事件:")
                for i, e in enumerate(opt_events):
                    if not isinstance(e, dict):
                        continue
                    status = "[done]" if i in done_opt_idxs else "[pending]"
                    desc = str(e.get("description", ""))[:60]
                    parts.append(f"  支线{i+1} {status} {desc}")

    # Active hidden events
    hidden_rows = (await s.execute(
        select(HiddenEvent).where(
            HiddenEvent.session_id == session_id,
            HiddenEvent.status == "active",
        ).order_by(HiddenEvent.introduced_turn.desc()).limit(3)
    )).scalars().all()
    if hidden_rows:
        for he in hidden_rows:
            age = current_turn - he.introduced_turn
            parts.append(
                f"- 隐藏事件: [{he.subject}/{he.kind}/t+{age}] {(he.description or '')[:50]}"
            )

    # Recent plot_turn major decisions (scan last 8 assistant messages)
    plot_rows = (await s.execute(
        select(MessageRow.events_json, MessageRow.turn)
        .where(
            MessageRow.session_id == session_id,
            MessageRow.role == "assistant",
            MessageRow.turn >= max(1, current_turn - 8),
        )
        .order_by(MessageRow.turn.desc())
    )).all()
    plot_majors: list[str] = []
    for events_json, turn in plot_rows:
        if not events_json:
            continue
        try:
            evs = _json.loads(events_json)
        except (TypeError, ValueError):
            continue
        if not isinstance(evs, list):
            continue
        for ev in evs:
            if not isinstance(ev, dict):
                continue
            if ev.get("type") == "plot_turn":
                impact = (ev.get("payload") or {}).get("impact", "")
                if impact == "major":
                    desc = (ev.get("payload") or {}).get("description", "")
                    if desc:
                        plot_majors.append(f"  · t{turn}: {str(desc)[:60]}")
    if plot_majors:
        parts.append("- 最近重大决策:")
        parts.extend(plot_majors[:3])

    # Last turn's PC action + narrative summary so Director can judge event completion.
    last_msgs = (await s.execute(
        select(MessageRow.role, MessageRow.content, MessageRow.turn)
        .where(
            MessageRow.session_id == session_id,
            MessageRow.turn == current_turn - 1,
        )
        .order_by(MessageRow.id)
    )).all()
    if last_msgs:
        parts.append(f"- 上一回合（t{current_turn - 1}）概况:")
        for role, content, _t in last_msgs:
            if role == "user":
                parts.append(f"  PC行动: {(content or '')[:120]}")
            elif role == "assistant":
                # Strip XML tags to get plain narrative excerpt
                plain = re.sub(r"<[^>]+>", " ", content or "")
                plain = " ".join(plain.split())[:200]
                parts.append(f"  场景叙事: {plain}")

    return "\n".join(parts)


async def _build_director_trigger_state(
    s: AsyncSession, session_id: int, sess: GameSession, current_turn: int,
):
    """Compute the trigger-relevant fields from real session state.

    v0.10.3 — replaces hard-coded False/99 values so Director can fire
    synchronously when major events happened on the prior turn or when PC
    is in critical state. Trigger fields scanned:
      - chapter_advanced_last_turn / major_plot_turn_last_turn: from prior
        turn's assistant Message.events_json
      - hp / sanity: from CharState.stats_json
      - hidden_event_due: severity-keyed threshold on active HiddenEvents
        (severity 1→5 turns / 2→3 / 3→2)
    """
    # Last-turn assistant events_json scan
    last_msg = (await s.execute(
        select(MessageRow.events_json)
        .where(
            MessageRow.session_id == session_id,
            MessageRow.role == "assistant",
            MessageRow.turn == sess.turn_count,  # last completed turn
        )
        .limit(1)
    )).scalar_one_or_none()

    chapter_advanced = False
    plot_turn_major = False
    if last_msg:
        try:
            events = _json.loads(last_msg)
        except (TypeError, ValueError):
            events = []
        if isinstance(events, list):
            for ev in events:
                if not isinstance(ev, dict):
                    continue
                t = ev.get("type")
                if t == "chapter_advance":
                    chapter_advanced = True
                if t == "plot_turn":
                    if (ev.get("payload") or {}).get("impact", "") == "major":
                        plot_turn_major = True

    # PC hp/sanity from char_state
    cs = (await s.execute(
        select(CharState).where(CharState.session_id == session_id)
    )).scalar_one_or_none()
    hp = 99
    sanity = 99
    if cs and cs.stats_json:
        try:
            stats = _json.loads(cs.stats_json)
            hp = int(stats.get("hp", 99))
            sanity = int(stats.get("sanity", 99))
        except (TypeError, ValueError):
            pass

    # Hidden event due: any active hidden_event whose introduced_turn + threshold
    # has been reached. We don't have explicit consequence_turn metadata, so
    # use a heuristic: severity 1 → 5 turns, severity 2 → 3, severity 3 → 2.
    hidden_due = False
    hidden_rows = (await s.execute(
        select(HiddenEvent).where(
            HiddenEvent.session_id == session_id,
            HiddenEvent.status == "active",
        )
    )).scalars().all()
    sev_to_threshold = {1: 5, 2: 3, 3: 2}
    for he in hidden_rows:
        thresh = sev_to_threshold.get(he.severity or 2, 3)
        if (current_turn - (he.introduced_turn or 0)) >= thresh:
            hidden_due = True
            break

    return type("S", (), {
        "turn_count": sess.turn_count,
        "doom_score": sess.doom_score,
        "scene_turn_count": sess.scene_turn_count,
        "chapter_advanced_last_turn": chapter_advanced,
        "major_plot_turn_last_turn": plot_turn_major,
        "hp": hp,
        "sanity": sanity,
        "hidden_event_due": hidden_due,
    })()


async def _last_director_directive(s: AsyncSession, stream_id: int) -> str:
    """Read the most recent assistant message from the director stream as
    a fallback directive when this turn isn't running Director."""
    row = (await s.execute(
        select(AgentMessage)
        .where(AgentMessage.stream_id == stream_id,
               AgentMessage.role == "assistant")
        .order_by(AgentMessage.id.desc())
        .limit(1)
    )).scalar_one_or_none()
    if row is None:
        return (
            "<plot_directive>\n- 本回合主推：自然推进\n- NPC 重点：（无）\n"
            "- 节奏：常态\n- 禁止：（无）\n</plot_directive>"
        )
    return row.content


async def _select_on_stage_npcs(
    s: AsyncSession, session_id: int, current_turn: int, max_count: int,
) -> list[NPC]:
    """Pinned + recently-seen NPCs (top-K by last_seen_turn)."""
    pinned = (await s.execute(
        select(NPC).where(
            NPC.session_id == session_id, NPC.pinned == True,  # noqa: E712
        )
    )).scalars().all()
    recent = (await s.execute(
        select(NPC).where(
            NPC.session_id == session_id,
            NPC.last_seen_turn >= max(0, current_turn - 3),
        )
        .order_by(NPC.last_seen_turn.desc())
    )).scalars().all()
    seen: dict[int, NPC] = {}
    for n in pinned:
        seen[n.id] = n
    for n in recent:
        if len(seen) >= max_count:
            break
        seen.setdefault(n.id, n)
    return list(seen.values())[:max_count]


def _sort_npcs_for_turn(npcs: list, user_action: str) -> list:
    """Sort NPCs to determine yield order (LLM calls run in parallel anyway).

    Buckets (smaller bucket = yields first):
      0. NPC name appears in user_action (PC directly cued them)
      1. Highest emotion >= 70 (anger/fear/love etc.)
      2. Everyone else, by last_seen_turn descending

    Pure function (no DB access) — safe to call before fan-out."""
    user_action = user_action or ""

    def _key(n) -> tuple[int, int, int]:
        name = (getattr(n, "name", None) or "").strip()
        cue = -1 if name and name in user_action else 0
        try:
            emo = _json.loads(getattr(n, "emotion_json", None) or "{}")
            max_emo = max(int(v) for v in emo.values()) if emo else 0
        except (TypeError, ValueError):
            max_emo = 0
        # Negative because tuple sort is ascending; we want highest first.
        return (cue, -max_emo, -(getattr(n, "last_seen_turn", 0) or 0))

    return sorted(npcs, key=_key)


async def _run_npc_with_isolated_session(
    session_maker,
    npc: NPC,
    *,
    session_id: int,
    plot_directive: str,
    scene_narrative: str,
    user_action: str,
    client: ModelClient,
    current_turn: int,
    scene_context: str,
    recent_dialogue: str,
    relationship_summary: str = "",
    cue_intent: str = "",
) -> tuple[NPC, list[ParseEvent], int, int]:
    """Run one NPC actor on its own AsyncSession.

    Returns (npc, events, tokens_in, tokens_out) so the caller can yield
    in sorted order and accumulate token counts."""
    try:
        async with session_maker() as ns:
            try:
                events, tok_in, tok_out = await run_npc_actor(
                    ns, npc=npc, session_id=session_id,
                    plot_directive=plot_directive,
                    scene_narrative=scene_narrative,
                    user_action=user_action,
                    client=client,
                    current_turn=current_turn,
                    scene_context=scene_context,
                    recent_dialogue=recent_dialogue,
                    relationship_summary=relationship_summary,
                    cue_intent=cue_intent,
                )
                await ns.commit()
                return npc, events, tok_in, tok_out
            except Exception as exc:  # noqa: BLE001
                log.warning("npc_actor(%s) failed: %s", npc.name, exc)
                try:
                    await ns.rollback()
                except Exception:  # noqa: BLE001
                    pass
                return npc, [], 0, 0
    except Exception as exc:  # noqa: BLE001
        log.warning("npc_actor(%s) session open failed: %s", npc.name, exc)
        return npc, [], 0, 0


async def run_turn_v10(
    s: AsyncSession,
    *,
    session_id: int,
    user_action: str,
    scene_client: ModelClient,
    director_client: ModelClient,
    npc_client: ModelClient,
    session_maker=None,
    world_md: str,
    character_md: str,
    live_state_text: str,
    key_facts: str,
    recent_messages: list[Message],
    scene_params: GenerationParams | None = None,
) -> AsyncIterator[ParseEvent | UsageSummary]:
    """Per-turn coordination. Runs Director (sync if triggered) ->
    streams Scene -> fan-out NPC actors. Yields ParseEvents followed by
    a final UsageSummary (filtered out by game.py before SSE forwarding).

    `session_maker`: when provided, NPC actors run in parallel with
    isolated AsyncSessions (production path — fast). When None, falls
    back to sequential execution on the shared session `s` (back-compat
    for tests that pass a single session in)."""
    sess = await s.get(GameSession, session_id)
    if sess is None:
        return
    current_turn = sess.turn_count + 1

    director_stream = await get_or_create_stream(
        s, session_id, STREAM_KIND_DIRECTOR, "",
    )

    # v0.10.3: compute real values for Director sync triggers.
    # These look at the prior turn's events_json + current PC state +
    # active hidden_events to decide if Director must run synchronously.
    cs_obj = await _build_director_trigger_state(s, session_id, sess, current_turn)

    total_tok_in = 0
    total_tok_out = 0

    fire, reason = should_run_director(director_stream, cs_obj, current_turn)
    if fire:
        log.info("director firing (reason=%s) at turn %d", reason, current_turn)
        snapshot = await _build_director_snapshot(s, session_id, current_turn)
        directive, d_in, d_out = await run_director(
            s, session_id, director_client, current_turn, snapshot,
        )
        total_tok_in += d_in
        total_tok_out += d_out
        # Parse any <event_complete> tags Director decided to emit and yield
        # them early so apply_tags processes them before Scene runs.
        for m in re.finditer(
            r'<event_complete\b([^/]*/?)>',
            directive,
        ):
            attr_str = m.group(1)
            attrs: dict[str, str] = {}
            for am in re.finditer(r'(\w+)=["\']([^"\']*)["\']', attr_str):
                attrs[am.group(1)] = am.group(2)
            if "chapter" in attrs and "event" in attrs:
                log.info(
                    "director yielded event_complete ch=%s ev=%s type=%s",
                    attrs.get("chapter"), attrs.get("event"), attrs.get("type", "main"),
                )
                yield TagComplete(name="event_complete", attrs=attrs)
    else:
        directive = await _last_director_directive(s, director_stream.id)

    # PC name from Character row (anti-drift)
    pc_name = "PC"
    char = await s.get(Character, sess.character_id)
    if char and char.name:
        pc_name = char.name

    narrative_buf: list[str] = []
    scene_raw_parts: list[str] = []  # for debug chain storage
    # v0.10.7: collect <npc_cue> tags from Scene to drive fan-out (replaces
    # DB-pinned/recent-seen heuristic which didn't reflect "who is in the
    # scene THIS turn"). Insertion order preserved so yield order matches
    # Scene's narrative ordering when cue is encountered.
    cued_npcs: dict[str, str] = {}
    scene_tok_in = scene_tok_out = 0
    async for ev in run_scene(
        client=scene_client,
        pc_name=pc_name,
        plot_directive=directive,
        world_md=world_md, character_md=character_md,
        live_state_text=live_state_text, key_facts=key_facts,
        recent_messages=recent_messages,
        current_action=user_action,
        params=scene_params,
    ):
        if isinstance(ev, UsageSummary):
            scene_tok_in = ev.tokens_in
            scene_tok_out = ev.tokens_out
            total_tok_in += ev.tokens_in
            total_tok_out += ev.tokens_out
            continue  # don't forward to SSE
        if isinstance(ev, NarrativeDelta):
            narrative_buf.append(ev.text)
            scene_raw_parts.append(ev.text)
        elif isinstance(ev, TagComplete):
            if ev.name == "npc_cue":
                speaker = (ev.attrs or {}).get("speaker", "").strip()
                intent = (ev.attrs or {}).get("intent", "").strip()
                if speaker and speaker not in cued_npcs:
                    cued_npcs[speaker] = intent
            # Reconstruct raw XML for debug storage (approximate)
            attr_str = " ".join(f'{k}="{v}"' for k, v in (ev.attrs or {}).items())
            tag_open = f"<{ev.name}{' ' + attr_str if attr_str else ''}>"
            if ev.content:
                scene_raw_parts.append(f"{tag_open}{ev.content}</{ev.name}>")
            else:
                scene_raw_parts.append(f"{tag_open}</{ev.name}>")
        yield ev

    scene_narrative = "".join(narrative_buf)

    # Persist Scene's input context + full output for debug chain inspection.
    scene_input_summary = (
        f"# directive\n{directive[:400]}\n\n"
        f"# key_facts\n{(key_facts or '')[:600]}\n\n"
        f"# user_action\n{user_action[:200]}"
    )
    scene_stream = await get_or_create_stream(s, session_id, STREAM_KIND_SCENE, "")
    await append_message(s, scene_stream.id, current_turn, "user",
                         scene_input_summary, tokens_in=scene_tok_in)
    await append_message(s, scene_stream.id, current_turn, "assistant",
                         "".join(scene_raw_parts), tokens_out=scene_tok_out)

    # v0.10.7: Scene's <npc_cue> tags drive fan-out — only NPCs Scene
    # explicitly cued get an actor pass. NPCs that DB says are pinned/recent
    # but Scene didn't put on-stage stay silent (avoids 'pinned NPC pops up
    # in scenes they aren't in' bug).
    on_stage: list[NPC] = []
    if cued_npcs:
        cue_names = list(cued_npcs.keys())
        rows = (await s.execute(
            select(NPC).where(
                NPC.session_id == session_id,
                NPC.name.in_(cue_names),
            )
        )).scalars().all()
        rows_by_name = {n.name: n for n in rows}
        # Preserve cue order from Scene; skip cues for non-existent NPCs
        # (encounter_check soft-validation in F2 flags those next turn).
        for name in cue_names:
            if name in rows_by_name:
                on_stage.append(rows_by_name[name])
    else:
        # Backwards compat / Scene didn't cue anyone — fall back to old
        # heuristic (pinned + last_seen ≤3) so legacy / older Scene prompt
        # behavior works.
        on_stage = await _select_on_stage_npcs(
            s, session_id, current_turn, NPC_MAX_PARALLEL,
        )
    if on_stage:
        # Sort to determine yield order so the player sees the most relevant
        # reaction first. LLM calls are issued in parallel below — sort
        # only affects yield ordering, not call timing.
        ordered = _sort_npcs_for_turn(on_stage, user_action)
        recent_dialogue = _format_recent_dialogue(recent_messages)
        scene_context = await _format_scene_context(s, session_id, on_stage)

        # v0.10.6: build per-NPC relationship summary outside the fan-out
        # so all NPCs share the same recent_messages snapshot.
        npc_relationships: dict[str, str] = {}
        for npc in ordered:
            npc_relationships[npc.name] = await _format_npc_relationship(
                s, session_id, npc, recent_messages,
            )

        if session_maker is not None:
            # Parallel fan-out with isolated AsyncSessions per NPC.
            # peer_lines is intentionally dropped — same-turn NPC awareness
            # has low marginal value (two NPCs hearing the PC at the same
            # time would naturally react simultaneously); second-order
            # dynamics across turns are carried by each NPC's own history.
            #
            # Release any outer write lock before fanning out: SQLite holds
            # an exclusive write lock on uncommitted Director/Scene state
            # which would block the per-NPC sessions ("database is locked").
            # Committing here is safe — Director + Scene are stable at this
            # point, and the outer session continues to be usable for the
            # post-turn writes in game.run_turn (Message rows, apply_tags).
            try:
                await s.commit()
            except Exception as exc:  # noqa: BLE001
                log.warning("pre-fanout commit failed: %s", exc)
            tasks = [
                _run_npc_with_isolated_session(
                    session_maker, npc,
                    session_id=session_id,
                    plot_directive=directive,
                    scene_narrative=scene_narrative,
                    user_action=user_action,
                    client=npc_client,
                    current_turn=current_turn,
                    scene_context=scene_context,
                    recent_dialogue=recent_dialogue,
                    relationship_summary=npc_relationships.get(npc.name, ""),
                    cue_intent=cued_npcs.get(npc.name, ""),
                )
                for npc in ordered
            ]
            results = await asyncio.gather(*tasks)
            # NPC names are unique within a session, so name is a stable
            # key for re-ordering completion-ordered results back into the
            # sorted yield order.
            result_map = {n.name: (evs, ti, to) for n, evs, ti, to in results}
            for npc in ordered:
                evs, ti, to = result_map.get(npc.name, ([], 0, 0))
                total_tok_in += ti
                total_tok_out += to
                for ev in evs:
                    yield ev
        else:
            # Sequential fallback (no session_maker — e.g. unit tests that
            # pass a single shared session). Same yield order as parallel.
            for npc in ordered:
                try:
                    events, n_in, n_out = await run_npc_actor(
                        s, npc=npc, session_id=session_id,
                        plot_directive=directive,
                        scene_narrative=scene_narrative,
                        user_action=user_action,
                        client=npc_client,
                        current_turn=current_turn,
                        scene_context=scene_context,
                        recent_dialogue=recent_dialogue,
                        relationship_summary=npc_relationships.get(npc.name, ""),
                        cue_intent=cued_npcs.get(npc.name, ""),
                    )
                    total_tok_in += n_in
                    total_tok_out += n_out
                except Exception as exc:  # noqa: BLE001
                    log.warning("npc_actor(%s) failed: %s", npc.name, exc)
                    continue
                for ev in events:
                    yield ev
    yield UsageSummary(tokens_in=total_tok_in, tokens_out=total_tok_out)
