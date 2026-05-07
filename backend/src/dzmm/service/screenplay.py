"""Screenplay (outline) generation + progress + revision logic. Called from
session creation route and the major-plot_turn rewrite path."""
import json
import logging
import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.db.models import (
    Character,
    Screenplay,
    ScreenplayRevision,
    Session as GameSession,
    World,
)
from dzmm.models.client import GenerationParams, ModelClient
from dzmm.prompts.outliner_template import build_outliner_messages, build_rewrite_messages

log = logging.getLogger(__name__)

_FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)
_REQUIRED_KEYS = {"chapters", "main_characters", "ending", "opening_hook"}


def _strip_fence(text: str) -> str:
    text = text.strip()
    m = _FENCE_RE.match(text)
    if m:
        return m.group(1).strip()
    return text


def _parse_outline_json(raw: str) -> dict:
    cleaned = _strip_fence(raw)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise ValueError(f"outliner returned invalid JSON: {e}") from e
    if not isinstance(data, dict):
        raise ValueError(f"outliner returned non-object root: {type(data).__name__}")
    missing = _REQUIRED_KEYS - data.keys()
    if missing:
        raise ValueError(f"outliner JSON missing keys: {missing}")
    if not isinstance(data["chapters"], list) or not data["chapters"]:
        raise ValueError("outliner JSON 'chapters' must be a non-empty list")
    return data


async def generate_screenplay(
    session: AsyncSession,
    session_id: int,
    genre: str,
    custom_prompt: str,
    client: ModelClient,
    *,
    parent_screenplay_id: int | None = None,
    previous_ending: str = "",
) -> Screenplay:
    """Call outliner LLM, parse JSON, persist a new Screenplay row."""
    sess = await session.get(GameSession, session_id)
    if sess is None:
        raise ValueError(f"session {session_id} not found")
    world = await session.get(World, sess.world_id)
    char = await session.get(Character, sess.character_id)

    user_extra = custom_prompt
    if previous_ending:
        user_extra = (custom_prompt or "") + (
            f"\n\n# 上一章结局（续作起点）\n{previous_ending}\n"
            "请基于这个结局生成下一章的剧情大纲。PC 状态延续，但章节、事件、敌对势力都应该是新的。"
        )

    messages = build_outliner_messages(
        world_name=world.name if world else "",
        world_md=world.content_md if world else "",
        character_name=char.name if char else "",
        character_md=char.profile_md if char else "",
        genre=genre or "悬疑探案",
        custom_prompt=user_extra,
    )

    from dzmm.service.activity_log import log_event
    import time as _time

    log_event(session_id, "screenplay_generate_start", genre=genre,
              parent_screenplay_id=parent_screenplay_id)
    start = _time.monotonic()

    raw_chunks: list[str] = []
    try:
        async for chunk in client.stream(messages, GenerationParams(max_tokens=2000, temperature=0.7)):
            if chunk.delta:
                raw_chunks.append(chunk.delta)
    except Exception as e:
        log_event(session_id, "screenplay_generate_error",
                  duration_ms=int((_time.monotonic() - start) * 1000),
                  error=str(e)[:200])
        raise
    raw = "".join(raw_chunks)
    duration_ms = int((_time.monotonic() - start) * 1000)

    try:
        data = _parse_outline_json(raw)
    except ValueError as e:
        log_event(session_id, "screenplay_generate_error",
                  duration_ms=duration_ms, raw_chars=len(raw),
                  error=f"parse: {e}"[:200])
        raise

    sp = Screenplay(
        session_id=session_id,
        version=1,
        genre=genre,
        custom_prompt=custom_prompt[:2000],
        chapters_json=json.dumps(data["chapters"], ensure_ascii=False),
        main_characters_json=json.dumps(data["main_characters"], ensure_ascii=False),
        ending_md=str(data["ending"])[:2000],
        opening_hook=str(data["opening_hook"])[:2000],
        outline_md="",  # we keep structured JSON; raw md is optional
        current_chapter=1,
        completed_events_json="[]",
        parent_screenplay_id=parent_screenplay_id,
        status="active",
    )
    session.add(sp)
    await session.flush()
    log.info(
        "generated screenplay %d for session %d (%d chapters, genre=%s, %dms, %d chars)",
        sp.id, session_id, len(data["chapters"]), genre, duration_ms, len(raw),
    )
    log_event(session_id, "screenplay_generate_end",
              duration_ms=duration_ms, raw_chars=len(raw),
              num_chapters=len(data["chapters"]),
              num_main_characters=len(data["main_characters"]))
    return sp


async def get_active_screenplay(session: AsyncSession, session_id: int) -> Screenplay | None:
    stmt = (
        select(Screenplay)
        .where(
            Screenplay.session_id == session_id,
            Screenplay.status == "active",
        )
        .order_by(Screenplay.version.desc())
    )
    return (await session.execute(stmt)).scalars().first()


