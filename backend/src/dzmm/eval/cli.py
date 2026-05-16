# ============================================================
# 自动化评测命令行入口（cli.py）
# ============================================================
# 【这个文件是什么？】
#   cli.py 是评测系统的命令行接口（CLI = Command-Line Interface）。
#   用户通过命令行运行这个脚本来启动评测，类似于：
#     python -m dzmm.eval.cli --session-id 5 --turns 20
#
# 【argparse 是什么？】
#   argparse 是 Python 标准库里的命令行参数解析模块。
#   它自动把命令行的 --session-id 5 解析成 args.session_id = 5。
#   还自动生成 --help 帮助信息，不需要手动写。
#   【Java 对比】类似于 Apache Commons CLI 或 Spring Boot 的 @CommandLine。
#
# 【asyncio.run() 是什么？】
#   Python 的异步函数（async def）不能直接调用，必须放入异步事件循环里运行。
#   asyncio.run(_main(args)) 会启动一个新的事件循环，运行 _main，完成后销毁循环。
#   这是命令行脚本里调用 async 函数的标准做法。
#
# 【评测输出是什么？】
#   1. 终端打印进度信息（"Running eval..."）
#   2. Markdown 报告保存到 ~/.local/share/dzmm/eval/report_<timestamp>.md
#   报告包含各回合评分表和 A/B 对比分析。
# ============================================================
import argparse
import asyncio
import sys
from datetime import datetime, UTC
from pathlib import Path

from dzmm.config import APP_DIR, DEFAULT_DB_URL
from dzmm.db.base import get_engine, async_session
from dzmm.db.models import ModelConfig, Session as GameSession  # 别名避免与 Python 内置 Session 冲突
from dzmm.models.factory import build_client
from dzmm.eval.export import export_jsonl
from dzmm.eval.report import generate_report
from dzmm.eval.runner import EvalConfig, run_eval


def _build_client_from_config(cfg: ModelConfig | None):
    """Build a ModelClient from a ModelConfig ORM object. Handle None gracefully.

    【为什么要单独封装这个函数？】
      同一段"从数据库 cfg 构建 LLM 客户端"的逻辑需要复用多次（GM/玩家/裁判）。
      封装成函数后，修改逻辑只需改一个地方。
    """
    if cfg is None:
        # 数据库里没有配置模型的话，直接抛出友好的错误提示
        # 而不是让 Python 自己抛 AttributeError（错误信息不友好）
        raise RuntimeError(
            "No model config found for session. Please configure a model first."
        )
    return build_client(cfg)  # build_client() 根据 cfg.type（"ollama"/"openai"）构建合适的客户端


