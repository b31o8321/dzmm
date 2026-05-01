"""NPC-related state_apply handlers.

Carved out of `_impl.py` in r3-a. Covers:
  - <npc_update> handler + progressive-reveal bookkeeping
  - Lightweight regex-only NER fallback that registers stub NPCs the GM
    mentions in narrative but forgets to declare via <npc_update>.

The dispatcher (`apply_tags` in `_impl.py`) imports the handlers below;
shared helpers (e.g. `_normalize_for_dedup`) remain in `_impl.py`.
"""

import json
import logging
import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.db.models import NPC
from dzmm.parsing.events import TagComplete
from dzmm.parsing.repair import parse_loose_json

log = logging.getLogger(__name__)


# v0.11 progressive reveal: only these field names can be marked revealed.
# Unknown reveal targets are silently ignored. "name" is always revealed
# implicitly (defaulted in revealed_json), but listing it here is harmless.
_NPC_REVEALABLE_FIELDS = frozenset({
    "name", "description", "purpose", "archetype",
    "state", "favor", "affinity", "emotion",
})

_REVEAL_SPLIT_RE = re.compile(r"[,\s]+")


def _auto_reveal_for_create(payload: dict) -> dict:
    """When creating a new NPC, fields whose value is being set in the same
    payload (description / state / archetype / purpose / favor_delta / etc.)
    should be auto-marked revealed=true — the GM is writing them now, so the
    player has just seen them.

    name is always revealed (the GM has to name an NPC for them to exist)."""
    revealed = {"name": True}
    for f in ("description", "state", "archetype", "purpose"):
        if payload.get(f):
            revealed[f] = True
    if payload.get("favor_delta") is not None:
        revealed["favor"] = True
    if payload.get("affinity"):
        revealed["affinity"] = True
    if payload.get("emotion"):
        revealed["emotion"] = True
    return revealed


def _parse_reveal_attr(reveal_str: str) -> list[str]:
    """Split a reveal="..." attribute into a list of recognised field names.
    Accepts commas, whitespace, or both as separators. Unknown fields are
    silently dropped."""
    if not reveal_str:
        return []
    fields = [f.strip() for f in _REVEAL_SPLIT_RE.split(reveal_str) if f.strip()]
    return [f for f in fields if f in _NPC_REVEALABLE_FIELDS]


