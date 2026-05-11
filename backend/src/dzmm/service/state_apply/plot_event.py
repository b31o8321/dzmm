# ============================================================
# 剧情事件（Plot Event）处理模块
#
# 负责处理 <plot_event> XML 标签，将 GM 叙述的剧情事件写入 PlotThread 表。
#
# 典型的 GM 输出示例：
#   <plot_event type="new_quest" importance="3">调查灯塔里的神秘信号</plot_event>
#   <plot_event type="hook_resolved" thread_id="12">谜团已解开</plot_event>
#
# 【PlotThread（剧情线）系统】
# 每个 PlotThread 行代表一条"开放中的剧情线索"，例如：
#   - new_quest：玩家接取了新任务
#   - hook_introduced：GM 埋下了一个钩子（伏笔）
#   - major_event：发生了重大事件
#   - location_entered：PC 进入了新地点（也作为剧情记录）
#   - hook_resolved：之前的钩子/任务被解决了
#
# 这些记录构成前端"剧情追踪面板"的数据来源。
#
# 【去重（Dedup）逻辑】
# LLM 非常容易重复 emit 相似内容的 plot_event 标签（措辞略有不同但含义相同）。
# 不去重的话，面板里会出现大量重复条目。
# 本模块使用字符串相似度（SequenceMatcher）对新事件和已有活跃线索进行比对，
# 相似度超过阈值则视为重复并跳过。
# ============================================================

"""<plot_event> handler + dedup helpers."""

import logging
import re
from difflib import SequenceMatcher  # Python 标准库的字符串相似度计算器

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.db.models import PlotThread

log = logging.getLogger(__name__)

# -------------------------------------------------------
# 去重相似度阈值
#
# 两个描述文本经过标准化后，SequenceMatcher.ratio() >= 此值即视为"重复"。
# 历史调整记录：
#   v0.13 之前：0.7（太高，很多近似重复没被过滤）
#   v0.13 调整：0.6（仍然太高，实测 0.79-0.95 的重复对没被过滤）
#   当前值：0.45（宽松阈值，实测"调查重力场异常" vs "寻找解药救小菱" 比值为 0.0，
#   不会把不相关的任务误判为重复）
# -------------------------------------------------------
# Similarity threshold for plot_event dedup (new_quest / hook_introduced /
# major_event / location_entered).
# v0.13: lowered 0.7 -> 0.6 after a 9-turn play session where 5 near-identical
# rows still slipped through despite ratios ~0.79-0.95 between them. Root
# cause was a mix of un-normalized whitespace and incidentally-low ratio after
# the GM rephrased entire clauses. 0.6 still rejects clearly-distinct quests
# (e.g. "调查重力场异常" vs "寻找解药救小菱" → ratio 0.0) so false-collapse
# risk is low; the empirical user pair scores 0.79 → safely caught.
_PLOT_DEDUP_RATIO = 0.45

# 会创建新 PlotThread 行的事件类型（需要去重的类型）
# hook_resolved 不在此列，因为它走"关闭已有线索"的逻辑，不创建新行
# Plot-event types that create a *new* thread row. Any tag whose type is in
# this set goes through dedup against existing active threads; types not
# listed (e.g. hook_resolved) take a separate path. We deliberately include
# major_event and location_entered: in practice the GM also restates these
# across turns and they end up as duplicate panel entries.
_THREAD_CREATING_TYPES = frozenset(
    {"new_quest", "hook_introduced", "major_event", "location_entered"}
)


def _normalize_for_dedup(text: str) -> str:
    # -------------------------------------------------------
    # 文本标准化（用于相似度比较前的预处理）
    #
    # 为什么需要标准化？
    # SequenceMatcher 对标点符号和空白字符非常敏感。
    # 如果 GM 在两次 emit 中只是把"，"换成了","，
    # 或者多加了一个空格，SequenceMatcher 的比值会被拉低，
    # 导致实际上相同的内容没被识别为重复。
    #
    # 标准化步骤：
    # 1. 全角空格/NBSP → 普通空格
    # 2. 连续空白 → 单个空格
    # 3. 去除首尾空白
    # 4. CJK 全角标点 → ASCII 标点（让"A，B"和"A,B"相等）
    # 5. 转小写（英文大小写不影响语义）
    # -------------------------------------------------------
    """Aggressive normalize before similarity comparison.

    The GM frequently emits visually-similar descriptions that the raw
    SequenceMatcher under-rates because they differ in punctuation width,
    whitespace, or letter case. We:
      - replace full-width spaces (U+3000) and NBSP (U+00A0) with ASCII space
      - collapse runs of any whitespace to a single space
      - strip leading/trailing whitespace
      - normalize a few common CJK punctuation marks to ASCII
      - lowercase (helps when GM mixes English locale words)
    """
    if not text:
        return ""
    # Full-width space (U+3000) + NBSP (U+00A0) -> ASCII space
    text = text.replace("　", " ").replace(" ", " ")
    # Collapse all whitespace runs (also handles tabs, line breaks)
    text = re.sub(r"\s+", " ", text)
    text = text.strip()
    # Punctuation: CJK forms -> ASCII so "A，B" and "A,B" compare equal
    text = (
        text.replace("，", ",")
        .replace("。", ".")
        .replace("！", "!")
        .replace("？", "?")
        .replace("：", ":")
        .replace("；", ";")
    )
    return text.lower()


