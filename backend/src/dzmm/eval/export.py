"""Phase D training-data exporter.

Converts per-turn EvalScore objects into JSONL records suitable for QLoRA
fine-tuning.  Only turns that have a recorded prompt_json (debug_mode was on
during the eval run) *and* an overall score ≥ min_overall are exported.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from sqlalchemy import select

from dzmm.db.models import Message
from dzmm.eval.judge_agent import EvalScore

log = logging.getLogger(__name__)


async def export_jsonl(
    session_id: int,
    scores: list[EvalScore],
    output_path: Path,
    session_maker,
    min_overall: float = 7.0,
) -> int:
    """Export per-turn training records to JSONL.  Returns count written.

    Records are written to *output_path* (UTF-8, one JSON object per line).
    Only turns where ``score.overall >= min_overall`` *and* the matching
    Message row has a non-empty ``prompt_json`` are included.

    A summary warning is printed at the end when any turns were skipped due to
    missing prompt_json (i.e. debug_mode was off during the eval run).
    """
    # ── 1. Load all assistant messages for this session, keyed by turn ──────
    async with session_maker() as db:
        stmt = (
            select(Message)
            .where(
                Message.session_id == session_id,
                Message.role == "assistant",
            )
            .order_by(Message.turn)
        )
        result = await db.execute(stmt)
        rows = result.scalars().all()

    # Build a turn → Message mapping (keep the last assistant row per turn in
    # case there are duplicates, which shouldn't normally happen).
    msg_by_turn: dict[int, Message] = {}
    for row in rows:
        msg_by_turn[row.turn] = row

    # ── 2. Filter scores and write records ───────────────────────────────────
    missing_prompt_json_count = 0
    written = 0

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as fh:
        for score in scores:
            if score.overall < min_overall:
                continue

            msg = msg_by_turn.get(score.turn)
            if msg is None:
                log.warning(
                    "export_jsonl: no assistant message found for session=%d turn=%d — skipping",
                    session_id,
                    score.turn,
                )
                missing_prompt_json_count += 1
                continue

            if not msg.prompt_json:
                log.warning(
                    "export_jsonl: prompt_json empty for session=%d turn=%d — skipping",
                    session_id,
                    score.turn,
                )
                missing_prompt_json_count += 1
                continue

            # Parse prompt_json — expected shape: list[{role, content}]
            try:
                messages = json.loads(msg.prompt_json)
            except (ValueError, TypeError) as exc:
                log.warning(
                    "export_jsonl: could not parse prompt_json for session=%d turn=%d: %s — skipping",
                    session_id,
                    score.turn,
                    exc,
                )
                missing_prompt_json_count += 1
                continue

            record = {
                "session_id": session_id,
                "turn": score.turn,
                "config_name": score.config_name,
                "messages": messages,
                "completion": msg.content,
                "score": {
                    "plot_speed": score.plot_speed,
                    "rule_violations": score.rule_violations,
                    "rp_immersion": score.rp_immersion,
                    "dice_accuracy": score.dice_accuracy,
                    "overall": score.overall,
                    "reasoning": score.reasoning,
                },
            }
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
            written += 1

    # ── 3. Summary warning ───────────────────────────────────────────────────
    if missing_prompt_json_count:
        print(
            f"WARNING: {missing_prompt_json_count} turns had no prompt_json captured "
            "(debug_mode was off during run)"
        )

    return written
