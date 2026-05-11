# ============================================================
# 末日时钟（Doom Clock）处理模块
#
# 负责处理 <doom> XML 标签，修改当前游戏局的末日时钟数值。
#
# 【末日时钟系统的游戏设计意图】
# "末日时钟"（doom_score）是一个 0-100 的全局压力指标，代表
# "如果 PC 不采取行动，坏事发生的紧迫程度"。
#
# 设计灵感来自现实中的末日时钟（象征核战争风险）和
# 跑团游戏中常见的"倒计时"机制。
#
# doom_score 的变化规则：
#   增加：
#     - GM 叙事中出现了危险信号（emit <doom delta="+5"/>）
#     - PC 做出了糟糕的决策
#     - 时间流逝而 PC 没有行动
#   减少：
#     - 完成主线事件时自动减少 10（screenplay.py 中实现）
#     - GM 决定 PC 的某个行动缓解了危机（emit <doom delta="-10"/>）
#
# 前端展示：
# - doom_score 显示在面板上，让玩家能感受到"紧迫感"
# - 可能触发特殊叙事效果（如 doom_score >= 80 时提示"危机迫在眉睫"）
#
# 典型的 GM 输出示例：
#   <doom delta="+10"/>  （危机升级）
#   <doom delta="-5"/>   （缓解了一些压力）
# ============================================================

"""<doom delta="±N"> handler — update Session.doom_score (0-100)."""

from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.db.models import Session as GameSession


async def _apply_doom(
    session: AsyncSession,
    session_id: int,
    attrs: dict[str, str],  # XML 属性，含 delta="±N"
) -> None:
    # -------------------------------------------------------
    # 处理 <doom delta="±N"> 标签
    #
    # delta 是有符号整数：
    #   正数（+N）= 末日时钟推进（情况变糟）
    #   负数（-N）= 末日时钟回退（危机缓解）
    #
    # 结果强制限制在 [0, 100]，确保值始终在合理范围内。
    # -------------------------------------------------------
    try:
        delta = int(attrs.get("delta", "0"))  # 解析增量，默认为 0
    except ValueError:
        return  # delta 不是合法整数，忽略这个标签
    if delta == 0:
        return  # 增量为 0 时无意义，直接跳过

    sess = await session.get(GameSession, session_id)
    if sess is None:
        return  # 游戏局不存在，跳过

    # 累加 delta 并限制在 [0, 100] 范围内
    # max(0, ...) 确保不低于 0（危机不能"为负"）
    # min(100, ...) 确保不超过 100（上限是"末日已至"）
    sess.doom_score = max(0, min(100, sess.doom_score + delta))
