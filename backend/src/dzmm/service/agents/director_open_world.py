# ============================================================
# director_open_world.py — 开放世界模式的「剧本导演」Agent
#
# 【Director agent 是什么？】
# Director（导演）是一个在幕后运行的 LLM agent，玩家看不到它。
# 它每隔几回合（或在关键时刻）出手，给 Scene agent 下一道「剧情指令」
# （plot_directive），告诉 Scene：本回合应该重点推进哪个事件、
# 哪个 NPC 该出现、节奏应该紧张还是舒缓、有什么是禁止的。
# Director 是「幕后编剧」，Scene 是「前台说书人」。
#
# 【开放世界 Director vs 章节剧本 Director】
# 章节剧本 Director（director.py）：跟着预设章节/主线事件走，
# 像在执行一个固定剧本。
# 开放世界 Director（本文件）：没有固定章节，根据世界地图上的
# WorldEvent（世界事件）、NPC 状态、派系紧张度动态决策。
# 玩家在地图上走到哪里、附近有什么事件正在发酵，Director 就推什么。
#
# 【评分算法：distance_factor 和 importance 是怎么工作的？】
# 每个 WorldEvent 有一个 importance（重要性，1-5 的整数）。
# Director 会用公式：score = importance × distance_factor 给事件打分，
# 然后把分数最高的几个事件告诉 LLM，让它决定本回合主推哪个。
#
# distance_factor（距离衰减因子）的逻辑：
#   - 距离 0（事件就在玩家所在地点）→ factor = 1.0（完整权重）
#   - 距离 1（隔一个地点）           → factor = 0.8（轻微衰减）
#   - 距离 2（隔两个地点）           → factor = 0.5（较大衰减）
#   - 距离 ≥ 3                       → score = 0，改为「谣言」渠道传递
#
# 直觉：玩家当然更容易被自己所在地点的事情卷入，
# 远处的事件影响力弱，只能作为道听途说的消息。
# ============================================================
"""Open-world Director agent.

Replaces the screenplay-chapter Director for sessions with framework_id set.
Scores nearby WorldEvents using a spatial decay formula, delivers far events
as rumors, checks NPC proactive contact, then calls the LLM for plot_directive.
"""
from __future__ import annotations

import json
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession  # 异步数据库会话

from dzmm.models.client import GenerationParams, ModelClient
from dzmm.prompts.director_open_world_template import build_open_world_director_messages
from dzmm.service.agents.streams import (
    append_message,
    get_or_create_stream,
    load_history,
)
from dzmm.service.world_graph import bfs_distance, build_graph  # 地图距离计算

log = logging.getLogger(__name__)

STREAM_KIND_DIRECTOR = "gm_director"   # AgentStream 的种类标识
DIRECTOR_HISTORY_MAX = 20              # 最多保留 20 条 Director 历史消息
_PARAMS = GenerationParams(temperature=0.4, max_tokens=500)  # LLM 生成参数

# 谣言冷却期：同一事件最少间隔多少回合才能再次作为谣言传递
_RUMOR_COOLDOWN_TURNS = 5
# 谣言的最低重要性门槛：太不重要的远处事件不值得作为谣言传递
_RUMOR_MIN_IMPORTANCE = 3

# LLM 调用失败时的兜底指令（让 Scene 继续正常推进，不要报错）
_FALLBACK_DIRECTIVE = (
    "<plot_directive>\n"
    "- 本回合主推：推进当前附近最高优先级事件\n"
    "- NPC 重点：（无）\n"
    "- 节奏：常态\n"
    "- 禁止：不要无视玩家本回合输入\n"
    "</plot_directive>"
)

# 距离衰减因子表：距离 → 权重乘数
# 超过 2 的距离不在这里，因为 score_event 遇到 distance >= 3 直接返回 0.0
_DIST_FACTORS = {0: 1.0, 1: 0.8, 2: 0.5}


# ────────────────────────────────────────────────────────────
# 事件评分函数
# ────────────────────────────────────────────────────────────

