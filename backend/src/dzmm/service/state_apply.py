import json
import re
from datetime import datetime, UTC

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.db.models import (
    Character,
    CharState,
    Era,
    HiddenEvent,
    NPC,
    NpcRelation,
    PCGoal,
    PlotThread,
    Session as GameSession,
)
from dzmm.parsing.events import TagComplete
from dzmm.parsing.repair import parse_loose_json


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
            await _apply_npc_update(session, session_id, current_turn, tag.content)
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


async def _apply_npc_update(
    session: AsyncSession, session_id: int, current_turn: int, raw: str
) -> None:
    payload = parse_loose_json(raw)
    name = payload.get("name")
    if not name:
        return

    npc = (
        await session.execute(
            select(NPC).where(NPC.session_id == session_id, NPC.name == name)
        )
    ).scalar_one_or_none()
    if npc is None:
        npc = NPC(
            session_id=session_id,
            name=name,
            description=payload.get("description", ""),
            favor=0,
            state=payload.get("state", "未知"),
            last_seen_turn=current_turn,
            notes_json="[]",
            purpose="",
            archetype="",
            affinity_json="{}",
            pinned=False,
        )
        session.add(npc)

    favor_delta = payload.get("favor_delta", 0)
    if isinstance(favor_delta, (int, float)):
        npc.favor += int(favor_delta)
    if "state" in payload:
        npc.state = str(payload["state"])
    if "description" in payload and not npc.description:
        npc.description = str(payload["description"])

    purpose = payload.get("purpose")
    if purpose is not None:
        npc.purpose = str(purpose)

    archetype = payload.get("archetype")
    if archetype is not None:
        npc.archetype = str(archetype)

    affinity_delta = payload.get("affinity")
    if isinstance(affinity_delta, dict):
        existing = json.loads(npc.affinity_json or "{}")
        if not isinstance(existing, dict):
            existing = {}
        for axis, delta in affinity_delta.items():
            if not isinstance(delta, (int, float)):
                continue
            axis_key = str(axis)
            existing[axis_key] = int(existing.get(axis_key, 0)) + int(delta)
        npc.affinity_json = json.dumps(existing, ensure_ascii=False)

    emotion_delta = payload.get("emotion")
    if isinstance(emotion_delta, dict):
        emotions = json.loads(npc.emotion_json or "{}")
        if not isinstance(emotions, dict):
            emotions = {}
        for axis, delta in emotion_delta.items():
            if axis not in ("anger", "love", "fear", "respect", "jealousy"):
                continue
            if not isinstance(delta, (int, float)):
                continue
            new_val = int(emotions.get(axis, 0) + delta)
            emotions[axis] = max(0, min(100, new_val))
        npc.emotion_json = json.dumps(emotions, ensure_ascii=False)

    note = payload.get("note")
    if note:
        notes = json.loads(npc.notes_json or "[]")
        notes.append({"turn": current_turn, "text": str(note)})
        npc.notes_json = json.dumps(notes, ensure_ascii=False)
    npc.last_seen_turn = current_turn


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
# Lightweight NPC NER fallback
# ---------------------------------------------------------------------------
#
# When the GM narrates ("小菱颤抖着说话") but forgets to emit <npc_update>,
# the NPC will never appear in the next prompt's NPC list — and the next turn
# the GM might forget that NPC entirely. To prevent this drift, we run a
# regex-only heuristic over the narrative text and register stubs for any
# 2-4 character names that follow a context cue (那女子 / 老者 / 等).
#
# Conservative on purpose: missing one is much better than fabricating one.
# We only register a name when:
#   - it's not already in the NPC table for this session
#   - the GM didn't already declare it this turn via <npc_update>
#   - it was mentioned ≥ 2 times OR followed by a quoted utterance (「...」)
#   - it doesn't match any common stopword

