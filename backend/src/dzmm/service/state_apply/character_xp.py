# ============================================================
# 角色经验值（XP）处理模块
#
# 负责处理 <character_xp> XML 标签，修改玩家角色的经验值（Xp）。
#
# 【XP / 等级系统的游戏设计意图】
# 在 dzmm 跑团引擎中，玩家角色通过完成故事事件来积累经验值（XP）。
# XP 达到一定阈值后，角色可以升级，玩家在升级时可以选择提升某项属性。
#
# XP 来源有两种：
# 1. 自动奖励（screenplay.py 中的 _apply_event_complete）：
#    - 完成主线事件（_XP_MAIN = 50）
#    - 完成支线事件（_XP_OPTIONAL = 20）
#    这些是系统自动计算的，GM 不需要操心
#
# 2. GM 手动奖励（本模块）：
#    GM 可以为特殊的玩家行为（机智的决策/英雄行为/创意解法）
#    额外奖励 XP，通过 <character_xp delta="N"/> 标签 emit
#
# 【为什么不在这里自动升级？】
# 升级是一个需要玩家参与的决策点（选择提升哪个属性），
# 不应该在后台静默发生。
# 前端会检测 XP 是否跨越了升级门槛，如果是，
# 就引导玩家进入 /levelup 流程，由玩家主动选择升级奖励。
#
# 典型的 GM 输出示例：
#   <character_xp delta="30"/>  （奖励 30 XP）
#   <character_xp delta="-10"/> （罚扣 10 XP，极少见）
# ============================================================

"""<character_xp> handler — bump Character.xp."""

from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.db.models import Character, Session as GameSession


async def _apply_character_xp(
    session: AsyncSession,
    session_id: int,
    attrs: dict[str, str],  # XML 属性，含 delta="N"
    content: str,           # 标签 body（通常为空，XP 标签一般没有 body）
) -> None:
    # -------------------------------------------------------
    # 处理 <character_xp delta="N"> 标签
    #
    # 执行步骤：
    # 1. 解析 delta 属性（整数，正数加 XP，负数扣 XP）
    # 2. 通过 session_id → GameSession → character_id → Character 找到角色
    # 3. 把 delta 累加到 Character.xp，并确保 XP 不低于 0
    # -------------------------------------------------------
    """Apply <character_xp delta="N"> by mutating Character.xp.

    Note: we don't auto-bump Character.level here; the frontend detects when
    the threshold is crossed and routes the user through /levelup, which
    advances the level and applies the player-chosen stat bonus.
    """
    try:
        delta = int(attrs.get("delta", "0"))  # 解析增量，默认为 0
    except ValueError:
        return  # delta 不是合法整数，忽略这个标签
    if delta == 0:
        return  # 增量为 0 时无意义，直接跳过

    # 通过游戏局找到玩家角色
    # 注意查询路径：session_id → GameSession → character_id → Character
    # 这是因为同一个 Character 可以参与多个 GameSession
    sess = await session.get(GameSession, session_id)
    if sess is None:
        return  # 游戏局不存在，跳过
    char = await session.get(Character, sess.character_id)
    if char is None:
        return  # 角色不存在，跳过（理论上不应发生）
    char.xp = max(0, char.xp + delta)  # 累加 XP，确保不低于 0（XP 不应为负数）
