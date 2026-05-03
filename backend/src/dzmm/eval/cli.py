import argparse
import asyncio
import sys
from datetime import datetime, UTC
from pathlib import Path

from dzmm.config import APP_DIR, DEFAULT_DB_URL
from dzmm.db.base import get_engine, async_session
from dzmm.db.models import ModelConfig, Session as GameSession
from dzmm.models.factory import build_client
from dzmm.eval.report import generate_report
from dzmm.eval.runner import EvalConfig, run_eval


def _build_client_from_config(cfg: ModelConfig | None):
    """Build a ModelClient from a ModelConfig ORM object. Handle None gracefully."""
    if cfg is None:
        raise RuntimeError(
            "No model config found for session. Please configure a model first."
        )
    return build_client(cfg)


async def _main(args: argparse.Namespace) -> None:
    engine = get_engine(DEFAULT_DB_URL)
    session_maker = async_session(engine)

    async with session_maker() as s:
        sess_a = await s.get(GameSession, args.session_id)
        if sess_a is None:
            print(f"Error: session {args.session_id} not found", file=sys.stderr)
            await engine.dispose()
            return
        gm_cfg = (
            await s.get(ModelConfig, sess_a.gm_model_config_id)
            if sess_a.gm_model_config_id
            else None
        )

    gm_client = _build_client_from_config(gm_cfg)
    player_client = gm_client
    judge_client = gm_client

    config_a = EvalConfig(
        session_id=args.session_id,
        config_name="single_gm",
        max_turns=args.turns,
        judge_every=args.judge_every,
        use_graph=False,
    )

    print(f"Running eval on session {args.session_id} for {args.turns} turns...")
    scores_a = await run_eval(config_a, session_maker, gm_client, player_client, judge_client)
    print(f"Session A done. {len(scores_a)} evaluation checkpoints.")

    scores_b = []
    config_b_name = "multi_agent_gm"

    if args.compare and args.session_id_b:
        async with session_maker() as s:
            sess_b = await s.get(GameSession, args.session_id_b)
            if sess_b is None:
                print(
                    f"Error: session {args.session_id_b} not found", file=sys.stderr
                )
                await engine.dispose()
                return

        config_b = EvalConfig(
            session_id=args.session_id_b,
            config_name=config_b_name,
            max_turns=args.turns,
            judge_every=args.judge_every,
            use_graph=True,
        )
        print(f"Running eval on session {args.session_id_b} (multi-agent GM)...")
        scores_b = await run_eval(
            config_b, session_maker, gm_client, player_client, judge_client
        )
        print(f"Session B done. {len(scores_b)} evaluation checkpoints.")

    report = generate_report(scores_a, "single_gm", scores_b, config_b_name)
    print(report)

    out_dir = APP_DIR / "eval"
    out_dir.mkdir(exist_ok=True)
    ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    report_path = out_dir / f"report_{ts}.md"
    report_path.write_text(report, encoding="utf-8")
    print(f"\nReport saved to: {report_path}")

    await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="TRPG GM Autonomous Evaluation")
    parser.add_argument("--session-id", type=int, required=True)
    parser.add_argument("--session-id-b", type=int, default=None)
    parser.add_argument("--turns", type=int, default=20)
    parser.add_argument("--judge-every", type=int, default=10)
    parser.add_argument("--compare", action="store_true")
    args = parser.parse_args()
    asyncio.run(_main(args))


if __name__ == "__main__":
    main()