# ── 主异步逻辑 ──────────────────────────────────────────────
async def _main(args: argparse.Namespace) -> None:
    # 初始化数据库连接
    engine = get_engine(DEFAULT_DB_URL)        # 创建 SQLAlchemy 异步引擎
    session_maker = async_session(engine)      # 工厂函数，调用后得到一个数据库 session

    # ── 读取 session A 的配置 ─────────────────────────────────────────────
    async with session_maker() as s:
        sess_a = await s.get(GameSession, args.session_id)  # 按主键查询游戏 session
        if sess_a is None:
            print(f"Error: session {args.session_id} not found", file=sys.stderr)
            await engine.dispose()  # 释放数据库连接池资源
            return
        # 从 session 关联的 gm_model_config_id 读取模型配置
        # 如果 gm_model_config_id 为 None（没配置模型），gm_cfg 也是 None
        gm_cfg = (
            await s.get(ModelConfig, sess_a.gm_model_config_id)
            if sess_a.gm_model_config_id
            else None
        )

    # 构建 LLM 客户端
    # 【简化设计】目前三个角色（GM/玩家 Agent/裁判 Agent）共用同一个模型
    # 这样只需要配置一个 API Key，降低了使用门槛
    # 未来可以分开配置，让裁判用不同（更强）的模型
    gm_client = _build_client_from_config(gm_cfg)
    player_client = gm_client   # 玩家 Agent 暂时用同一个模型
    judge_client = gm_client    # 裁判 Agent 暂时用同一个模型

    # ── 配置 A 的评测参数 ─────────────────────────────────────────────────
    config_a = EvalConfig(
        session_id=args.session_id,
        config_name="single_gm",         # 配置名称，用于报告区分
        max_turns=args.turns,             # 跑多少回合（从命令行参数读取）
        judge_every=args.judge_every,     # 每隔多少回合评判一次
    )

    # 启动评测循环 A
    print(f"Running eval on session {args.session_id} for {args.turns} turns...")
    scores_a = await run_eval(config_a, session_maker, gm_client, player_client, judge_client)
    print(f"Session A done. {len(scores_a)} evaluation checkpoints.")

    # ── 可选的 B 组评测（A/B 对比）────────────────────────────────────────
    scores_b = []
    config_b_name = "multi_agent_gm"  # B 组的名称（多 Agent GM 架构）

    # 只有用户传了 --compare 和 --session-id-b 才运行 B 组
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
        )
        print(f"Running eval on session {args.session_id_b} (multi-agent GM)...")
        scores_b = await run_eval(
            config_b, session_maker, gm_client, player_client, judge_client
        )
        print(f"Session B done. {len(scores_b)} evaluation checkpoints.")

    # ── 可选：导出 JSONL 训练数据（Phase D QLoRA）────────────────────────
    if args.export_jsonl:
        export_base = Path(args.export_jsonl)
        if args.compare and scores_b:
            # A/B 对比模式：写两个文件
            path_a = export_base.parent / (export_base.name + ".a.jsonl")
            path_b = export_base.parent / (export_base.name + ".b.jsonl")
            n_a = await export_jsonl(
                args.session_id, scores_a, path_a, session_maker,
                min_overall=args.min_score,
            )
            print(f"Exported {n_a} records to {path_a}")
            n_b = await export_jsonl(
                args.session_id_b, scores_b, path_b, session_maker,
                min_overall=args.min_score,
            )
            print(f"Exported {n_b} records to {path_b}")
        else:
            # 单组模式：直接写到指定路径
            n = await export_jsonl(
                args.session_id, scores_a, export_base, session_maker,
                min_overall=args.min_score,
            )
            print(f"Exported {n} records to {export_base}")

    # ── 生成 Markdown 报告 ──────────────────────────────────────────────
    # generate_report() 接收 A/B 两组评分，生成带对比分析的 Markdown 文本
    report = generate_report(scores_a, "single_gm", scores_b, config_b_name)
    print(report)  # 先在终端显示一遍

    # 同时保存到文件（方便后续查阅或分享）
    out_dir = APP_DIR / "eval"         # APP_DIR 是用户数据目录，如 ~/.local/share/dzmm
    out_dir.mkdir(exist_ok=True)       # 如果目录不存在则创建（exist_ok=True 不报错）
    ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")   # 时间戳，格式如 "20260511_143022"
    report_path = out_dir / f"report_{ts}.md"          # 拼接完整路径
    report_path.write_text(report, encoding="utf-8")   # 写入文件（UTF-8 支持中文）
    print(f"\nReport saved to: {report_path}")

    # 释放数据库连接池（让进程正常退出，不挂起等待连接关闭）
    await engine.dispose()


# ── 命令行参数定义 ──────────────────────────────────────────
def main() -> None:
    # argparse.ArgumentParser：定义程序接受哪些命令行参数
    # description 是 --help 时显示的程序说明
    parser = argparse.ArgumentParser(description="TRPG GM Autonomous Evaluation")

    # --session-id：要评测的游戏 session 的数据库 ID（必填）
    # type=int：自动将字符串转为整数
    # required=True：不传则报错提示
    parser.add_argument("--session-id", type=int, required=True)

    # --session-id-b：B 组对比的 session ID（可选，只在 --compare 模式下用）
    parser.add_argument("--session-id-b", type=int, default=None)

    # --turns：总回合数（默认 20）
    parser.add_argument("--turns", type=int, default=20)

    # --judge-every：每隔多少回合评判一次（默认 10）
    parser.add_argument("--judge-every", type=int, default=10)

    # --compare：布尔标志（有则为 True，无则为 False）
    # action="store_true" 表示这是一个开关参数，不需要传值，传了就是 True
    parser.add_argument("--compare", action="store_true")

    # --export-jsonl：导出 JSONL 训练数据到指定路径（Phase D QLoRA 用）
    # 不传则不导出；传了路径则在评测完成后写文件
    # --compare 模式下会自动在路径名后加 .a.jsonl / .b.jsonl 后缀
    parser.add_argument(
        "--export-jsonl",
        dest="export_jsonl",
        default=None,
        metavar="PATH",
        help="Export per-turn training records to JSONL at PATH (Phase D QLoRA data).",
    )

    # --min-score：导出时的综合分下限（低于此分数的回合不写入 JSONL）
    parser.add_argument(
        "--min-score",
        dest="min_score",
        type=float,
        default=7.0,
        metavar="FLOAT",
        help="Minimum overall score to include in JSONL export (default: 7.0).",
    )

    args = parser.parse_args()  # 解析实际的命令行参数

    # asyncio.run()：启动事件循环，运行异步函数 _main，阻塞直到完成
    asyncio.run(_main(args))


# Python 惯例：只有直接运行这个文件时（不是 import）才调用 main()
if __name__ == "__main__":
    main()