def score_event(
    event: dict,
    pc_location_id: int,
    distance: int,
    companion_npc_ids: set[int],
    faction_rep_npcs: set[int],
    npc_template_ids_in_event: set[int] | None = None,
) -> float:
    # 【评分算法详解】
    # 基础分 = importance × distance_factor
    # 加成规则：
    #   - 事件里有玩家的同伴 NPC → +0.3（同伴在场的事件更紧迫）
    #   - 事件里有派系代表 NPC  → +0.2（影响派系关系的事件更重要）
    # 最终分数越高，Director 越倾向于本回合推进这个事件。
    #
    # 为什么距离 ≥ 3 直接返回 0.0？
    # 超过 3 跳的事件对玩家当前行动影响极小，
    # 与其占用 Director 的注意力，不如用「谣言」的方式轻描淡写地提一句。
    """Compute Director priority score for a WorldEvent.

    Returns 0.0 for events at distance ≥ 3 (handled by rumor channel instead).
    Formula: importance × distance_factor + companion_bonus + faction_bonus
    """
    if distance >= 3:
        return 0.0  # 太远的事件评分为 0，走谣言渠道
    dist_factor = _DIST_FACTORS.get(distance, 0.0)  # 查距离衰减表
    # importance 是 1-5 的整数，越大越重要
    score = float(event["importance"]) * dist_factor

    # 如果事件里涉及的 NPC 是玩家的同伴，加分
    npc_ids = npc_template_ids_in_event or set()
    if companion_npc_ids & npc_ids:  # 集合取交集，非空说明有重叠
        score += 0.3
    if faction_rep_npcs & npc_ids:  # 同理，派系代表
        score += 0.2
    return score


# ────────────────────────────────────────────────────────────
# 谣言资格判断函数
# ────────────────────────────────────────────────────────────

def is_rumor_eligible(
    event: dict,
    distance: int,
    delivered: bool,
    turns_since_last: int,
    cooldown: int = _RUMOR_COOLDOWN_TURNS,
) -> bool:
    # 谣言是把远处事件以「风闻」方式告诉玩家的机制。
    # 不是所有远处事件都适合做谣言，需要同时满足：
    #   1. 还没传递过这条谣言（delivered=False）
    #   2. 距离 ≥ 3（近处事件直接发生，不走谣言渠道）
    #   3. 重要性 ≥ 3（太不重要的消息不值得提）
    #   4. 距离上次传递已超过冷却期（防止反复提同一件事）
    """Return True if a far event qualifies for rumor delivery."""
    if delivered:
        return False  # 这条谣言已经传递过了
    if distance < 3:
        return False  # 近处事件不走谣言渠道
    if event["importance"] < _RUMOR_MIN_IMPORTANCE:
        return False  # 重要性太低，不值得
    if turns_since_last < cooldown:
        return False  # 冷却期内，不重复
    return True


# ────────────────────────────────────────────────────────────
# NPC 主动联系判断函数
# ────────────────────────────────────────────────────────────

def check_npc_proactive_contact(
    npc_states: list[dict],
    pc_location_id: int,
    current_turn: int,
) -> dict | None:
    # 某些 NPC 好感度高到一定程度会「主动找玩家联系」，
    # 就像现实中的朋友会主动发消息。
    # 这个函数找出本回合最适合主动联系的 NPC（如果有）。
    #
    # 条件（全部满足才算候选）：
    #   - 还活着（is_alive=True）
    #   - 不是同伴（同伴一直跟着，不需要「主动联系」）
    #   - 好感度达到该 NPC 的联系门槛（contact_favor_threshold）
    #   - 不在玩家当前地点（如果在同一地点就是直接对话了）
    #   - 上次联系已超过冷却期（contact_cooldown_turns）
    # 从候选中选好感度最高的那个。
    """Return the best NPC candidate for proactive contact this turn, or None.

    Conditions (all must be true):
    - is_alive
    - not is_companion (companions are always with PC)
    - favor >= contact_favor_threshold
    - current_location_id != pc_location_id (NPC is away)
    - current_turn - last_contact_turn >= contact_cooldown_turns
    """
    candidates = []
    for npc in npc_states:
        if not npc.get("is_alive", True):
            continue  # 死亡的 NPC 不会联系玩家
        if npc.get("is_companion", False):
            continue  # 同伴一直在场，不需要「主动联系」
        if npc.get("favor", 0) < npc.get("contact_favor_threshold", 70):
            continue  # 好感度不够，还不到主动联系的阶段
        if npc.get("current_location_id") == pc_location_id:
            continue  # 同地点的 NPC 会直接出现在场景里
        last_contact = npc.get("last_contact_turn", 0)
        cooldown = npc.get("contact_cooldown_turns", 10)
        if current_turn - last_contact < cooldown:
            continue  # 联系得太频繁了，先等等
        candidates.append(npc)
    if not candidates:
        return None
    # 从所有候选中选好感度最高的那个（最想联系玩家的）
    return max(candidates, key=lambda n: n.get("favor", 0))


