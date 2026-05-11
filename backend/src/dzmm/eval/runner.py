# ============================================================
# 自动化评测运行器（runner.py）
# ============================================================
# 【自动化评测是什么？】
#   TRPG GM 的质量很难靠人工测试：每次需要坐下来手动玩几十回合才能得到足够数据。
#   自动化评测（Automated Evaluation / Eval）用两个 AI Agent 来替代人工：
#   1. Player Agent（玩家 Agent）：模拟真实玩家的行为，自动输入行动
#   2. Judge Agent（裁判 Agent）：每 N 回合评估一次 GM 的表现，给出分数
#   这样就能在无人值守的情况下自动跑几十、几百回合，获得客观的质量评分。
#
# 【这个文件做什么？】
#   runner.py 是评测的核心调度器（Orchestrator）：
#   - 接收 EvalConfig 配置（跑多少回合、多久评判一次等）
#   - 循环执行：玩家行动 → GM 回应 → 每 N 回合触发裁判评分
#   - 把每次评分结果存入数据库（Feedback 表）
#   - 最终返回所有评分列表，供报告生成器生成 Markdown 报告
#
# 【为什么要比较两个 session？】
#   这是 A/B 测试设计：
#   - Session A：单 GM 架构（一个 LLM 直接当 GM）
#   - Session B：多 Agent 架构（Director + Scene + NPC Actor）
#   同一个裁判评两组，得到可比较的分数，验证哪种架构更好。
#   但 runner.py 本身只管跑一个 session，A/B 对比逻辑在 cli.py 里。
# ============================================================
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

# 每次给 Player Agent 和 Judge Agent 看的最近消息条数
# 不用全量历史是为了节省 token：10 条消息约等于最近 5 回合（一回合=玩家+GM各一条）
_RECENT_N = 10  # number of recent messages to feed each agent


# ── 评测配置（EvalConfig）────────────────────────────────────
# 【为什么用 @dataclass 而不是普通 class？】
#   @dataclass 装饰器会自动生成 __init__、__repr__、__eq__ 等方法。
#   不需要手动写 def __init__(self, session_id, config_name, ...)，
#   只需要声明字段和类型，Python 自动搞定。
#   相当于 Java 的 Lombok @Data 注解或 Java 14+ 的 record 语法。
#
# 【各字段说明】
#   session_id：要评测的游戏会话 ID（对应数据库里的一局游戏）
#   config_name：这次评测的名称（如 "single_gm" 或 "multi_agent_gm"），用于报告区分
#   max_turns：总共跑多少回合（默认 20 回合）
#   judge_every：每隔多少回合触发一次裁判评分（默认每 10 回合评一次）
#   ollama_base_url：如果 GM 用本地 Ollama 模型，需要提供这个 URL；否则填 None
@dataclass
class EvalConfig:
    session_id: int
    config_name: str
    max_turns: int = 20
    judge_every: int = 10
    ollama_base_url: str | None = None


