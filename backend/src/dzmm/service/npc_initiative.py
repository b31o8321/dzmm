# ============================================================
# npc_initiative.py — NPC 主动联络系统
# ============================================================
# 【什么是 NPC 主动联络（initiative）？】
#   传统跑团里，NPC 通常是被动的——玩家去找他们，他们才出现。
#   主动联络机制让 NPC 在合适的时机主动出现在玩家面前，
#   使世界显得更有生命力，NPC 像真实的人一样有自己的节奏。
#
# 【游戏设计意图】
#   - 好感高的 NPC 更容易主动联络（想念玩家，有话说）
#   - 久未登场的 NPC 会抓住机会冒个头（避免某些 NPC 被遗忘）
#   - 冷却期（cooldown）防止同一个 NPC 每回合都出现（显得烦人）
#   - 只有已与玩家相遇过的 NPC 才会主动联络（合理性保证）
#
# 【调用时机】
#   每回合 GM 处理前，game.run_turn 调用 find_initiative_npc()，
#   如果找到候选 NPC，就在 Prompt 里指示 GM 让这个 NPC 主动出现。
# ============================================================

import json
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.db.models import Message as MessageRow, NPC

log = logging.getLogger(__name__)

# v0.10.2: 原本用 last_seen_turn（NPC 出现就算），但 v0.10 里只要叙述提到名字就会
# 更新 last_seen_turn，即使 NPC 根本没开口。
# 改用 last_spoke_turn（真正有 <say> 标签才算），所以阈值降为 1：
# 上回合在场但没说话的 NPC，这回合可以有机会发言（延迟反应）
_INACTIVE_TURNS_MIN = 1

# 同一个 NPC 两次主动联络之间至少要隔几回合（防止频繁骚扰玩家）
_COOLDOWN_TURNS = 4

# 往前看多少回合的助手消息，用于判断 NPC 最后一次说话的时间
_LOOKBACK_TURNS = 8


def _eagerness(npc: NPC) -> int:
    # 计算 NPC 的"主动性分数"，分数越高越可能被选为本回合主动联络的 NPC
    #
    # 计分规则：
    # - 钉选 NPC（剧本主要角色）基础 +10（他们是故事的核心，应该活跃）
    # - 好感度每 5 点 +1（好感越高，越想见玩家）
    # - 情绪强度越高 +（max情绪值÷10）（情绪激动时更容易主动出击）
    score = 10 if npc.pinned else 0       # 钉选加成
    score += max(0, npc.favor // 5)       # 好感加成（负好感不减分，只是不加）
    try:
        # emotion_json 格式如 {"愤怒": 70, "悲伤": 20}，取最大值
        emotion = json.loads(npc.emotion_json or "{}")
        if emotion:
            score += max(emotion.values()) // 10  # 情绪加成
    except (TypeError, ValueError):
        pass
    return score


async def _last_spoke_turn(
    session: AsyncSession,
    session_id: int,
    npc_name: str,     # NPC 的姓名
    current_turn: int, # 当前回合数（用于限定查找范围）
) -> int:
    # 在最近 _LOOKBACK_TURNS 条助手消息里，找到这个 NPC 最近一次说话的回合数
    # "说话"定义：events_json 里有 type="say" 且 speaker 等于 npc_name 的事件
    # 如果从未说过话，返回 0
    if not npc_name:
        return 0
    # 只查最近几回合（不是全部历史），避免扫描过多数据库行
    rows = (await session.execute(
        select(MessageRow.turn, MessageRow.events_json)
        .where(
            MessageRow.session_id == session_id,
            MessageRow.role == "assistant",                           # 只看 GM 的回复（助手消息）
            MessageRow.turn >= max(1, current_turn - _LOOKBACK_TURNS),  # 最近 N 回合
        )
        .order_by(MessageRow.turn.desc())  # 从最新的往前查，找到就可以提前返回
    )).all()
    for turn, events_json in rows:
        if not events_json:
            continue
        try:
            events = json.loads(events_json)  # events_json 是 JSON 数组
        except (TypeError, ValueError):
            continue
        if not isinstance(events, list):
            continue
        for ev in events:
            if not isinstance(ev, dict):
                continue
            if ev.get("type") != "say":
                continue  # 只关心 say 类型的事件
            payload = ev.get("payload") or {}
            speaker = payload.get("speaker", "") if isinstance(payload, dict) else ""
            if speaker == npc_name:
                return int(turn)  # 找到了，返回回合数
    return 0  # 在 lookback 范围内没有找到


async def find_initiative_npc(
    session: AsyncSession,
    session_id: int,
    current_turn: int,
) -> NPC | None:
    # 在所有 NPC 里找出这回合最适合主动联络玩家的那一个，没有候选则返回 None
    #
    # 【资格条件】（全部满足才进入候选池）
    # 1. 已经与玩家相遇过（last_seen_turn > 0）—— 陌生 NPC 不会凭空联络
    # 2. 最近一次说话不在最近 _INACTIVE_TURNS_MIN 回合内
    #    （从未说过话的 NPC 永远有资格，因为他们的声音"还没被听到"）
    # 3. 距离上次主动联络已经过了冷却期（current_turn - last_initiative_turn ≥ 4）
    # 4. 主动性分数 > 0

    # 读取这个存档的全部 NPC
    npcs = (await session.execute(
        select(NPC).where(NPC.session_id == session_id)
    )).scalars().all()

    eligible: list[tuple[int, NPC]] = []  # (分数, NPC) 的候选列表
    for npc in npcs:
        # 条件1：必须已与玩家相遇过
        if npc.last_seen_turn == 0:
            continue

        # 查询这个 NPC 最近一次说话的回合
        spoke_turn = await _last_spoke_turn(
            session, session_id, npc.name, current_turn,
        )
        # 从未说过话（spoke_turn=0）的 NPC 始终有资格——他们最有理由"插一嘴"
        # 说过话但上次说话太近（还在冷却期内），跳过
        if spoke_turn > 0 and (current_turn - spoke_turn) < _INACTIVE_TURNS_MIN:
            continue

        # 条件3：两次主动联络之间的冷却期
        turns_since_initiative = current_turn - npc.last_initiative_turn
        if turns_since_initiative < _COOLDOWN_TURNS:
            continue  # 冷却中，跳过

        # 计算主动性分数
        score = _eagerness(npc)
        if score <= 0:
            continue  # 分数为 0 不参与竞争

        eligible.append((score, npc))

    if not eligible:
        return None  # 没有符合条件的 NPC，本回合无人主动联络

    # 排序规则（优先级从高到低）：
    # 1. 主动性分数（高优先）
    # 2. 好感度（高优先，作为打平时的次级排序）
    # 3. 上次出现的回合（越久没出现越优先，让冷落的 NPC 有机会）
    eligible.sort(key=lambda x: (-x[0], -x[1].favor, -x[1].last_seen_turn))
    return eligible[0][1]  # 返回排名最高的 NPC