async def _apply_npc_update(
    session: AsyncSession,
    session_id: int,
    current_turn: int,
    attrs: dict[str, str],
    raw: str,
) -> None:
    # Merge attrs with body JSON. Body wins on conflict (GM is more deliberate
    # when it serialises a JSON payload than when it inlines attrs).
    payload: dict = {}
    payload.update({k: v for k, v in (attrs or {}).items()})
    body_payload = parse_loose_json(raw)
    if body_payload:
        payload.update(body_payload)

    name = payload.get("name")
    if not name:
        return
    name = str(name).strip()
    if not name:
        return

    npc = (
        await session.execute(
            select(NPC).where(NPC.session_id == session_id, NPC.name == name)
        )
    ).scalar_one_or_none()

    reveal_fields = _parse_reveal_attr(str(payload.get("reveal", "")))

    is_create = npc is None
    if is_create:
        # Special case: a payload that ONLY carries a reveal=... directive
        # against a non-existent NPC is a silent no-op. The intent is
        # "unlock previously-hidden fields"; without an existing NPC, there's
        # nothing to unlock and we don't fabricate a stub from a typo.
        # Any other shape (name only, name + value fields, etc.) creates.
        keys_other_than_name_and_reveal = [
            k for k in payload.keys() if k not in ("name", "reveal")
        ]
        if reveal_fields and not keys_other_than_name_and_reveal:
            return

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
            revealed_json=json.dumps(
                _auto_reveal_for_create(payload), ensure_ascii=False
            ),
        )
        session.add(npc)

    favor_delta_raw = payload.get("favor_delta", 0)
    favor_delta_num = 0
    if isinstance(favor_delta_raw, bool):
        favor_delta_num = 0
    elif isinstance(favor_delta_raw, (int, float)):
        favor_delta_num = int(favor_delta_raw)
    elif isinstance(favor_delta_raw, str):
        # attrs always parse as strings; tolerate an integer literal.
        try:
            favor_delta_num = int(favor_delta_raw)
        except ValueError:
            favor_delta_num = 0
    if favor_delta_num:
        npc.favor += favor_delta_num
    if "state" in payload and payload["state"] is not None:
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

    # Progressive reveal bookkeeping. Two sources merge into revealed_json:
    #   1. fields that have a concrete value in this payload
    #      (auto-revealed: GM just wrote them, so the player has seen them)
    #   2. names listed in the reveal="..." attribute
    # Both add to the existing set; never clear what was previously revealed.
    try:
        revealed = json.loads(npc.revealed_json or '{"name": true}')
        if not isinstance(revealed, dict):
            revealed = {"name": True}
    except (TypeError, ValueError):
        revealed = {"name": True}

    # Auto-reveal: any field with a meaningful value in this update was visible
    # to the player when the GM emitted it — mark revealed. (For updates only;
    # create path already auto-revealed via _auto_reveal_for_create above.)
    if not is_create:
        if payload.get("description"):
            revealed["description"] = True
        if payload.get("state") not in (None, ""):
            revealed["state"] = True
        if payload.get("archetype"):
            revealed["archetype"] = True
        if payload.get("purpose"):
            revealed["purpose"] = True
        if payload.get("favor_delta") is not None and favor_delta_num:
            revealed["favor"] = True
        if payload.get("affinity"):
            revealed["affinity"] = True
        if payload.get("emotion"):
            revealed["emotion"] = True

    for f in reveal_fields:
        revealed[f] = True

    npc.revealed_json = json.dumps(revealed, ensure_ascii=False)


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
    # v0.1.9 — extra real-game junk picked up by the freq-2 heuristic.
    # Buildings / locations
    "修道院", "教堂", "酒吧", "广场", "桌子", "椅子", "墙壁", "屋顶",
    "窗台", "大门", "窗户",
    # Nature / weather / scene atmosphere
    "雨水", "雪花", "夕阳", "月光", "星空", "海风", "沙漠", "森林",
    # Connectives / sequence markers
    "然后", "于是", "接着", "随后", "起初", "最后", "终于",
    # Verb-led fragments that NER mistakes for names
    "细的", "他不", "她不", "我不", "她说", "他说", "我说", "你说",
    "离开", "回来", "走过", "走来", "看见", "听见", "感觉", "心想",
    "起来", "下去", "过来", "过去", "出去", "进来",
    # Quantity / scope
    "全部", "所有", "好多", "许多", "一些",
})

# v0.1.9 — characters that are overwhelmingly verbs / function words at the
# start of a 2-char run; if a candidate starts with one of these, require a
# longer prefix (>= 3 chars when frequency-derived, >= 4 chars before we even
# consider a context-cue extraction). Names rarely start with these.
_NER_VERBAL_HEAD_CHARS = frozenset(
    "然后因所但并而起离进出走来去上下看听想说是不"
)

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
      A) frequency >= 3 across run-start positions (v0.1.9: was >= 2 before;
         bumped to cut down on real-play false positives like 修道院/大门/然后)
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

    # Signal A: run-start frequency >= 3 (v0.1.9 strictness bump). Prefer the
    # 3-char prefix when both the 2-char and 3-char show up at the same count,
    # i.e. they always co-occur — meaning the 3rd char is part of the name.
    # Verb-led 2-grams (started by 然/后/起/离/进/出/走/来/去/上/下/看/听/想/说/是/不/etc)
    # require the 3-char extension; bare 2-char verb-leds are dropped.
    for tok2, c2 in freq2.items():
        if c2 < 3:
            continue
        # Look for a 3-char extension that occurs as often.
        ext = None
        for tok3, c3 in freq3.items():
            if tok3.startswith(tok2) and c3 == c2:
                ext = tok3
                break
        if tok2[0] in _NER_VERBAL_HEAD_CHARS and ext is None:
            # Verb-led 2-char with no equally-frequent 3-char extension —
            # almost certainly a verbal phrase, not a name. Drop.
            continue
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
                # v0.1.9: skip verb-led tokens via context cue too; they're
                # almost always "看见/听见/走来 + verb" pattern.
                if (
                    tok not in _NER_STOPWORDS
                    and tok[0] not in _NER_VERBAL_HEAD_CHARS
                ):
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
            if (
                tok not in _NER_STOPWORDS
                and tok[0] not in _NER_VERBAL_HEAD_CHARS
            ):
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
