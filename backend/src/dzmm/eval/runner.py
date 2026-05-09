"""Phase C evaluation runner — orchestrates player agent, GM, and judge."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from sqlalchemy import select

from dzmm.db.models import (
    Character,
    Feedback,
    Message,
    Session,
    World,
)
from dzmm.eval.judge_agent import EvalScore, judge_session
from dzmm.eval.player_agent import generate_player_action
from dzmm.models.client import ModelClient
from dzmm.service.game import run_turn

log = logging.getLogger(__name__)

_RECENT_N = 10  # number of recent messages to feed each agent


@dataclass
class EvalConfig:
    session_id: int
    config_name: str
    max_turns: int = 20
    judge_every: int = 10
    ollama_base_url: str | None = None


async def _load_recent_messages(db, session_id: int, n: int = _RECENT_N) -> list:
    stmt = (
        select(Message)
        .where(Message.session_id == session_id)
        .order_by(Message.id.desc())
        .limit(n)
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return list(reversed(rows))


async def run_eval(
    config: EvalConfig,
    session_maker,
    gm_client: ModelClient,
    player_client: ModelClient,
    judge_client: ModelClient,
) -> list[EvalScore]:
    """Run a full eval loop for *config.max_turns* turns.

    Returns a list of :class:`EvalScore` objects — one per *judge_every* turns.
    """
    scores: list[EvalScore] = []

    async with session_maker() as db:
        # ── load game session metadata ───────────────────────────────────────
        game_session = await db.get(Session, config.session_id)
        character = await db.get(Character, game_session.character_id)
        world = await db.get(World, game_session.world_id)

        world_summary: str = getattr(world, "content_md", "") or ""
        character_md: str = getattr(character, "profile_md", "") or ""
        character_name: str = getattr(character, "name", "玩家") or "玩家"

        for turn in range(1, config.max_turns + 1):
            log.debug("eval turn %d / %d", turn, config.max_turns)

            # ── player action ────────────────────────────────────────────────
            messages = await _load_recent_messages(db, config.session_id)
            action = await generate_player_action(
                messages=messages,
                character_md=character_md,
                character_name=character_name,
                client=player_client,
            )

            # ── GM turn ──────────────────────────────────────────────────────
            async for _ in run_turn(
                db,
                config.session_id,
                action,
                gm_client,
                ollama_base_url=config.ollama_base_url,
            ):
                pass

            await db.commit()

            # ── judge every N turns ──────────────────────────────────────────
            if turn % config.judge_every == 0:
                recent = await _load_recent_messages(db, config.session_id)
                score = await judge_session(
                    messages=recent,
                    world_summary=world_summary,
                    session_id=config.session_id,
                    turn=turn,
                    config_name=config.config_name,
                    client=judge_client,
                )
                scores.append(score)

                # persist to DB
                fb = Feedback(
                    session_id=config.session_id,
                    turn=turn,
                    kind="eval_score",
                    content=json.dumps({
                        "plot_speed": score.plot_speed,
                        "rule_violations": score.rule_violations,
                        "rp_immersion": score.rp_immersion,
                        "dice_accuracy": score.dice_accuracy,
                        "overall": score.overall,
                        "reasoning": score.reasoning,
                        "config_name": score.config_name,
                    }),
                )
                db.add(fb)
                await db.commit()

    return scores
