# ============================================================
# PC 情绪系统模块
#
# 负责处理 <pc_mood> XML 标签，记录玩家角色（PC）的情绪状态变化。
#
# 【PC 情绪系统的游戏设计意图】
# 在跑团游戏中，玩家角色不是没有情感的机器。
# 经历了一场激战后，PC 可能会感到"紧张"；
# 拿到重要线索后，PC 可能会感到"兴奋"；
# 连续失败后，PC 可能会感到"沮丧"。
#
# pc_mood 系统让 GM 可以追踪这些情绪变化，
# 情绪状态会被注入后续回合的 GM 提示词，
# 让 GM 的叙事和 NPC 反应能够考虑到 PC 当前的心理状态。
#
# 【设计选择：自由格式情绪轴】
# 与 NPC 的 emotion 系统（固定五轴）不同，
# PC 情绪使用完全自由格式的关键词 → 数值映射，
# 例如：{"紧张": 70, "兴奋": 30, "疲惫": 50}
#
# 为什么 PC 用自由格式而不是固定轴？
# - PC 的情绪更丰富、更情境化，不适合固定几个轴
# - GM 可以根据剧情创造性地使用任意情绪关键词
# - 前端展示时只需显示"当前较高的几个情绪维度"即可
#
# 典型的 GM 输出示例：
#   <pc_mood>{"紧张": 15, "好奇": 10, "疲惫": -5}</pc_mood>
# ============================================================

"""<pc_mood> handler — accumulate mood deltas into Session.pc_mood_json."""

import json

from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.db.models import Session as GameSession
from dzmm.parsing.repair import parse_loose_json  # 宽松 JSON 解析


async def _apply_pc_mood(
    session: AsyncSession,
    session_id: int,
    raw: str,   # 标签 body，应该是 JSON 格式的情绪增量字典
) -> None:
    # -------------------------------------------------------
    # 处理 <pc_mood> 标签
    #
    # 数据结构：Session.pc_mood_json 存储一个 JSON 字典，
    # 键是情绪关键词（GM 自定义），值是当前强度（0-100 之间的整数）。
    #
    # 操作方式：增量更新（delta）
    # - raw 里的值是"增量"而不是绝对值
    # - 正值表示这个情绪增强，负值表示减弱
    # - 结果强制限制在 [0, 100]，防止溢出
    # - 从未出现过的情绪关键词从 0 开始计算
    # -------------------------------------------------------
    """Accumulate PC mood deltas into Session.pc_mood_json.

    Mood is a free-form keyword→int map (GM picks keywords like 紧张/兴奋/疲惫).
    Values clamp to [0, 100]. Missing keys start at 0."""
    payload = parse_loose_json(raw)  # 把 body 文本解析成字典，容忍不规范 JSON
    if not isinstance(payload, dict):
        return  # body 不是 JSON 对象，忽略整个标签

    sess = await session.get(GameSession, session_id)
    if sess is None:
        return  # 游戏局不存在，不做处理

    # 读取现有情绪状态（可能为空 "{}"）
    moods = json.loads(sess.pc_mood_json or "{}")
    if not isinstance(moods, dict):
        moods = {}  # 数据损坏时用空字典兜底

    # 遍历 GM 提供的情绪增量，累加到现有值上
    for axis, delta in payload.items():
        if not isinstance(delta, (int, float)):
            continue  # 非数字值跳过（防止 GM 输出字符串类型的值）
        axis_key = str(axis)
        new_val = int(moods.get(axis_key, 0) + delta)  # 从现有值累加 delta
        moods[axis_key] = max(0, min(100, new_val))     # 限制在 [0, 100]

    sess.pc_mood_json = json.dumps(moods, ensure_ascii=False)  # 写回数据库