async def rewrite_screenplay_after_decision(
    session: AsyncSession,
    session_id: int,
    revision_id: int,
    decision_description: str,
    client: ModelClient,
) -> ScreenplayRevision | None:
    """Call outliner LLM to rewrite the active screenplay's chapters from
    current_chapter onward, fill in the revision row's after_chapters_json
    and diff_summary, and update the screenplay's chapters_json in place.

    Idempotent: returns the revision if rewrite succeeded, else None (and
    the revision keeps its placeholder diff_summary so the caller can see
    it never completed).
    """
    rev = await session.get(ScreenplayRevision, revision_id)
    if rev is None:
        return None
    sp = await session.get(Screenplay, rev.screenplay_id)
    if sp is None or sp.status != "active":
        return None
    sess = await session.get(GameSession, session_id)
    if sess is None:
        return None
    world = await session.get(World, sess.world_id) if sess.world_id else None
    char = await session.get(Character, sess.character_id) if sess.character_id else None

    completed_events = []
    try:
        completed_events = json.loads(sp.completed_events_json or "[]")
    except (ValueError, TypeError):
        pass
    completed_summary_lines = [
        f"- 第 {ev.get('chapter', '?')} 章 {ev.get('type', '')} 事件 #{ev.get('event_idx', '?')}（回合 {ev.get('turn', '?')}）"
        for ev in completed_events[:20]
    ]
    completed_summary = "\n".join(completed_summary_lines)

    messages = build_rewrite_messages(
        world_name=world.name if world else "",
        world_md=world.content_md if world else "",
        character_name=char.name if char else "",
        character_md=char.profile_md if char else "",
        genre=sp.genre or "悬疑探案",
        current_chapters_json=sp.chapters_json or "[]",
        current_chapter=sp.current_chapter,
        completed_events_summary=completed_summary,
        decision_description=decision_description,
        custom_prompt=sp.custom_prompt or "",
    )

    from dzmm.service.activity_log import log_event
    import time as _time

    log_event(session_id, "screenplay_rewrite_start",
              screenplay_id=sp.id, revision_id=rev.id,
              trigger=decision_description[:100])
    start = _time.monotonic()

    raw_chunks: list[str] = []
    try:
        async for chunk in client.stream(messages, GenerationParams(max_tokens=2000, temperature=0.7)):
            if chunk.delta:
                raw_chunks.append(chunk.delta)
    except Exception as e:
        log_event(session_id, "screenplay_rewrite_error",
                  duration_ms=int((_time.monotonic() - start) * 1000),
                  revision_id=rev.id, error=str(e)[:200])
        return None
    raw = "".join(raw_chunks)
    duration_ms = int((_time.monotonic() - start) * 1000)

    try:
        data = _parse_outline_json(raw)
    except ValueError as e:
        log_event(session_id, "screenplay_rewrite_error",
                  duration_ms=duration_ms, raw_chars=len(raw),
                  revision_id=rev.id, error=f"parse: {e}"[:200])
        return None

    new_chapters_json = json.dumps(data["chapters"], ensure_ascii=False)
    diff_summary = str(data.get("diff_summary") or "")[:500]
    if not diff_summary:
        diff_summary = f"基于决定『{decision_description[:80]}』改写第 {sp.current_chapter} 章起后续章节"

    rev.after_chapters_json = new_chapters_json
    rev.diff_summary = diff_summary
    sp.chapters_json = new_chapters_json
    if data.get("ending"):
        sp.ending_md = str(data["ending"])[:2000]
    if data.get("main_characters"):
        sp.main_characters_json = json.dumps(data["main_characters"], ensure_ascii=False)

    log_event(session_id, "screenplay_rewrite_end",
              duration_ms=duration_ms, raw_chars=len(raw),
              revision_id=rev.id, screenplay_id=sp.id,
              num_chapters=len(data["chapters"]))
    log.info(
        "rewrote screenplay %d (revision %d) for session %d (%dms, %d chars, %d chapters)",
        sp.id, rev.id, session_id, duration_ms, len(raw), len(data["chapters"]),
    )
    return rev


async def rewrite_in_background(
    session_maker,
    session_id: int,
    revision_id: int,
    decision_description: str,
) -> None:
    """Fire-and-forget background rewrite. Opens a fresh AsyncSession, builds
    a long-timeout outliner client from the session's GM model config, runs
    the rewrite, commits. Exceptions are swallowed (logged) — the caller is
    decoupled by design.
    """
    from dzmm.db.models import ModelConfig as _MC, Session as _GS  # local import: avoid cycle
    from dzmm.models.factory import build_client as _build

    try:
        async with session_maker() as s:
            sess = await s.get(_GS, session_id)
            if sess is None:
                return
            cfg = await s.get(_MC, sess.gm_model_config_id) if sess.gm_model_config_id else None
            if cfg is None:
                log.warning("rewrite_in_background: no GM model config for session %d", session_id)
                return
            client = _build(cfg)
            if hasattr(client, "timeout"):
                client.timeout = max(getattr(client, "timeout", 0.0), 600.0)
            result = await rewrite_screenplay_after_decision(
                s, session_id, revision_id, decision_description, client,
            )
            if result is not None:
                await s.commit()
    except Exception as e:  # noqa: BLE001
        log.error(
            "rewrite_in_background failed (session=%d, revision=%d): %s",
            session_id, revision_id, e,
        )
