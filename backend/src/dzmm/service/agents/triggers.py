# ============================================================
# triggers.py — Director agent 的「触发条件」判断器
#
# 【Director 为什么不是每回合都跑？】
# Director（导演）调用 LLM 是有成本的：时间成本（延迟）和 token 成本（费用）。
# 如果每回合都运行 Director，游戏会变慢，费用也会很高。
# 因此 Director 采用「按需触发」策略：
#   - 默认每 5 回合运行一次（定期检查剧情走向）
#   - 遇到「关键事件」时立刻运行（紧急更新叙事方向）
#
# 【触发条件有哪些？】
# 1. bootstrap：第一次运行（stream.last_run_turn == 0），Director 必须先给 Scene 方向
# 2. chapter_advance：上一回合发生了章节推进，Director 需要为新章节制定策略
# 3. plot_turn_major：上一回合发生了重大剧情转折，Director 需要调整方向
# 4. hp_critical：玩家生命值 ≤ 5，游戏快结束了，Director 需要处理
# 5. sanity_critical：玩家理智值 ≤ 5，可能触发特殊结局
# 6. hidden_event_due：幕后「定时炸弹」到期，Director 需要引爆它
# 7. interval：距离上次运行已超过 5 回合，定期更新
# ============================================================
"""Director run triggers — when does the Director agent fire each turn?

Default cadence: every 5 turns in the background. Sync triggers fire
when the prior turn's outcome demands fresh long-term reasoning:
- bootstrap (first run)
- chapter_advance (last turn emitted <chapter_advance/>)
- plot_turn major (last turn emitted <plot_turn impact="major">)
- hp / sanity <= 5 (PC in critical state — needs rescue or ending)
- hidden_event maturity reached
"""
from __future__ import annotations

# 定期触发的间隔：每 5 回合 Director 必须运行一次，即便没有特殊事件
DIRECTOR_INTERVAL_TURNS = 5
# 开放世界模式下缩短间隔到 3 回合（地点/事件变化更频繁）
DIRECTOR_INTERVAL_TURNS_FRAMEWORK = 3
# 临界状态的阈值：HP 或理智值低于等于这个数字时立即触发 Director
HP_CRITICAL = 5
SANITY_CRITICAL = 5


def should_run_director(stream, session, current_turn: int) -> tuple[bool, str]:
    # 参数说明：
    #   stream：AgentStream 对象，有 .last_run_turn 字段（Director 上次运行在第几回合）
    #   session：包含触发判断所需字段的对象（由 orchestrator._build_director_trigger_state 构建）
    #   current_turn：当前是第几回合
    # 返回：(是否触发, 触发原因字符串)
    # 触发原因字符串主要用于日志记录，方便调试
    """Return (fire?, reason). `stream` has .last_run_turn; `session` has the
    fields shown in the test stub (built by the orchestrator).
    """
    # ── 触发条件 1：首次运行（bootstrap）────────────────────
    # last_run_turn == 0 说明这个 Director 流还从未运行过。
    # 第一次必须运行，否则 Scene 没有 plot_directive，不知道该讲什么故事。
    if stream.last_run_turn == 0:
        return True, "bootstrap"

    # ── 触发条件 2：上一回合发生了章节推进 ──────────────────
    # chapter_advanced_last_turn 由 orchestrator 从上一回合的 events_json 中读取。
    # 进入新章节意味着剧情进入全新阶段，Director 必须重新制定方向。
    if getattr(session, "chapter_advanced_last_turn", False):
        return True, "chapter_advance"

    # ── 触发条件 3：上一回合发生了重大剧情转折 ──────────────
    # 玩家做了某个影响深远的决定（impact="major"），Director 要据此调整叙事方向。
    if getattr(session, "major_plot_turn_last_turn", False):
        return True, "plot_turn_major"

    # ── Framework 模式（开放世界）触发条件 ──────────────────────
    # 这五个字段由 orchestrator._build_director_trigger_state 填充；
    # 非 framework 模式下全部为 False，不影响剧本章节模式的逻辑。
    if getattr(session, "event_completed_last_turn", False):
        return True, "event_completed"
    if getattr(session, "phase_advanced_last_turn", False):
        return True, "phase_advanced"
    if getattr(session, "event_triggered_last_turn", False):
        return True, "event_triggered"
    if getattr(session, "faction_tension_breached", False):
        return True, "faction_tension"
    if getattr(session, "proactive_npc_pending", False):
        return True, "proactive_npc"

    # ── 触发条件 4：玩家 HP 临界 ─────────────────────────────
    # HP ≤ 5 说明玩家快死了。Director 需要立刻决定是要给「死亡结局」
    # 还是安排 NPC 救援、剧情转机等。
    if int(getattr(session, "hp", 99)) <= HP_CRITICAL:
        return True, "hp_critical"

    # ── 触发条件 5：玩家理智值临界 ───────────────────────────
    # 理智值（sanity）代表玩家角色的精神状态，
    # 低于阈值可能触发「发疯」「幻觉」等特殊剧情，Director 要干预。
    if int(getattr(session, "sanity", 99)) <= SANITY_CRITICAL:
        return True, "sanity_critical"

    # ── 触发条件 6：隐藏事件到期 ─────────────────────────────
    # hidden_event_due 由 orchestrator 根据「事件存在回合数 vs 严重程度阈值」计算。
    # 到期的隐藏事件必须在这回合「爆发」，Director 需要在 directive 里安排这件事。
    if getattr(session, "hidden_event_due", False):
        return True, "hidden_event_due"

    # ── 触发条件 7：定期触发（interval）──────────────────────
    # 即便没有特殊事件，Director 也要定期出手一次，
    # 确保故事不会偏离整体方向太远，并为下阶段剧情预埋伏笔。
    # 开放世界模式使用更短的间隔（3 回合），因为地点/事件变化更频繁。
    interval = (
        DIRECTOR_INTERVAL_TURNS_FRAMEWORK
        if getattr(session, "is_framework_mode", False)
        else DIRECTOR_INTERVAL_TURNS
    )
    if (current_turn - stream.last_run_turn) >= interval:
        return True, "interval"

    # 以上条件都不满足，本回合跳过 Director，复用上次的 directive
    return False, "skip"