# Names matching these are obvious false positives (place words, pronouns,
# generic person nouns, scene words). Better to drop legit names than to
# pollute the NPC table with junk.
_NER_STOPWORDS = frozenset({
    # pronouns / common subjects
    "你", "我", "他", "她", "它", "我们", "你们", "他们", "她们", "它们",
    "自己", "对方", "大家", "众人", "众位", "诸位", "彼此", "互相",
    # generic person nouns (would otherwise look like names)
    "那个", "这个", "一个", "几个", "某人", "某个", "有人", "无人",
    "那位", "这位", "某位", "一位", "几位",
    "男人", "女人", "男子", "女子", "少年", "少女", "老者", "老人",
    "孩子", "小孩", "陌生", "陌生人", "路人", "行人", "侍者", "侍女",
    "老板", "掌柜", "学生", "老师", "弟子", "师父", "师傅",
    # Place / scene words commonly captured by 2-4 hanzi regex
    "城里", "村里", "巷子", "街道", "屋内", "屋外", "门口", "门外",
    "远处", "近处", "身后", "身前", "身边", "周围", "前方", "后方",
    "茶寮", "酒馆", "客栈", "庭院", "院子", "屋子", "房间", "走廊",
    "屋檐", "窗外", "窗前", "桌前", "桌边", "床上", "椅上",
    # time / abstract
    "刚才", "片刻", "瞬间", "今日", "昨日", "明日", "今夜", "昨夜",
    "此刻", "如今", "当下", "随即", "立刻", "马上", "稍后", "之后",
    "之前", "突然", "忽然", "不知", "不料", "果然",
    # fillers
    "似乎", "仿佛", "应该", "可能", "也许", "或许", "大概",
    "什么", "怎么", "为何", "哪里", "哪边", "哪儿",
    # generic abstract
    "事情", "东西", "声音", "气息", "气味", "目光", "眼神", "表情",
})

# Context cues that strongly precede a name. Match form: <cue><name>
_NER_CONTEXT_CUES = (
    "那女子", "那男子", "那少年", "那少女", "那老者", "那老人",
    "这女子", "这男子", "这少年", "这少女", "这老者",
    "听见", "听到", "看见", "看到", "瞥见", "瞧见", "走来",
    "上前", "回头", "转身",
)

_HANZI_NAME_RE = re.compile(r"[一-龥]{2,4}")
_HANZI_RUN_RE = re.compile(r"[一-龥]+")


def _hanzi_ngrams(text: str, n_min: int = 2, n_max: int = 4) -> list[str]:
    """Yield every n-gram (n_min <= n <= n_max) inside contiguous hanzi runs.

    Sliding window — overlapping. Splits on any non-hanzi punctuation/space
    so "小菱颤抖。她抬头" produces ngrams over "小菱颤抖" and over "她抬头"
    independently. We rely on a stopword filter + frequency threshold to
    suppress n-grams that are partial words rather than names.
    """
    out: list[str] = []
    for m in _HANZI_RUN_RE.finditer(text):
        run = m.group(0)
        L = len(run)
        for n in range(n_min, n_max + 1):
            if L < n:
                break
            for i in range(L - n + 1):
                out.append(run[i : i + n])
    return out


def _explicit_npc_names_from_tags(tags: list[TagComplete]) -> set[str]:
    """Names the GM declared via <npc_update> this turn — should never be
    re-registered via NER fallback even if name extraction would catch them."""
    names: set[str] = set()
    for tag in tags:
        if tag.name != "npc_update":
            continue
        payload = parse_loose_json(tag.content)
        if isinstance(payload, dict):
            n = payload.get("name")
            if isinstance(n, str) and n.strip():
                names.add(n.strip())
    return names


