"""v0.2.0 wizard service — multi-step world / character / screenplay generation.

Six functions:
- generate_world_brief(genre, theme, client) -> {name, setting, conflict, raw_md}
- generate_world_details(brief_md, client) -> {world_md}
- generate_character(world_md, archetype, client) -> {name, profile_md}
- generate_npcs(world_md, character_md, client) -> {npcs: [...]}
- generate_screenplay_from_wizard(world_md, character_md, npcs, genre, client)
    -> {chapters, main_characters, ending, opening_hook}
- finalize_wizard(session, bundle) -> int (new session_id)
    Atomic create World + Character + Session + pinned NPCs + Screenplay.
"""
import json
import logging
import re
from typing import TypeVar, Callable, Awaitable
_T = TypeVar("_T")

log = logging.getLogger(__name__)

from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.db.models import (
    Character,
    NPC,
    Screenplay,
    Session as GameSession,
    World,
)
from dzmm.models.client import GenerationParams, ModelClient

from dzmm.prompts.wizard_character import build_character_messages
from dzmm.prompts.wizard_npcs import build_npcs_messages
from dzmm.prompts.wizard_refine_theme import build_refine_theme_messages
from dzmm.prompts.wizard_screenplay import build_wizard_screenplay_messages
from dzmm.prompts.wizard_suggest import build_suggest_messages
from dzmm.prompts.wizard_suggest_archetypes import build_suggest_archetypes_messages
from dzmm.prompts.wizard_suggest_npcs import build_suggest_npcs_messages
from dzmm.prompts.wizard_world_brief import build_world_brief_messages
from dzmm.prompts.wizard_world_details import build_world_details_messages

_FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


def _strip_fence(text: str) -> str:
    text = text.strip()
    m = _FENCE_RE.match(text)
    return m.group(1).strip() if m else text


_TRAILING_COMMA_RE = re.compile(r",\s*([}\]])")
# Python-style literals that some models emit instead of JSON literals
_PY_BOOL_RE = re.compile(r"\bTrue\b|\bFalse\b|\bNone\b")
_PY_BOOL_MAP = {"True": "true", "False": "false", "None": "null"}
# Models that saw {{...}} in the prompt may echo doubled braces
_DOUBLE_BRACE_RE = re.compile(r"\{\{|\}\}")


def _extract_json(text: str) -> str:
    """Extract the outermost {...} or [...] block from text and clean it.

    Handles common local-model quirks:
    - Prefix text ("Here is your JSON:\\n{...}")
    - Trailing markdown fences
    - Trailing commas before } or ]
    - Python-style True/False/None instead of true/false/null
    """
    text = text.strip()
    # Try fence strip first
    m = _FENCE_RE.match(text)
    if m:
        text = m.group(1).strip()
    # Collapse doubled braces that models copy from {{...}} prompt examples
    text = _DOUBLE_BRACE_RE.sub(lambda m: m.group()[0], text)

    # Find whichever comes first: '{' or '['
    obj_start = text.find("{")
    arr_start = text.find("[")
    if obj_start == -1 and arr_start == -1:
        return text
    if obj_start == -1:
        start = arr_start
    elif arr_start == -1:
        start = obj_start
    else:
        start = min(obj_start, arr_start)

    open_ch = text[start]
    close_ch = "}" if open_ch == "{" else "]"
    depth = 0
    for i, ch in enumerate(text[start:], start):
        if ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth == 0:
                extracted = text[start : i + 1]
                extracted = _TRAILING_COMMA_RE.sub(r"\1", extracted)
                extracted = _PY_BOOL_RE.sub(lambda m: _PY_BOOL_MAP[m.group()], extracted)
                return extracted
    # Truncated JSON: return from start to end and still clean
    tail = _TRAILING_COMMA_RE.sub(r"\1", text[start:])
    return _PY_BOOL_RE.sub(lambda m: _PY_BOOL_MAP[m.group()], tail)


_VALID_GENDERS = {"male", "female"}
_GENDER_ALIASES = {
    "男": "male", "男性": "male", "m": "male", "boy": "male", "man": "male",
    "女": "female", "女性": "female", "f": "female", "girl": "female", "woman": "female",
}