# ── 辅助函数：加载最近 N 条消息 ────────────────────────────────
async def _load_recent_messages(db, session_id: int, n: int = _RECENT_N) -> list:
    # SQLAlchemy 查询：按 id 倒序取最新的 n 条，然后反转顺序（得到时间顺序）
    # .desc()：降序排列（最新的先出来）
    # .limit(n)：只取前 n 条（等同于 SQL 的 LIMIT n）
    stmt = (
        select(Message)
        .where(Message.session_id == session_id)
        .order_by(Message.id.desc())
        .limit(n)
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()  # scalars() 把 Row 转成实际的 ORM 对象列表
    return list(reversed(rows))   # reversed 恢复时间顺序（早的在前，新的在后）


# ── 主评测循环 ──────────────────────────────────────────────
async def run_eval(
    config: EvalConfig,
    session_maker,         # AsyncSessionMaker：用于创建数据库连接
    gm_client: ModelClient,      # GM 使用的 LLM 客户端
    player_client: ModelClient,  # 玩家 Agent 使用的 LLM 客户端
    judge_client: ModelClient,   # 裁判 Agent 使用的 LLM 客户端
) -> list[EvalScore]:
    """Run a full eval loop for *config.max_turns* turns.

    Returns a list of :class:`EvalScore` objects — one per *judge_every* turns.
    """
    # scores：收集所有评分点的结果，最终返回给 cli.py 生成报告
    scores: list[EvalScore] = []

    # async with session_maker() as db：打开一个数据库连接（事务会话）
    # 整个评测循环共享同一个数据库连接，避免频繁建连接的开销
    async with session_maker() as db:
        # ── 加载游戏 session 的基本信息 ──────────────────────────────────────
        # db.get()：按主键查询，等同于 SELECT * FROM ... WHERE id = session_id
        game_session = await db.get(Session, config.session_id)
        character = await db.get(Character, game_session.character_id)
        world = await db.get(World, game_session.world_id)

        # 提取文本内容，用 getattr 而不是直接访问属性，避免 None 时报错
        # or "" 是后备值：如果字段为 None 则用空字符串
        world_summary: str = getattr(world, "content_md", "") or ""
        character_md: str = getattr(character, "profile_md", "") or ""
        character_name: str = getattr(character, "name", "玩家") or "玩家"

        # ── 主循环：每次迭代 = 一个回合（玩家行动 + GM 回应 + 可选裁判评分）──
        for turn in range(1, config.max_turns + 1):
            log.debug("eval turn %d / %d", turn, config.max_turns)

            # ── 第一步：Player Agent 生成玩家行动 ────────────────────────────
            # 先从数据库读最近的消息历史，作为上下文提供给 Player Agent
            messages = await _load_recent_messages(db, config.session_id)
            # generate_player_action()：给玩家 Agent 看历史消息，让它生成下一个行动
            # 返回一段文字，如"我走向门口，想听听门外的声音"
            action = await generate_player_action(
                messages=messages,
                character_md=character_md,
                character_name=character_name,
                client=player_client,
            )

            # ── 第二步：GM 处理玩家行动，生成叙事回应 ──────────────────────
            # run_turn() 是实际的 GM 推进函数（来自 service/game.py）
            # 它会调用 GM LLM，解析输出，存储消息，更新角色状态等
            # run_turn() 是 async generator（返回流式 chunk），这里用 async for 消费
            # 但我们不需要实时处理 chunk，只是等它跑完，所以用 _ 忽略每个 chunk
            async for _ in run_turn(
                db,
                config.session_id,
                action,
                gm_client,
                ollama_base_url=config.ollama_base_url,
            ):
                pass  # 消费完所有 chunk（推进到结束），但不处理中间内容

            # 每回合后提交数据库事务（持久化 GM 生成的消息）
            await db.commit()

            # ── 第三步：每 judge_every 回合评判一次 ──────────────────────────
            # turn % config.judge_every == 0 表示"整除"，即每 N 回合触发一次
            # 例如 judge_every=10，则在第 10、20、30... 回合触发评判
            if turn % config.judge_every == 0:
                # 重新读取最近消息（加上这一回合刚产生的内容）给裁判看
                recent = await _load_recent_messages(db, config.session_id)
                # judge_session()：裁判 Agent 分析对话历史，给出各维度评分
                # 返回 EvalScore 对象，包含 plot_speed/rule_violations/rp_immersion 等指标
                score = await judge_session(
                    messages=recent,
                    world_summary=world_summary,
                    session_id=config.session_id,
                    turn=turn,
                    config_name=config.config_name,
                    client=judge_client,
                )
                scores.append(score)

                # 将评分持久化到数据库（Feedback 表）
                # 这样即使进程崩溃，已完成的评分也不会丢失
                # kind="eval_score" 是标识符，区分于用户提交的普通 Feedback
                fb = Feedback(
                    session_id=config.session_id,
                    turn=turn,
                    kind="eval_score",
                    # json.dumps() 把 Python 字典转成 JSON 字符串，存入数据库 TEXT 列
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
                db.add(fb)         # 把 ORM 对象加入会话（标记为"待插入"）
                await db.commit()  # 实际写入数据库（INSERT）

    # 返回所有评分点结果，供调用方（cli.py）生成比较报告
    return scores