def _ner_extract_candidate_names(text: str) -> set[str]:
    """Extract candidate NPC names from narrative text using cheap heuristics.

    Strategy: candidates are 2- or 3-char hanzi tokens that appear at the
    *start* of a hanzi run (i.e. right after punctuation, line break, or
    document start). This is a poor man's tokenizer — Chinese names sit at
    clause boundaries far more often than verb/object words do.

    Two signals (any one passes):
      A) frequency >= 2 across run-start positions
      B) follows a context cue (那女子, 听到, 走来, …) OR is the speaker
         right before a Chinese quote 「

    All candidates are filtered through _NER_STOPWORDS.
    """
    if not text:
        return set()

    # Pass 1: count run-start 2-char and 3-char tokens. We do NOT use 4-char
    # tokens because Chinese names are overwhelmingly 2-3 characters; allowing
    # 4 picks up too many false positives like "小菱颤抖" being read as a name.
    freq2: dict[str, int] = {}
    freq3: dict[str, int] = {}
    for m in _HANZI_RUN_RE.finditer(text):
        run = m.group(0)
        if len(run) >= 2:
            tok = run[:2]
            if tok not in _NER_STOPWORDS:
                freq2[tok] = freq2.get(tok, 0) + 1
        if len(run) >= 3:
            tok = run[:3]
            if tok not in _NER_STOPWORDS:
                freq3[tok] = freq3.get(tok, 0) + 1

    candidates: set[str] = set()

    # Signal A: run-start frequency >= 2. Prefer the 3-char prefix when both
    # the 2-char and 3-char show up — but only if the 3-char isn't an obvious
    # verbal phrase. Simpler heuristic: keep 2-char results unless a 3-char
    # superset has ≥ 2 occurrences AND the 2-char count is the same (i.e.
    # they always co-occur — meaning the 3rd char is part of the name).
    for tok2, c2 in freq2.items():
        if c2 < 2:
            continue
        # Look for a 3-char extension that occurs as often.
        ext = None
        for tok3, c3 in freq3.items():
            if tok3.startswith(tok2) and c3 == c2:
                ext = tok3
                break
        candidates.add(ext or tok2)

    # Signal B: follows a context cue. Take the next 2 hanzi (a 3-char name
    # gets picked up by the frequency signal once it appears more than once).
    # We don't try 3-char here because name + adjacent verb char is a common
    # false-positive ("小菱沉" from "...小菱沉默了").
    for cue in _NER_CONTEXT_CUES:
        idx = 0
        while True:
            i = text.find(cue, idx)
            if i < 0:
                break
            tail = text[i + len(cue) : i + len(cue) + 2]
            m = re.match(r"[一-龥]{2}", tail)
            if m:
                tok = m.group(0)
                if tok not in _NER_STOPWORDS:
                    candidates.add(tok)
            idx = i + len(cue)

    # Speaker pattern: <name>「...」 — the chars right before 「 are likely a
    # speaker. Look back 2 hanzi only (frequency signal handles 3-char names).
    for i, ch in enumerate(text):
        if ch != "「":
            continue
        end = i
        start = max(0, i - 2)
        snippet = text[start:end]
        m = re.search(r"[一-龥]{2}$", snippet)
        if m:
            tok = m.group(0)
            if tok not in _NER_STOPWORDS:
                candidates.add(tok)

    return candidates


async def _register_npc_ner_fallback(
    session: AsyncSession,
    session_id: int,
    current_turn: int,
    narrative_text: str,
    explicit_names: set[str],
) -> None:
    """Register stub NPCs for names mentioned in narrative but not declared
    via <npc_update>. Conservative — see module-level comment."""
    candidates = _ner_extract_candidate_names(narrative_text)
    if not candidates:
        return

    # Drop names already declared this turn.
    candidates -= explicit_names
    if not candidates:
        return

    # Drop names already in DB for this session.
    existing_rows = (
        await session.execute(
            select(NPC.name).where(
                NPC.session_id == session_id,
                NPC.name.in_(list(candidates)),
            )
        )
    ).scalars().all()
    existing = {n for n in existing_rows}

    for name in sorted(candidates - existing):
        session.add(
            NPC(
                session_id=session_id,
                name=name,
                description="（GM 未补全）",
                favor=0,
                state="未知",
                last_seen_turn=current_turn,
                notes_json="[]",
                purpose="",
                archetype="",
                affinity_json="{}",
                pinned=False,
            )
        )