# ════════════════════════════════════════════════════════════
# 核心函数：运行开放世界 Director
# ════════════════════════════════════════════════════════════

async def run_open_world_director(
    s: AsyncSession,
    session_id: int,
    framework_id: int,          # 开放世界框架的 ID（关联世界地图和事件库）
    client: ModelClient,        # 用于生成剧情指令的 LLM 客户端
    current_turn: int,
    pc_location_id: int,        # 玩家当前所在地点的 ID（用于计算距离）
    character_name: str,        # 玩家角色名字
    character_md: str,          # 玩家角色的 Markdown 描述
) -> tuple[str, int, int]:
    # 整个函数的工作流：
    #   1. 加载世界地图（WorldLocation），构建图结构
    #   2. 加载所有世界事件（WorldEvent）
    #   3. 过滤掉已触发/完成的事件
    #   4. 计算每个事件到玩家当前位置的距离
    #   5. 用评分公式筛选「候选事件」（近处高分事件）
    #   6. 识别适合传递的「谣言事件」（远处高重要性事件）
    #   7. 检查是否有 NPC 要主动联系玩家
    #   8. 加载派系紧张度、战役阶段等背景信息
    #   9. 构建快照，调用 LLM 生成 plot_directive
    """Run the open-world Director for one turn.

    Loads WorldLocations + pending WorldEvents + SessionNpcStates from DB,
    computes scoring, builds snapshot, calls LLM, returns (directive, tok_in, tok_out).
    """
    from dzmm.db.models import (
        WorldLocation,
        WorldEvent,
        WorldNPCTemplate,
        WorldFaction,
        SessionNpcState,
        SessionEventState,
        SessionFactionState,
        SessionCampaignState,
        Campaign,
    )
    from sqlalchemy import select as _select

    # ── 步骤 1：加载世界地图，构建邻接图 ─────────────────────
    # WorldLocation 是地图上的节点，connections_json 描述各节点之间的连接
    locs = (await s.execute(
        _select(WorldLocation).where(WorldLocation.framework_id == framework_id)
    )).scalars().all()
    loc_dicts = [
        {"id": loc.id, "connections_json": loc.connections_json, "name": loc.name}
        for loc in locs
    ]
    # build_graph 把地点列表转成邻接字典，供 BFS 计算最短路径
    graph = build_graph(loc_dicts)

    # ── 步骤 2：加载所有世界事件 ─────────────────────────────
    # WorldEvent 是世界地图上「正在发酵」的事件（可能是战争、瘟疫、节日等）
    events = (await s.execute(
        _select(WorldEvent).where(WorldEvent.framework_id == framework_id)
    )).scalars().all()

    # ── 步骤 3：过滤已完成/已触发的事件 ──────────────────────
    # SessionEventState 记录了这个存档里每个事件的状态
    # 已触发或完成的事件不再需要 Director 推进
    ev_states_rows = (await s.execute(
        _select(SessionEventState).where(SessionEventState.session_id == session_id)
    )).scalars().all()
    done_event_ids = {
        es.event_id for es in ev_states_rows
        if es.status in ("triggered", "completed")
    }
    # 已经以谣言形式传递过的事件 ID 集合
    rumor_event_ids = {
        es.event_id for es in ev_states_rows if es.rumor_delivered
    }
    # 上次传递谣言是哪个回合（用于计算冷却期）
    last_rumor_turns = {es.event_id: es.rumor_delivered_turn for es in ev_states_rows}

    # ── 步骤 4：加载 NPC 状态，用于主动联系检查 ──────────────
    # JOIN 两张表：SessionNpcState（存档状态）+ WorldNPCTemplate（模板数据）
    npc_states_rows = (await s.execute(
        _select(SessionNpcState, WorldNPCTemplate)
        .join(WorldNPCTemplate, SessionNpcState.npc_template_id == WorldNPCTemplate.id)
        .where(SessionNpcState.session_id == session_id)
    )).all()
    # 收集同伴 NPC 的模板 ID（同伴在事件评分中有加成）
    companion_npc_ids = {
        row.SessionNpcState.npc_template_id
        for row in npc_states_rows
        if row.SessionNpcState.is_companion
    }
    # 把 ORM 对象转成普通字典，方便传给 check_npc_proactive_contact
    npc_state_dicts = [
        {
            "npc_template_id": row.SessionNpcState.npc_template_id,
            "favor": row.SessionNpcState.favor,
            "current_location_id": row.SessionNpcState.current_location_id,
            "last_contact_turn": row.SessionNpcState.last_contact_turn,
            "contact_favor_threshold": row.WorldNPCTemplate.contact_favor_threshold,
            "contact_cooldown_turns": row.WorldNPCTemplate.contact_cooldown_turns,
            "is_alive": row.SessionNpcState.is_alive,
            "is_companion": row.SessionNpcState.is_companion,
            "name": row.WorldNPCTemplate.name,
        }
        for row in npc_states_rows
    ]

    # ── 步骤 5：加载派系紧张度 ────────────────────────────────
    # 派系（Faction）是世界里的势力（如帝国、盗贼公会等）
    # 紧张度（tension）高说明派系间快要爆发冲突，Director 可能推进相关事件
    faction_states = (await s.execute(
        _select(SessionFactionState, WorldFaction)
        .join(WorldFaction, SessionFactionState.faction_id == WorldFaction.id)
        .where(SessionFactionState.session_id == session_id)
    )).all()
    faction_tensions = [
        {"name": row.WorldFaction.name, "tension": row.SessionFactionState.tension}
        for row in faction_states
        if row.SessionFactionState.tension > 0  # 只关心有紧张度的派系
    ]

    # ── 步骤 6：对每个事件评分，分类为候选事件或谣言 ──────────
    candidate_events = []  # 近处可直接推进的事件
    rumor_events = []      # 远处适合作为谣言传递的事件
    for ev in events:
        if ev.id in done_event_ids:
            continue  # 跳过已完成的事件

        # 计算事件发生地点到玩家当前位置的距离（BFS 跳数）
        try:
            # scope_type == "location" 说明事件有具体发生地点
            scope_loc_id = int(ev.scope_ref) if ev.scope_type == "location" else None
        except (ValueError, TypeError):
            scope_loc_id = None
        # bfs_distance 在地图图结构上做 BFS 搜索，返回最短跳数
        dist = bfs_distance(graph, pc_location_id, scope_loc_id) if scope_loc_id else 0

        # 计算事件得分
        sc = score_event(
            {"id": ev.id, "importance": ev.importance, "scope_ref": ev.scope_ref,
             "scope_type": ev.scope_type},
            pc_location_id=pc_location_id,
            distance=dist,
            companion_npc_ids=companion_npc_ids,
            faction_rep_npcs=set(),  # 暂时传空集合，未来扩展
        )
        if sc > 0:
            # 评分 > 0 → 近处事件，加入候选列表
            candidate_events.append({
                "id": ev.id, "name": ev.name, "score": sc,
                "importance": ev.importance, "summary_md": ev.summary_md,
            })
        elif is_rumor_eligible(
            {"importance": ev.importance},
            distance=dist,
            delivered=ev.id in rumor_event_ids,
            turns_since_last=current_turn - last_rumor_turns.get(ev.id, 0),
        ):
            # 评分 = 0 但符合谣言条件 → 加入谣言列表
            rumor_events.append({
                "id": ev.id, "name": ev.name,
                "importance": ev.importance, "summary_md": ev.summary_md,
            })

    # 按分数降序排列，只取前 5 个候选事件（防止 prompt 太长）
    candidate_events.sort(key=lambda e: e["score"], reverse=True)
    candidate_events = candidate_events[:5]

    # ── 步骤 7：检查 NPC 主动联系 ────────────────────────────
    proactive = check_npc_proactive_contact(
        npc_state_dicts, pc_location_id=pc_location_id, current_turn=current_turn
    )
    proactive_name = proactive["name"] if proactive else None  # 最合适的 NPC 名字（或 None）

    # ── 步骤 8：加载战役阶段（如果有）──────────────────────────
    # Campaign 是一系列有顺序的大事件（如「主线任务链」）
    # SessionCampaignState 记录当前进度到哪个阶段了
    campaign_phase_str: str | None = None
    camp_state = await s.get(SessionCampaignState, session_id)
    if camp_state and camp_state.current_phase_id:
        camp_row = (await s.execute(
            _select(Campaign).where(Campaign.framework_id == framework_id)
        )).scalars().first()
        if camp_row:
            phases = json.loads(camp_row.phases_json or "[]")
            # 找到当前阶段的配置（按 phase_id 匹配）
            phase = next((p for p in phases if p["phase_id"] == camp_state.current_phase_id), None)
            if phase:
                triggered = json.loads(camp_state.triggered_key_events_json or "[]")
                # 格式：「阶段名（已触发关键事件数/总数）」
                campaign_phase_str = (
                    f"{phase['name']}（{len(triggered)}/{phase['required_count']} 关键事件）"
                )

    # ── 步骤 9：构建快照并调用 LLM ───────────────────────────
    # 把所有信息打包成字典，传给 prompt 模板函数
    snapshot = {
        "current_location": next((l["name"] for l in loc_dicts if l["id"] == pc_location_id), "未知"),
        "pc_summary": f"{character_name}",
        "companions": [n["name"] for n in npc_state_dicts if n["is_companion"]],
        "candidate_events": candidate_events,   # 近处可推进的事件（按分数排序）
        "rumor_events": rumor_events[:3],       # 最多 3 条谣言事件
        "proactive_npc": proactive_name,        # 想主动联系玩家的 NPC（或 None）
        "campaign_phase": campaign_phase_str,   # 当前战役阶段（或 None）
        "faction_tensions": faction_tensions,   # 派系紧张度列表
    }

    # 加载 Director 的历史对话（用于保持叙事连贯性）
    stream = await get_or_create_stream(s, session_id, STREAM_KIND_DIRECTOR, "")
    history = await load_history(s, stream.id, max_messages=DIRECTOR_HISTORY_MAX)
    # 把历史 + 快照拼成 LLM 消息列表
    msgs = build_open_world_director_messages(history, snapshot)

    # 调用 LLM 生成 plot_directive
    try:
        output, usage = await client.complete(msgs, _PARAMS)
    except Exception as exc:  # noqa: BLE001
        log.warning("open-world director: LLM call failed: %s", exc)
        return _FALLBACK_DIRECTIVE, 0, 0  # 出错时返回安全兜底指令

    text = (output or "").strip()
    if not text:
        return _FALLBACK_DIRECTIVE, 0, 0  # LLM 返回空内容，走兜底

    # 统计 token 用量
    tok_in = usage.input_tokens if usage else 0
    tok_out = usage.output_tokens if usage else 0

    # 把本回合的输入快照 + LLM 输出存入 AgentStream，
    # 这样下次 load_history 能读到，Director 保持记忆连贯
    snapshot_str = _json_snapshot(snapshot)
    await append_message(s, stream.id, current_turn, "user", snapshot_str, tokens_in=tok_in)
    await append_message(s, stream.id, current_turn, "assistant", text, tokens_out=tok_out)
    stream.last_run_turn = current_turn  # 更新 Director 上次运行的回合号
    return text, tok_in, tok_out


# ────────────────────────────────────────────────────────────
# 工具函数：把快照字典序列化为 JSON 字符串
# ────────────────────────────────────────────────────────────

def _json_snapshot(snapshot: dict) -> str:
    # ensure_ascii=False 保留中文字符（不转义为 \uXXXX）
    # indent=None 不格式化，节省存储空间
    return json.dumps(snapshot, ensure_ascii=False, indent=None)
