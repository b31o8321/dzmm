"""NPC-related state_apply handlers.

Carved out of `_impl.py` in r3-a. Covers:
  - <npc_update> handler + progressive-reveal bookkeeping

The dispatcher (`apply_tags` in `_impl.py`) imports the handlers below;
shared helpers (e.g. `_normalize_for_dedup`) remain in `_impl.py`.
"""

import json
import logging
import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.db.models import NPC
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
_NER_STOPWORDS: frozenset[str] = frozenset({
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

# v0.2.1 — playtest 72 turns produced 24 NPCs in the table; 20 were NER junk
# (里面/写着/塞巴/奥斯特 etc). Bumping freq + min 3 chars wasn't enough. This
# extends _NER_STOPWORDS with 70+ high-frequency junk fragments observed in
# real play. Categories: status/position words, verb+particle 2-char fragments,
# 「的 X」combos, qty/qty-marker pairs, common verbs, time/sequence markers.
_PLAYTEST_STOPWORDS_V0_2_1: frozenset[str] = frozenset({
    # exact garbage observed in playtest
    "里面", "写着", "印着", "面对", "标签",
    # verb + particle pairs (verb + 了/我/他/她/它)
    "了你", "了我", "了他", "了她", "了它", "了一",
    "我从", "她从", "他从",
    "她轻", "她说", "她来", "她去", "她想",
    "他说", "他来", "他去", "他想",
    "我说", "我想", "我来", "我去",
    # 「的 X」 combinations
    "的一", "的那", "的黑", "的白", "的红", "的人", "的事", "的话",
    "的手", "的眼",
    # adjectives + classifiers / numerals
    "一丝", "一缕", "一阵", "一瞬", "一时", "一片", "一切",
    "几个", "好几", "许多", "很多", "若干", "一些", "全部", "所有",
    # verbs commonly captured at run-start
    "个叫", "远叫", "走过", "走来", "走出", "走进", "走到", "走去",
    "看见", "看到", "听见", "听到", "感觉", "感受",
    "想到", "想着", "认为", "知道", "明白", "了解",
    "起来", "下去", "过来", "过去", "出去", "进来",
    # time / sequence markers
    "然后", "于是", "接着", "随后", "之后", "起初", "最后", "终于",
    "现在", "刚才", "马上", "立刻", "瞬间", "片刻",
})

# Merge into a single set used at filter time. _NER_STOPWORDS is re-bound
# above as a set to preserve the original public symbol but include v0.2.1
# additions.
_NER_STOPWORDS = frozenset(_NER_STOPWORDS | _PLAYTEST_STOPWORDS_V0_2_1)

# v0.2.1 P0.1 (4): when a candidate's first char is one of these high-frequency
# verb / particle / connector starters, require length >= 4 chars. Names that
# start with these are extremely rare; almost all 2-3 char hits are verb
# phrases or connective fragments.
_FIRST_CHAR_NEEDS_LONGER: frozenset[str] = frozenset(
    "了的着我她他一这那有被把给为之从"
)

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

# v0.2.1: bumped min length from 2 → 3. Real-play 2-char hits are
# overwhelmingly verb/particle fragments (了你/我从/她轻/印着/写着/...) rather
# than independent names. Genuine 2-char Chinese names (李华/小菱) now have to
# be picked up via context cue + at least one extra cue char, or be declared
# explicitly via <npc_update>. Trade-off: lose a few legit short names; gain
# a much cleaner NPC table.
_HANZI_NAME_RE = re.compile(r"[一-龥]{3,}")
_HANZI_RUN_RE = re.compile(r"[一-龥]+")


def _pc_name_substrings(character_name: str, min_len: int = 2) -> frozenset[str]:
    """Compute every contiguous substring (length >= min_len, capped at 4
    chars) of a PC name. Used to suppress NER hits that are subsets of the PC's
    own name — e.g. "塞巴" / "塞巴斯" / "奥斯特" must never become NPCs when the
    PC is "塞巴斯蒂安·冯·奥斯特".

    Splits on whitespace, mid-dot/Bopomofo dot/hyphen/underscore, and strips
    parenthesised glosses ("(英雄人物)"), then takes substrings of each
    surviving token. Output capped at 4-char substrings — longer than that
    and the candidate would never be a legit short-NPC NER hit anyway.
    """
    if not character_name:
        return frozenset()
    # Drop parenthesised glosses (both half-width and full-width parens).
    cleaned = re.sub(r"[（(].*?[)）]", "", character_name).strip()
    out: set[str] = set()
    for token in re.split(r"[\s·•．\-—_]+", cleaned):
        if len(token) < min_len:
            continue
        L = len(token)
        for i in range(L):
            for j in range(i + min_len, min(i + 5, L + 1)):
                sub = token[i:j]
                if len(sub) >= min_len:
                    out.add(sub)
    return frozenset(out)


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


def _passes_first_char_threshold(name: str) -> bool:
    """v0.2.1 (4): if a candidate starts with one of the verb/particle/
    connector chars in _FIRST_CHAR_NEEDS_LONGER (了/的/着/我/她/他/一/这/那/有
    /被/把/给/为/之/从), require >= 4 chars before accepting. Names beginning
    with these are extremely rare; almost all 2-3 char hits are verb phrases
    or function-word fragments (了你 / 我从 / 她轻 / 个叫)."""
    if not name:
        return False
    if name[0] in _FIRST_CHAR_NEEDS_LONGER and len(name) < 4:
        return False
    return True


def _ner_extract_candidate_names(
    text: str,
    *,
    pc_substrings: frozenset[str] = frozenset(),
) -> set[str]:
    """Extract candidate NPC names from narrative text using cheap heuristics.

    Strategy: candidates are 3+ char hanzi tokens at the *start* of a hanzi
    run (right after punctuation, line break, or document start). This is a
    poor man's tokenizer — Chinese names sit at clause boundaries far more
    often than verb/object words do.

    v0.2.1 — playtest-driven strictness bump:
      • min length raised 2 → 3 chars (kills 里面/写着/塞巴/了你 etc.)
      • PC name substrings always rejected (塞巴/奥斯特 from PC 塞巴斯蒂安·冯·
        奥斯特 must not become independent NPCs)
      • first-char threshold: 了/的/着/我/她/他/一/this/that/有/被/把/给/为/之/
        从 require >= 4 chars
      • _NER_STOPWORDS expanded with 70+ playtest-observed junk fragments

    Two signals (any one passes):
      A) frequency >= 3 across run-start positions (v0.1.9 threshold)
      B) follows a context cue (那女子, 听到, 走来, …) OR is the speaker
         right before a Chinese quote 「

    All candidates pass through _NER_STOPWORDS, _passes_first_char_threshold,
    and the PC-substring filter.
    """
    if not text:
        return set()

    def _accept(tok: str) -> bool:
        """Combined post-extraction filter."""
        if not tok or len(tok) < 3:
            return False
        if tok in _NER_STOPWORDS:
            return False
        if tok in pc_substrings:
            return False
        if not _passes_first_char_threshold(tok):
            return False
        return True

    # Pass 1: count run-start 3-char and 4-char tokens. v0.2.1 dropped 2-char
    # entirely — too noisy in real play. 4-char captures slightly longer names
    # (赵铁柱兄 etc) but more importantly lets the first-char-threshold rule
    # accept a "了..."/"她..." 4-char run where the first char belongs to the
    # name (rare but real, e.g. 「了空大师」).
    freq3: dict[str, int] = {}
    freq4: dict[str, int] = {}
    for m in _HANZI_RUN_RE.finditer(text):
        run = m.group(0)
        if len(run) >= 3:
            tok = run[:3]
            if tok not in _NER_STOPWORDS:
                freq3[tok] = freq3.get(tok, 0) + 1
        if len(run) >= 4:
            tok = run[:4]
            if tok not in _NER_STOPWORDS:
                freq4[tok] = freq4.get(tok, 0) + 1

    candidates: set[str] = set()

    # Signal A: run-start frequency >= 3. Prefer the 4-char prefix when both
    # the 3-char and 4-char show up at the same count (they always co-occur
    # → the 4th char is part of the name).
    for tok3, c3 in freq3.items():
        if c3 < 3:
            continue
        # Look for a 4-char extension that occurs as often.
        ext = None
        for tok4, c4 in freq4.items():
            if tok4.startswith(tok3) and c4 == c3:
                ext = tok4
                break
        if tok3[0] in _NER_VERBAL_HEAD_CHARS and ext is None:
            # Verb-led 3-char with no equally-frequent 4-char extension —
            # almost certainly a verbal phrase, not a name. Drop.
            continue
        candidate = ext or tok3
        if _accept(candidate):
            candidates.add(candidate)

    # Signal B: follows a context cue. Take the next 3 hanzi (v0.2.1 raised
    # 2 → 3 to match the new minimum). 4-char names get picked up by the
    # frequency signal when they appear more than once.
    for cue in _NER_CONTEXT_CUES:
        idx = 0
        while True:
            i = text.find(cue, idx)
            if i < 0:
                break
            tail = text[i + len(cue) : i + len(cue) + 3]
            m = re.match(r"[一-龥]{3}", tail)
            if m:
                tok = m.group(0)
                # v0.1.9: skip verb-led tokens via context cue too; they're
                # almost always "看见/听见/走来 + verb" pattern.
                if (
                    tok[0] not in _NER_VERBAL_HEAD_CHARS
                    and _accept(tok)
                ):
                    candidates.add(tok)
            idx = i + len(cue)

    # Speaker pattern: <name>「...」 — the chars right before 「 are likely a
    # speaker. v0.2.1: look back 3 hanzi (was 2; now matches the 3-char min).
    for i, ch in enumerate(text):
        if ch != "「":
            continue
        end = i
        start = max(0, i - 3)
        snippet = text[start:end]
        m = re.search(r"[一-龥]{3}$", snippet)
        if m:
            tok = m.group(0)
            if (
                tok[0] not in _NER_VERBAL_HEAD_CHARS
                and _accept(tok)
            ):
                candidates.add(tok)

    return candidates


async def _register_npc_ner_fallback(
    session: AsyncSession,
    session_id: int,
    current_turn: int,
    narrative_text: str,
    explicit_names: set[str],
    *,
    character_name: str = "",
) -> None:
    """Register stub NPCs for names mentioned in narrative but not declared
    via <npc_update>. Conservative — see module-level comment.

    `character_name` is the PC's name; any candidate that is a substring of
    the PC name (e.g. "塞巴" / "奥斯特" when PC is "塞巴斯蒂安·冯·奥斯特") is
    dropped to avoid creating ghost NPCs that share fragments of the player's
    own name.
    """
    pc_subs = _pc_name_substrings(character_name) if character_name else frozenset()
    candidates = _ner_extract_candidate_names(
        narrative_text, pc_substrings=pc_subs
    )
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
