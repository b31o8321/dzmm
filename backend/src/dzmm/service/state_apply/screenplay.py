# ============================================================
# 剧本驱动系统的标签处理模块
#
# dzmm v0.1.0 引入了"剧本驱动"（Screenplay-Driven）设计：
# 游戏开始时，AI 会为本局游戏生成一个结构化剧本大纲（Screenplay），
# 包含若干章节（chapters），每个章节有若干主线事件（main events）
# 和支线事件（optional events）。
#
# GM 在叙事中通过以下四个标签来推进或结束剧本：
#
#   <chapter_advance/>          → PC 完成了某章节，进入下一章
#   <event_complete chapter=N event=M type=main|optional/>  → 某个剧情事件完成
#   <plot_turn impact=major description="..."/>  → 重大剧情转折，可能重写大纲
#   <ending/>                   → 故事走向结局，剧本状态变为 "concluded"
#
# 【为什么要有剧本系统？】
# 没有剧本的 AI GM 容易"走偏"——每回合的叙事彼此割裂，缺乏整体结构感。
# 剧本大纲作为"锚点"，让 GM 的每回合叙事都在朝着明确的章节目标推进，
# 同时又允许玩家的重大决策触发大纲重写（plot_turn major），
# 保持"剧情有方向感"和"玩家选择真的有影响力"之间的平衡。
# ============================================================

"""v0.1.0 screenplay-driven tag handlers.

Four lightweight handlers that mutate the session's *active* Screenplay row
in response to <chapter_advance/>, <event_complete/>, <plot_turn/>,
<ending/>. All four share the same "lookup active screenplay then mutate"
shape; if no active screenplay exists they no-op silently (legacy sessions
created before v0.1.0 simply never see these tags applied).

attrs is a string→string dict from XML attribute parsing — chapter / event
indices need explicit int conversion with try/except since the GM may emit
them as decorative text.
"""

import json
from datetime import datetime, UTC  # UTC 时间，用于记录结局时间戳

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.db.models import Character, Screenplay, ScreenplayRevision
from dzmm.db.models import Session as GameSession

# 事件完成后自动奖励 XP（经验值）的数量
# 主线事件更重要，奖励更多；支线事件可选，奖励较少
_XP_MAIN = 50      # 主线事件奖励 50 XP
_XP_OPTIONAL = 20  # 支线事件奖励 20 XP


async def _get_active_screenplay(
    session: AsyncSession, session_id: int
) -> Screenplay | None:
    # -------------------------------------------------------
    # 获取当前活跃剧本
    #
    # 一个游戏局可能有多个剧本版本（因为 plot_turn major 会触发重写），
    # 取 version 最大的那个（最新版本）且状态为 "active" 的剧本。
    # 如果没有活跃剧本（老存档或游戏还未初始化剧本），返回 None。
    # -------------------------------------------------------
    """Return the highest-version active Screenplay for the session, or None."""
    return (
        await session.execute(
            select(Screenplay)
            .where(
                Screenplay.session_id == session_id,
                Screenplay.status == "active",
            )
            .order_by(Screenplay.version.desc())  # 按版本降序，取第一个（最新）
        )
    ).scalars().first()


async def _apply_chapter_advance(
    session: AsyncSession,
    session_id: int,
    attrs: dict[str, str],
    current_turn: int,
) -> None:
    # -------------------------------------------------------
    # 处理 <chapter_advance/> 标签
    #
    # 把当前章节号加 1，但不超过剧本总章节数（防止越界）。
    # 为什么是加 1 而不是从 attrs 读目标章节号？
    # - 简化 GM 的工作：GM 只需说"进入下一章"，不需要记住当前是第几章
    # - 防止 GM 算错章节号（LLM 计数容易出错）
    # -------------------------------------------------------
    """<chapter_advance/> → bump current_chapter by 1, clamped to total chapters
    (last chapter is a no-op so we don't go past the planned outline)."""
    sp = await _get_active_screenplay(session, session_id)
    if sp is None:
        return  # 没有活跃剧本，静默跳过（老存档兼容）

    try:
        chapters = json.loads(sp.chapters_json or "[]")  # 章节大纲列表
    except (TypeError, ValueError):
        chapters = []
    if not isinstance(chapters, list):
        chapters = []

    # 只在还有下一章时才推进（避免越过最后一章）
    if sp.current_chapter < len(chapters):
        sp.current_chapter += 1


