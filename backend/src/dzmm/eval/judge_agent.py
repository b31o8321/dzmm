import json
import logging
import re
from dataclasses import dataclass

from dzmm.models.client import GenerationParams, ModelClient
from dzmm.prompts.judge_template import build_judge_messages

log = logging.getLogger(__name__)

_JUDGE_PARAMS = GenerationParams(temperature=0.2, max_tokens=200)


@dataclass
class EvalScore:
    session_id: int
    turn: int
    config_name: str
    plot_speed: float
    rule_violations: int
    rp_immersion: float
    dice_accuracy: float
    reasoning: str

    @property
    def overall(self) -> float:
        viol_penalty = max(0.0, 10.0 - self.rule_violations * 2.0)
        return (self.plot_speed + viol_penalty + self.rp_immersion + self.dice_accuracy) / 4.0


async def judge_session(
    messages: list,
    world_summary: str,
    session_id: int,
    turn: int,
    config_name: str,
    client: ModelClient,
) -> EvalScore:
    pairs: list[tuple[str, str]] = []
    user_msg: str | None = None
    for msg in messages:
        if msg.role == "user":
            user_msg = msg.content
        elif msg.role == "assistant" and user_msg is not None:
            pairs.append((user_msg, msg.content))
            user_msg = None

    n_turns = len(pairs)
    prompt_msgs = build_judge_messages(
        world_summary=world_summary,
        recent_history=pairs,
        n_turns=n_turns,
    )

    raw = ""
    try:
        raw, _ = await client.complete(prompt_msgs, _JUDGE_PARAMS)
        data = _parse_judge_output(raw)
        return EvalScore(
            session_id=session_id,
            turn=turn,
            config_name=config_name,
            plot_speed=float(data.get("plot_speed", 5.0)),
            rule_violations=int(data.get("rule_violations", 0)),
            rp_immersion=float(data.get("rp_immersion", 5.0)),
            dice_accuracy=float(data.get("dice_accuracy", 7.0)),
            reasoning=str(data.get("reasoning", "")),
        )
    except Exception as exc:
        log.warning("judge_agent parse failed (turn %d): %s | raw: %.100s", turn, exc, raw)
        return EvalScore(
            session_id=session_id,
            turn=turn,
            config_name=config_name,
            plot_speed=5.0,
            rule_violations=0,
            rp_immersion=5.0,
            dice_accuracy=7.0,
            reasoning=f"parse error: {exc}",
        )


def _parse_judge_output(raw: str) -> dict:
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        pass
    m = re.search(r"\{[^{}]*\}", raw, re.DOTALL)
    if m:
        try:
            return json.loads(m.group())
        except (ValueError, TypeError):
            pass
    raise ValueError(f"no parseable JSON in judge output: {raw[:200]}")
