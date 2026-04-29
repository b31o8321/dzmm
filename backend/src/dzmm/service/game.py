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

    msgs = build_gm_messages(
        world_md=world.content_md,
        character_md=char.profile_md,
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


async def _build_key_facts(
    session: AsyncSession, session_id: int, current_turn: int
) -> str:
    npcs = (
        await session.execute(
            select(NPC).where(NPC.session_id == session_id)
            .order_by(NPC.last_seen_turn.desc())
            .limit(8)
        )
    ).scalars().all()
    threads = (
        await session.execute(
            select(PlotThread)
            .where(PlotThread.session_id == session_id, PlotThread.status == "active")
            .order_by(PlotThread.importance.desc(), PlotThread.id.desc())
            .limit(8)
        )
    ).scalars().all()

    parts: list[str] = []
    if npcs:
        parts.append("NPC 列表：")
        for n in npcs:
            parts.append(f"- {n.name}（好感{n.favor:+d}，状态：{n.state}）{n.description[:40]}")
    if threads:
        parts.append("\n进行中的剧情线：")
        for t in threads:
            stars = "★" * t.importance
            parts.append(f"- [{t.type} {stars}] {t.description}")
    return "\n".join(parts)