def _is_duplicate_thread(
    new_desc: str,                      # 待插入的新事件描述
    existing_threads: list[PlotThread], # 现有活跃线索列表
) -> int | None:
    # -------------------------------------------------------
    # 判断新事件是否与已有活跃线索重复
    #
    # 返回：
    # - 重复的线索 ID（int）：发现重复
    # - None：不重复，可以插入
    #
    # 算法：
    # 1. 标准化两边的文本
    # 2. 精确匹配优先（快速路径）
    # 3. 用 SequenceMatcher 计算相似度，超过阈值视为重复
    # -------------------------------------------------------
    """If `new_desc` is substantially the same as an existing active thread's
    description (SequenceMatcher ratio >= _PLOT_DEDUP_RATIO after
    normalization), return its id; else None. Empty descriptions never match.
    Exact post-normalization equality short-circuits to a hit."""
    new_norm = _normalize_for_dedup(new_desc)
    if not new_norm:
        return None  # 空描述不参与去重
    for t in existing_threads:
        old_norm = _normalize_for_dedup(t.description or "")
        if not old_norm:
            continue
        if new_norm == old_norm:
            return t.id  # 精确相等，直接认定为重复（快速路径）
        ratio = SequenceMatcher(None, new_norm, old_norm).ratio()
        if ratio >= _PLOT_DEDUP_RATIO:
            return t.id  # 相似度超过阈值，认定为重复
    return None  # 与所有现有线索都不重复


async def _apply_plot_event(
    session: AsyncSession,
    session_id: int,
    current_turn: int,
    attrs: dict[str, str],
    content: str,
) -> None:
    # -------------------------------------------------------
    # 处理 <plot_event> 标签的主函数
    #
    # 逻辑分支：
    # 1. type="hook_resolved" → 关闭已有线索（标记为 resolved）
    # 2. 其他创建型类型 → 去重检查 → 创建新 PlotThread 行
    # -------------------------------------------------------
    event_type = attrs.get("type", "major_event")  # 默认类型为 major_event
    try:
        importance = int(attrs.get("importance", "2"))  # 重要性 1-3，默认 2
    except ValueError:
        importance = 2
    importance = max(1, min(3, importance))  # 强制限制在 [1, 3] 范围

    description = content.strip()  # 事件描述来自标签 body
    if not description:
        return  # 没有描述文字则跳过（残缺标签）

    if event_type == "hook_resolved":
        # -------------------------------------------------------
        # 解决已有线索
        #
        # GM 通过 thread_id 属性指定要关闭哪条线索，
        # 如果没有指定 thread_id 或者找不到，则关闭最近（最新）的一条活跃线索。
        # -------------------------------------------------------
        thread_id_str = attrs.get("thread_id", "").strip()
        target = None
        if thread_id_str.isdigit():
            target = await session.get(PlotThread, int(thread_id_str))  # 精确 ID 查找
        if target is None:
            # 兜底：取最近引入的活跃线索（最新插入的）
            target = (
                await session.execute(
                    select(PlotThread)
                    .where(
                        PlotThread.session_id == session_id,
                        PlotThread.status == "active",
                    )
                    .order_by(PlotThread.introduced_turn.desc())  # 最近引入的排在最前
                    .limit(1)
                )
            ).scalar_one_or_none()
        if target is not None:
            target.status = "resolved"          # 标记为已解决
            target.resolution = description     # 记录解决方式的描述
        return

    # -------------------------------------------------------
    # 创建型事件类型：去重检查
    #
    # 只对 _THREAD_CREATING_TYPES 中的类型做去重，
    # 已解决（resolved）的线索不参与比对（重新开启的任务应算新线索）。
    # -------------------------------------------------------
    # Dedup against existing *active* threads for any thread-creating type —
    # GM frequently re-emits the same quest description across turns with
    # minor wording tweaks, which previously inflated the plot_threads table.
    # v0.13: extended from {new_quest, hook_introduced} to also cover
    # major_event + location_entered (same problem in production logs).
    # Resolved threads are intentionally NOT considered (a re-opened version
    # of an old quest deserves a fresh row).
    if event_type in _THREAD_CREATING_TYPES:
        existing = list(
            (
                await session.execute(
                    select(PlotThread).where(
                        PlotThread.session_id == session_id,
                        PlotThread.status == "active",  # 只对比活跃线索
                    )
                )
            ).scalars()
        )
        dup_id = _is_duplicate_thread(description, existing)
        if dup_id is not None:
            # 发现重复，记录日志并跳过
            log.info(
                "plot_event dedup: skip new %r (matches existing thread #%d, turn %d)",
                description[:60],
                dup_id,
                current_turn,
            )
            return  # 静默跳过，不插入重复行

    # 去重通过，创建新 PlotThread 行
    thread = PlotThread(
        session_id=session_id,
        type=event_type,               # 线索类型
        description=description,       # 线索描述
        introduced_turn=current_turn,  # 哪个回合引入的
        importance=importance,         # 重要性（1-3）
        status="active",               # 初始状态为活跃
    )
    session.add(thread)
    await session.flush()  # 立即刷新让 ID 生效（本回合后续操作可能引用这个 ID）