async def _apply_event_complete(
    session: AsyncSession,
    session_id: int,
    attrs: dict[str, str],
    current_turn: int,
) -> None:
    # -------------------------------------------------------
    # 处理 <event_complete chapter=N event=M type=main|optional/> 标签
    #
    # 记录哪个章节的哪个事件已完成，格式：
    #   {"chapter": N, "event_idx": M, "type": "main", "turn": T}
    # 写入 completed_events_json 列表。
    #
    # 【幂等性保证】
    # 如果 GM 重复 emit 同一个事件完成标签（LLM 偶尔会这样），
    # 系统只记录第一次，后续重复忽略。
    # 判断依据：(chapter, event_idx, type) 三元组相同即视为重复。
    #
    # 【自动奖励 XP】
    # 事件完成时，系统自动给 PC 奖励 XP，不需要 GM 额外 emit <character_xp>。
    # 这样 GM 的规则更简单，XP 也不会因为 GM 忘记而漏掉。
    #
    # 【末日时钟减压】
    # 主线事件完成时，末日时钟（doom_score）降低 10 点，
    # 表示 PC 在推进故事目标，减轻了末日压力。
    # -------------------------------------------------------
    """<event_complete chapter=N event=M type=main|optional/> →
    append {"chapter": N, "event_idx": M, "type": "main|optional"} to
    completed_events_json. Idempotent: re-emitting same triple is a no-op."""
    sp = await _get_active_screenplay(session, session_id)
    if sp is None:
        return

    try:
        chapter = int(attrs.get("chapter", ""))    # 章节号（从 1 开始）
        event_idx = int(attrs.get("event", ""))    # 事件编号（章节内从 1 开始）
    except (TypeError, ValueError):
        return  # attrs missing or non-numeric — silently skip

    type_ = (attrs.get("type") or "main").strip().lower()
    if type_ not in ("main", "optional"):
        type_ = "main"  # 未知类型默认视为主线事件

    try:
        completed = json.loads(sp.completed_events_json or "[]")
    except (TypeError, ValueError):
        completed = []
    if not isinstance(completed, list):
        completed = []

    # Idempotency key matches on (chapter, event_idx, type) only — turn is
    # metadata for v0.2.2 P1.2 progress-stuck detection (key_facts uses the
    # max turn among completed events of the current chapter to estimate
    # turns_since_progress). Re-emit of the same triple is still a no-op
    # so we don't bump the recorded turn artificially.
    # 检查是否已存在相同的 (chapter, event_idx, type) 记录
    already = any(
        isinstance(c, dict)
        and c.get("chapter") == chapter
        and c.get("event_idx") == event_idx
        and (c.get("type") or "main") == type_
        for c in completed
    )
    if not already:
        # 记录事件完成，带上回合号（供进度停滞检测使用）
        rec = {
            "chapter": chapter,
            "event_idx": event_idx,
            "type": type_,
            "turn": current_turn,  # 记录哪个回合完成的（用于检测进度停滞）
        }
        completed.append(rec)
        sp.completed_events_json = json.dumps(completed, ensure_ascii=False)

        # 自动奖励 XP：不需要 GM 额外 emit <character_xp>，系统自动处理
        # Auto-award XP on event completion so the LLM doesn't need to track it.
        xp_delta = _XP_MAIN if type_ == "main" else _XP_OPTIONAL
        sess = await session.get(GameSession, session_id)
        if sess is not None:
            char = await session.get(Character, sess.character_id)
            if char is not None:
                char.xp = max(0, char.xp + xp_delta)  # 经验值不能为负

        # 主线事件完成 → 末日时钟减少 10（PC 在积极推进故事）
        # Completing a main event reduces doom pressure.
        if type_ == "main":
            sess = await session.get(GameSession, session_id)
            if sess is not None:
                sess.doom_score = max(0, sess.doom_score - 10)  # 不能低于 0


