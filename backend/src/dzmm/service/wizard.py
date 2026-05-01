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
import re
from typing import TypeVar, Callable, Awaitable
_T = TypeVar("_T")

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
from dzmm.prompts.wizard_screenplay import build_wizard_screenplay_messages
from dzmm.prompts.wizard_world_brief import build_world_brief_messages
from dzmm.prompts.wizard_world_details import build_world_details_messages

_FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


def _strip_fence(text: str) -> str:
    text = text.strip()
    m = _FENCE_RE.match(text)
    return m.group(1).strip() if m else text


def _parse_section(md: str, header: str) -> str:
    """Extract the body of a `## <header>` section in `md`. Stops at the next
    `##` heading or end-of-string. Returns "" if not found."""
    pat = re.compile(
        rf"^##\s*{re.escape(header)}\s*$(.*?)(?=^##\s|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    m = pat.search(md)
    return m.group(1).strip() if m else ""


async def _stream_text(client: ModelClient, messages, max_tokens: int) -> str:
    chunks: list[str] = []
    async for ch in client.stream(
        messages, GenerationParams(max_tokens=max_tokens, temperature=0.85)
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


async def generate_world_brief(genre: str, theme: str, client: ModelClient) -> dict:
    async def _attempt():
        raw = await _stream_text(
            client, build_world_brief_messages(genre, theme), max_tokens=600
        )
        name = _parse_section(raw, "名字") or _parse_section(raw, "世界名") or _parse_section(raw, "世界名字")
        setting = _parse_section(raw, "年代与地点") or _parse_section(raw, "年代") or _parse_section(raw, "地点")
        conflict = _parse_section(raw, "核心冲突") or _parse_section(raw, "冲突")
        return {
            "name": name,
            "setting": setting,
            "conflict": conflict,
            "raw_md": raw,
        }
    return await _with_retry(_attempt)


async def generate_world_details(brief_md: str, client: ModelClient) -> dict:
    world_md = await _stream_text(
        client, build_world_details_messages(brief_md), max_tokens=1500
    )
    return {"world_md": world_md}


async def generate_character(
    world_md: str, archetype: str, client: ModelClient
) -> dict:
    effective_archetype = archetype.strip() or "（请根据世界观自由发挥，创造一个有深度的主角）"
    async def _attempt():
        profile = await _stream_text(
            client, build_character_messages(world_md, effective_archetype), max_tokens=1500
        )
        info = _parse_section(profile, "基本信息")
        name_match = re.search(r"姓名[:：]\s*([^\s\n]+)", info)
        if name_match is None:
            name_match = re.search(r"姓名[:：]\s*([^\s\n]+)", profile)
        name = name_match.group(1).strip("*` ") if name_match else "(未命名)"
        return {"name": name, "profile_md": profile}
    return await _with_retry(_attempt)


async def generate_npcs(
    world_md: str, character_md: str, client: ModelClient
) -> dict:
    async def _attempt():
        raw = await _stream_text(
            client, build_npcs_messages(world_md, character_md), max_tokens=1500
        )
        cleaned = _strip_fence(raw)
        try:
            npcs = json.loads(cleaned)
        except json.JSONDecodeError as e:
            raise ValueError(f"NPCs JSON parse error: {e}; raw={raw[:200]!r}") from e
        if not isinstance(npcs, list):
            raise ValueError(f"NPCs JSON must be a list, got {type(npcs).__name__}")
        npcs = [n for n in npcs if isinstance(n, dict) and n.get("name")]
        return {"npcs": npcs}
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
                "格式：{\"name\":\"...\",\"description\":\"...\",\"archetype\":\"...\",\"purpose\":\"...\"}"
            ),
        },
        {"role": "user", "content": f"NPC 提示：{hint_text}"},
    ]

    async def _attempt():
        raw = await _stream_text(client, messages, max_tokens=400)
        cleaned = _strip_fence(raw)
        try:
            npc = json.loads(cleaned)
        except json.JSONDecodeError as e:
            raise ValueError(f"single NPC JSON error: {e}; raw={raw[:200]!r}") from e
        if not isinstance(npc, dict) or not npc.get("name"):
            raise ValueError(f"invalid NPC shape: {npc!r}")
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
            max_tokens=2500,
        )
        cleaned = _strip_fence(raw)
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
    for npc_data in (bundle.get("pinned_npcs") or []):
        if not isinstance(npc_data, dict):
            continue
        name = str(npc_data.get("name") or "").strip()
        if not name:
            continue
        npc = NPC(
            session_id=sess.id,
            name=name[:120],
            description=str(npc_data.get("description") or "")[:1000],
            purpose=str(npc_data.get("motivation") or npc_data.get("purpose") or "")[:1000],
            archetype=str(npc_data.get("role") or npc_data.get("archetype") or "")[:120],
            pinned=True,
            revealed_json=revealed_name_only,
        )
        session.add(npc)

    # 5. Screenplay
    sp = Screenplay(
        session_id=sess.id,
        version=1,
        genre=str(bundle.get("genre") or "")[:60],
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

    return sess.id