def _normalize_gender(raw: object) -> str:
    """Coerce free-form gender input into the strict `male` / `female` enum.
    Returns "" for empty / unrecognized values — the GM prompt and dossier
    treat that as legacy/unset."""
    if not raw:
        return ""
    s = str(raw).strip().lower()
    if not s:
        return ""
    if s in _VALID_GENDERS:
        return s
    return _GENDER_ALIASES.get(s, "")


def _unwrap_npc_list(data: object) -> list:
    """Accept any of:
    - bare list `[{...}, {...}]`
    - `{"npcs": [...]}` (or NPCs / npc_list / characters)
    - bare single NPC dict `{"name": ..., ...}` — local models sometimes drop
      the wrapping array when only one NPC is generated. We treat it as a
      single-element list so the wizard doesn't fail outright.
    """
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("npcs", "NPCs", "npc_list", "characters"):
            if isinstance(data.get(key), list):
                return data[key]
        if "name" in data and isinstance(data.get("name"), str):
            log.warning(
                "wizard NPC generation returned a single object instead of an array; wrapping. keys=%s",
                sorted(data.keys()),
            )
            return [data]
    raise ValueError(f"Cannot extract NPC list from {type(data).__name__}: {str(data)[:200]}")


def _parse_section(md: str, header: str) -> str:
    """Extract the body of a `## <header>` section in `md`. Stops at the next
    `##` heading or end-of-string. Returns "" if not found."""
    pat = re.compile(
        rf"^##\s*{re.escape(header)}\s*$(.*?)(?=^##\s|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    m = pat.search(md)
    return m.group(1).strip() if m else ""


async def _stream_text(
    client: ModelClient, messages, max_tokens: int, json_mode: bool = False
) -> str:
    chunks: list[str] = []
    async for ch in client.stream(
        messages, GenerationParams(max_tokens=max_tokens, temperature=0.85, json_mode=json_mode)
    ):
        if ch.delta:
            chunks.append(ch.delta)
    return "".join(chunks).strip()


async def _with_retry(
    fn: Callable[[], Awaitable[_T]],
    max_attempts: int = 3,
) -> _T:
    last_err: Exception = RuntimeError("no attempts made")
    for _ in range(max_attempts):
        try:
            return await fn()
        except (ValueError, json.JSONDecodeError) as e:
            last_err = e
    raise last_err


def _render_brief_md(name: str, setting: str, conflict: str) -> str:
    """Render brief JSON fields into the markdown blob shape consumed by
    world_details (it expects `## 名字`/`## 年代与地点`/`## 核心冲突`)."""
    return (
        f"## 名字\n{name.strip()}\n\n"
        f"## 年代与地点\n{setting.strip()}\n\n"
        f"## 核心冲突\n{conflict.strip()}\n"
    )


def _parse_brief_json(raw: str) -> dict:
    """Parse the JSON the model emits and return a dict with name/setting/
    conflict/raw_md. raw_md is synthesized from the three fields so legacy
    consumers (world_details prompt, frontend `brief_md`) keep working."""
    extracted = _extract_json(raw)
    data = json.loads(extracted)
    if not isinstance(data, dict):
        raise ValueError(f"world_brief expected JSON object, got {type(data).__name__}")
    name = str(data.get("name") or "").strip()
    setting = str(data.get("setting") or "").strip()
    conflict = str(data.get("conflict") or "").strip()
    if not (name and setting and conflict):
        raise ValueError(
            f"world_brief missing required fields (got: name={bool(name)}, "
            f"setting={bool(setting)}, conflict={bool(conflict)})"
        )
    return {
        "name": name,
        "setting": setting,
        "conflict": conflict,
        "raw_md": _render_brief_md(name, setting, conflict),
    }


async def generate_world_brief(genre: str, theme: str, client: ModelClient) -> dict:
    async def _attempt():
        raw = await _stream_text(
            client, build_world_brief_messages(genre, theme), max_tokens=600,
            json_mode=True,
        )
        return _parse_brief_json(raw)
    return await _with_retry(_attempt)


async def generate_world_details(brief_md: str, client: ModelClient) -> dict:
    world_md = await _stream_text(
        client, build_world_details_messages(brief_md), max_tokens=1500
    )
    return {"world_md": world_md}


def _parse_character_json(raw: str) -> dict:
    """Parse `{"name": "...", "profile_md": "...markdown..."}`. Falls back
    to regex-on-markdown if the model emitted markdown directly (older
    behavior) so we don't break sessions while local models adapt."""
    try:
        data = json.loads(_extract_json(raw))
    except json.JSONDecodeError as e:
        # If the body looks like the model *tried* to emit JSON but failed
        # (truncation / mismatched quotes), fall back to markdown regex
        # would match `姓名:` and `性别:` from inside the half-baked JSON
        # literal — which produces garbage like name="伊诺克·菲利普斯\n-"
        # and a profile_md that's actually the raw JSON text. Better to
        # raise so _with_retry kicks in (or surfaces an error).
        if raw.lstrip().startswith("{"):
            raise ValueError(
                f"character JSON appeared malformed (likely truncated): {e}; "
                f"head={raw[:120]!r}"
            ) from e

        # Legacy fallback: model returned actual markdown instead of JSON.
        log.warning("character generation returned non-JSON; falling back to markdown regex")
        info = _parse_section(raw, "基本信息")
        # `[^\s\n\\]+` excludes backslash so a stray `\n` literal in the
        # raw text doesn't get glued onto the name.
        m = (
            re.search(r"姓名[:：]\s*([^\s\n\\]+)", info)
            or re.search(r"姓名[:：]\s*([^\s\n\\]+)", raw)
        )
        name = m.group(1).strip("*` ") if m else "(未命名)"
        gm = (
            re.search(r"性别[:：]\s*([^\s\n*`\\]+)", info)
            or re.search(r"性别[:：]\s*([^\s\n*`\\]+)", raw)
        )
        gender = _normalize_gender(gm.group(1)) if gm else ""
        return {"name": name, "gender": gender, "profile_md": raw}

    if not isinstance(data, dict):
        raise ValueError(f"character JSON expected object, got {type(data).__name__}")
    name = str(data.get("name") or "").strip().strip("*` ")
    profile_md = str(data.get("profile_md") or "").strip()
    gender = _normalize_gender(data.get("gender"))
    if not gender:
        # Try to extract from profile_md (`性别：男 / 女`).
        m = re.search(r"性别[:：]\s*([^\s\n*`]+)", profile_md)
        if m:
            gender = _normalize_gender(m.group(1))
    if not name:
        # Last-ditch: try to extract from profile_md regex.
        m = re.search(r"姓名[:：]\s*([^\s\n]+)", profile_md)
        name = m.group(1).strip("*` ") if m else "(未命名)"
    if not profile_md:
        raise ValueError("character JSON missing profile_md")
    return {"name": name, "gender": gender, "profile_md": profile_md}


async def generate_character(
    world_md: str, archetype: str, client: ModelClient
) -> dict:
    effective_archetype = archetype.strip() or "（请根据世界观自由发挥，创造一个有深度的主角）"
    async def _attempt():
        # 2500 tokens: profile body alone runs 600-1500 chars, and the JSON
        # envelope adds ~200 chars of structural overhead. 1800 was getting
        # truncated mid-string, leading to malformed JSON that fell through
        # to the markdown regex fallback (and rendered raw JSON as profile).
        raw = await _stream_text(
            client, build_character_messages(world_md, effective_archetype),
            max_tokens=2500, json_mode=True,
        )
        return _parse_character_json(raw)
    return await _with_retry(_attempt)


async def generate_npcs(
    world_md: str, character_md: str, client: ModelClient
) -> dict:
    async def _attempt():
        raw = await _stream_text(
            client, build_npcs_messages(world_md, character_md), max_tokens=1800,
            json_mode=True,
        )
        try:
            data = json.loads(_extract_json(raw))
        except json.JSONDecodeError as e:
            raise ValueError(f"NPCs JSON parse error: {e}; raw={raw[:200]!r}") from e
        npcs = _unwrap_npc_list(data)
        out: list[dict] = []
        for n in npcs:
            if not isinstance(n, dict) or not n.get("name"):
                continue
            n["gender"] = _normalize_gender(n.get("gender"))
            out.append(n)
        return {"npcs": out}
    return await _with_retry(_attempt)


async def generate_single_npc(
    world_md: str,
    character_md: str,
    hint: str,
    client: ModelClient,
) -> dict:
    """Generate one NPC based on a player-provided hint (archetype / role / name)."""
    hint_text = hint.strip() or "（根据世界观自由发挥）"
    messages = [
        {
            "role": "system",
            "content": (
                f"世界观：\n{world_md}\n\n主角：\n{character_md}\n\n"
                "你是世界观设计师。根据以下提示，生成**1个**主要 NPC，输出纯 JSON（无 markdown fence）。\n"
                "格式：{\"name\":\"...\",\"gender\":\"male 或 female（必填）\","
                "\"description\":\"...\",\"archetype\":\"...\",\"purpose\":\"...\"}"
            ),
        },
        {"role": "user", "content": f"NPC 提示：{hint_text}"},
    ]

    async def _attempt():
        raw = await _stream_text(client, messages, max_tokens=400, json_mode=True)
        try:
            npc = json.loads(_extract_json(raw))
        except json.JSONDecodeError as e:
            raise ValueError(f"single NPC JSON error: {e}; raw={raw[:200]!r}") from e
        if not isinstance(npc, dict) or not npc.get("name"):
            raise ValueError(f"invalid NPC shape: {npc!r}")
        npc["gender"] = _normalize_gender(npc.get("gender"))
        return npc

    return await _with_retry(_attempt)


async def generate_screenplay_from_wizard(
    world_md: str,
    character_md: str,
    npcs: list,
    genre: str,
    client: ModelClient,
) -> dict:
    async def _attempt():
        raw = await _stream_text(
            client,
            build_wizard_screenplay_messages(
                world_md=world_md,
                character_md=character_md,
                npcs=list(npcs or []),
                genre=genre,
            ),
            max_tokens=4000,
            json_mode=True,
        )
        cleaned = _extract_json(raw)
        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError as e:
            raise ValueError(
                f"screenplay JSON parse error: {e}; raw={raw[:200]!r}"
            ) from e
        if not isinstance(data, dict):
            raise ValueError("screenplay JSON root must be an object")
        return data
    return await _with_retry(_attempt)


async def finalize_wizard(
    session: AsyncSession,
    bundle: dict,
) -> int:
    """Atomic create World + Character + Session + pinned NPCs + Screenplay.

    Caller is responsible for `await session.commit()` on success and
    `await session.rollback()` on the exception we raise — this function
    only `flush`es so the IDs are populated for FK references.
    """
    if not isinstance(bundle, dict):
        raise ValueError("bundle must be a dict")

    try:
        world_data = bundle["world"]
        char_data = bundle["character"]
        sp_data = bundle["screenplay"]
        session_name = bundle["session_name"]
        gm_mid = int(bundle["gm_model_config_id"])
        sum_mid = int(bundle["summarizer_model_config_id"])
    except (KeyError, TypeError, ValueError) as e:
        raise ValueError(f"missing or invalid bundle field: {e}") from e

    if not isinstance(world_data, dict) or not isinstance(char_data, dict) \
            or not isinstance(sp_data, dict):
        raise ValueError("bundle.world / character / screenplay must be objects")

    # 1. World
    world = World(
        name=str(world_data.get("name") or "(未命名世界)")[:120],
        content_md=str(world_data.get("content_md") or ""),
        style=str(world_data.get("style") or "realistic")[:40],
    )
    session.add(world)
    await session.flush()

    # 2. Character
    char = Character(
        world_id=world.id,
        name=str(char_data.get("name") or "(未命名)")[:120],
        gender=_normalize_gender(char_data.get("gender")),
        profile_md=str(char_data.get("profile_md") or ""),
        base_stats_json=str(char_data.get("base_stats_json") or "{}"),
    )
    session.add(char)
    await session.flush()

    # 3. Session
    sess = GameSession(
        name=str(session_name or "(未命名存档)")[:120],
        world_id=world.id,
        character_id=char.id,
        gm_model_config_id=gm_mid,
        summarizer_model_config_id=sum_mid,
    )
    session.add(sess)
    await session.flush()

    # 4. Pinned NPCs (v0.2.2: only `name` is revealed by default — GM should
    # progressively reveal description/purpose/archetype via <npc_update> as
    # the story unfolds. Previously we revealed everything here, which made
    # the opening feel "spoiler-loaded" — players saw all archetypes and
    # motivations before they ever met the NPC.)
    revealed_name_only = json.dumps({"name": True})
    created_npcs: list[NPC] = []
    for npc_data in (bundle.get("pinned_npcs") or []):
        if not isinstance(npc_data, dict):
            continue
        name = str(npc_data.get("name") or "").strip()
        if not name:
            continue
        npc = NPC(
            session_id=sess.id,
            name=name[:120],
            gender=_normalize_gender(npc_data.get("gender")),
            description=str(npc_data.get("description") or "")[:1000],
            purpose=str(npc_data.get("motivation") or npc_data.get("purpose") or "")[:1000],
            archetype=str(npc_data.get("role") or npc_data.get("archetype") or "")[:120],
            pinned=True,
            revealed_json=revealed_name_only,
        )
        session.add(npc)
        created_npcs.append(npc)

    # 5. Screenplay (carry pc_gender so future sessions cloned from this
    # screenplay get the same gender on their PC)
    sp = Screenplay(
        session_id=sess.id,
        version=1,
        genre=str(bundle.get("genre") or "")[:60],
        pc_name=char.name,
        pc_gender=char.gender,
        pc_profile_md=char.profile_md,
        pc_base_stats_json=char.base_stats_json,
        chapters_json=json.dumps(sp_data.get("chapters", []), ensure_ascii=False),
        main_characters_json=json.dumps(
            sp_data.get("main_characters", []), ensure_ascii=False
        ),
        ending_md=str(sp_data.get("ending_md") or sp_data.get("ending") or "")[:2000],
        opening_hook=str(sp_data.get("opening_hook") or "")[:2000],
        current_chapter=1,
        completed_events_json="[]",
        status="active",
    )
    session.add(sp)
    await session.flush()

    # Flush NPCs to get their IDs
    for npc in created_npcs:
        await session.refresh(npc)

    return {
        "session_id": sess.id,
        "world_id": world.id,
        "npc_ids": {npc.name: npc.id for npc in created_npcs},
    }


# ---------------------------------------------------------------------------
# Streaming variants — yield (event_type, data_dict) pairs for SSE endpoints.
# Protocol:  "delta"  → {"text": "..."}   raw token chunk
#            "result" → {...parsed data...} on success
#            "error"  → {"message": "..."}  on failure
# ---------------------------------------------------------------------------

from collections.abc import AsyncGenerator  # noqa: E402 (local import fine here)

_StreamYield = AsyncGenerator[tuple[str, dict], None]


async def stream_world_brief(genre: str, theme: str, client: ModelClient) -> _StreamYield:
    messages = build_world_brief_messages(genre, theme)
    chunks: list[str] = []
    async for ch in client.stream(
        messages, GenerationParams(max_tokens=800, temperature=0.85, json_mode=True),
    ):
        if ch.delta:
            chunks.append(ch.delta)
            yield "delta", {"text": ch.delta}
    raw = "".join(chunks).strip()
    try:
        result = _parse_brief_json(raw)
    except (ValueError, json.JSONDecodeError) as e:
        log.warning("stream_world_brief JSON parse failed: %s; raw=%r", e, raw[:200])
        yield "error", {"message": f"基础设定 JSON 解析失败：{e}"}
        return
    yield "result", result


async def stream_world_details(brief_md: str, client: ModelClient) -> _StreamYield:
    messages = build_world_details_messages(brief_md)
    chunks: list[str] = []
    async for ch in client.stream(messages, GenerationParams(max_tokens=1800, temperature=0.85)):
        if ch.delta:
            chunks.append(ch.delta)
            yield "delta", {"text": ch.delta}
    world_md = "".join(chunks).strip()
    yield "result", {"world_md": world_md}


async def stream_character(world_md: str, archetype: str, client: ModelClient) -> _StreamYield:
    effective = archetype.strip() or "（请根据世界观自由发挥，创造一个有深度的主角）"
    messages = build_character_messages(world_md, effective)
    chunks: list[str] = []
    # 2500 tokens — see generate_character for rationale (JSON envelope
    # was getting truncated at 1800).
    async for ch in client.stream(
        messages, GenerationParams(max_tokens=2500, temperature=0.85, json_mode=True),
    ):
        if ch.delta:
            chunks.append(ch.delta)
            yield "delta", {"text": ch.delta}
    raw = "".join(chunks).strip()
    try:
        result = _parse_character_json(raw)
    except (ValueError, json.JSONDecodeError) as e:
        log.warning("stream_character JSON parse failed: %s; raw=%r", e, raw[:200])
        yield "error", {"message": f"角色 JSON 解析失败：{e}"}
        return
    yield "result", result


async def stream_npcs(world_md: str, character_md: str, client: ModelClient) -> _StreamYield:
    messages = build_npcs_messages(world_md, character_md)
    chunks: list[str] = []
    async for ch in client.stream(messages, GenerationParams(max_tokens=1800, temperature=0.85, json_mode=True)):
        if ch.delta:
            chunks.append(ch.delta)
            yield "delta", {"text": ch.delta}
    raw = "".join(chunks).strip()
    try:
        data = json.loads(_extract_json(raw))
        npcs = _unwrap_npc_list(data)
        npcs = [n for n in npcs if isinstance(n, dict) and n.get("name")]
        yield "result", {"npcs": npcs}
    except Exception as e:
        yield "error", {"message": f"NPC 解析失败: {e}"}


async def stream_screenplay(
    world_md: str, character_md: str, npcs: list, genre: str, client: ModelClient,
) -> _StreamYield:
    messages = build_wizard_screenplay_messages(
        world_md=world_md, character_md=character_md, npcs=list(npcs or []), genre=genre,
    )
    chunks: list[str] = []
    async for ch in client.stream(messages, GenerationParams(max_tokens=4000, temperature=0.85, json_mode=True)):
        if ch.delta:
            chunks.append(ch.delta)
            yield "delta", {"text": ch.delta}
    raw = "".join(chunks).strip()
    try:
        data = json.loads(_extract_json(raw))
        if not isinstance(data, dict):
            raise ValueError("screenplay root must be object")
        yield "result", data
    except Exception as e:
        yield "error", {"message": f"剧本解析失败: {e}"}


async def suggest_archetypes(world_md: str, client: ModelClient) -> dict:
    """Generate 4 world-aware character archetype suggestions."""
    async def _attempt():
        raw = await _stream_text(
            client, build_suggest_archetypes_messages(world_md), max_tokens=600,
            json_mode=True,
        )
        data = json.loads(_extract_json(raw))
        archetypes = data.get("archetypes", [])
        validated = [
            {"description": str(a["description"])[:60], "hook": str(a.get("hook", ""))[:60]}
            for a in archetypes
            if isinstance(a, dict) and a.get("description")
        ]
        if not validated:
            raise ValueError("empty archetypes")
        return {"archetypes": validated}
    return await _with_retry(_attempt)


async def suggest_npcs(world_md: str, character_md: str, client: ModelClient) -> dict:
    """Generate 4 world+character-aware NPC suggestions."""
    async def _attempt():
        raw = await _stream_text(
            client, build_suggest_npcs_messages(world_md, character_md), max_tokens=800,
            json_mode=True,
        )
        data = json.loads(_extract_json(raw))
        npcs = data.get("npcs", [])
        validated = [
            {
                "name": str(n["name"])[:20],
                "gender": _normalize_gender(n.get("gender")),
                "role": str(n.get("role", ""))[:20],
                "description": str(n.get("description", ""))[:200],
                "motivation": str(n.get("motivation", ""))[:100],
            }
            for n in npcs
            if isinstance(n, dict) and n.get("name")
        ]
        if not validated:
            raise ValueError("empty npcs")
        return {"npcs": validated}
    return await _with_retry(_attempt)


async def refine_theme(genre: str, rough: str, client: ModelClient) -> dict:
    """Refine a rough direction into a polished one-line theme."""
    raw = await _stream_text(
        client, build_refine_theme_messages(genre, rough), max_tokens=200
    )
    # Strip any accidental quotes or leading/trailing punctuation the model adds
    theme = raw.strip().strip('"\'""')
    return {"theme": theme}


async def generate_suggestions(genre_hint: str, client: ModelClient) -> dict:
    """Generate 4 creative game scenario packages (genre + theme + archetype)."""
    async def _attempt():
        raw = await _stream_text(
            client, build_suggest_messages(genre_hint), max_tokens=800, json_mode=True,
        )
        data = json.loads(_extract_json(raw))
        suggestions = data.get("suggestions", [])
        validated = []
        for s in suggestions:
            if isinstance(s, dict) and s.get("genre") and s.get("theme") and s.get("archetype"):
                validated.append({
                    "genre": str(s["genre"])[:20],
                    "theme": str(s["theme"])[:200],
                    "archetype": str(s["archetype"])[:100],
                })
        if not validated:
            raise ValueError("empty suggestions")
        return {"suggestions": validated}
    return await _with_retry(_attempt)