async def _apply_plot_turn(
    session: AsyncSession,
    session_id: int,
    attrs: dict[str, str],
    current_turn: int,
) -> None:
    # -------------------------------------------------------
    # 处理 <plot_turn impact=major|minor description="..."/> 标签
    #
    # 剧情转折分两类：
    # - minor（次要）：观察性记录，本函数不做任何数据库写操作
    #   （后续可能用于消息历史的 events_json）
    # - major（重大）：创建一条 ScreenplayRevision 记录
    #   这个记录是"剧本重写"的触发信号，记录了：
    #     - 重写触发的回合（trigger_turn）
    #     - 触发原因描述（trigger_description）
    #     - 重写前的剧本快照（before_chapters_json）
    #   实际的重写内容（after_chapters_json）由异步的 outliner 任务填写，
    #   这里只是先把"触发事件"存档，让重写链有完整的来源追溯。
    #
    # 【设计意图】
    # 玩家的重大决策（如拒绝盟友、杀死关键 NPC）应该能影响剧情走向。
    # plot_turn major 就是 GM 表达"PC 的选择改变了故事方向"的信号，
    # 触发后台大纲重写任务，使后续章节适应玩家的选择。
    # -------------------------------------------------------
    """<plot_turn impact=major|minor description=...> → only major creates a
    ScreenplayRevision row. The actual rewrite (after_chapters_json + diff_summary)
    is left to a later async outliner pass; we just stash the trigger and the
    *before* snapshot so the chain has provenance. minor is observational and
    intentionally a no-op here (we may pipe it into messages.events_json later).
    """
    impact = (attrs.get("impact") or "minor").strip().lower()
    if impact != "major":
        return  # minor 转折是观察性记录，此处不做处理

    sp = await _get_active_screenplay(session, session_id)
    if sp is None:
        return

    # 截取描述文字（最多 500 字，防止无限长度）
    description = str(attrs.get("description", ""))[:500]

    # 创建剧本修订记录（快照保留，实际重写内容留给后台异步任务）
    rev = ScreenplayRevision(
        screenplay_id=sp.id,
        revision_num=1,                              # 修订编号（后续可能递增）
        trigger_turn=current_turn,                   # 在第几回合触发的
        trigger_description=description,             # 触发原因
        before_chapters_json=sp.chapters_json or "[]",  # 重写前的剧本快照
        after_chapters_json=sp.chapters_json or "[]",   # 重写后内容（暂时等于 before，等待 outliner 填写）
        diff_summary="(pending outliner rewrite)",   # 差异摘要，等待 outliner 异步填写
    )
    session.add(rev)


async def _apply_ending(
    session: AsyncSession,
    session_id: int,
    attrs: dict[str, str],
    current_turn: int,
) -> None:
    # -------------------------------------------------------
    # 处理 <ending/> 标签
    #
    # GM 决定故事走向结局时 emit 此标签。
    # 处理方式：把活跃剧本的状态改为 "concluded"，记录结局时间戳。
    #
    # 结局后玩家可以从同一个游戏局开启续集（新的 active Screenplay），
    # 因此这里只是标记"已结局"，不删除数据。
    # -------------------------------------------------------
    """<ending/> → mark active screenplay status="concluded" + concluded_at=now.
    Player can later launch a fresh chapter from the same session if desired."""
    sp = await _get_active_screenplay(session, session_id)
    if sp is None:
        return
    sp.status = "concluded"                                        # 标记为"已结局"
    sp.concluded_at = datetime.now(UTC).replace(tzinfo=None)       # 记录结局时间（不带时区，存 UTC）
