# ============================================================
# turn_snapshot.py — 回合状态快照与回滚（v0.10.5）
# ============================================================
# 【什么是回合快照（turn snapshot）？】
#   每个回合开始前，把游戏当前的全部可变状态序列化成一个 JSON 字典，
#   存储在这回合的 MessageRow.snapshot_json 字段里。
#
#   如果玩家想"撤销上一回合"（删除最后一回合），就读出快照，
#   把所有数据恢复到快照时的状态，并删除本回合新建的行。
#
# 【为什么需要快照？】
#   一回合里 GM 可能创建新 NPC、改变地点、调整好感度、完成剧情事件……
#   如果只是删除 Message 行，数据库里的状态改动仍然存在。
#   快照保证了"回滚"能真正还原到回合开始前的状态，
#   让玩家可以"读档重来"（类似游戏存档功能）。
#
# 【两个核心函数】
#   take_snapshot: 回合开始时调用，拍一张"状态快照"
#   restore_snapshot: 回滚时调用，按快照还原状态
# ============================================================
from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.db.models import (
    CharState,      # 角色状态（HP、道具栏等）
    Faction,        # 派系（与玩家的声望关系）
    HiddenEvent,    # 隐藏事件（条件满足时触发）
    Location,       # 地点
    LocationEdge,   # 地点之间的连接（地图边）
    NPC,            # NPC
    PCGoal,         # PC 目标
    PlotThread,     # 剧情线索
    Screenplay,     # 剧本大纲
    Session as GameSession,  # 游戏存档
)

log = logging.getLogger(__name__)


async def take_snapshot(s: AsyncSession, session_id: int) -> dict[str, Any]:
    # 把这个存档当前的全部可变状态序列化为一个 JSON 可序列化的字典
    # 在每回合开始时（LLM 调用之前）调用，存入 MessageRow.snapshot_json
    #
    # 【什么算"可变状态"？】
    #   任何在一回合内可能被 GM 输出（apply_tags）修改的字段，
    #   例如：NPC 好感度、地点是否是当前位置、剧情线索的状态、PC 的 HP 等

    # 读取游戏存档行（包含 doom_score、回合数等全局状态）
    sess = await s.get(GameSession, session_id)
    # 读取角色状态（HP、背包等）
    cs = (await s.execute(
        select(CharState).where(CharState.session_id == session_id)
    )).scalar_one_or_none()
    # 读取当前活跃剧本（按版本降序取最新的）
    sp = (await s.execute(
        select(Screenplay).where(
            Screenplay.session_id == session_id,
            Screenplay.status == "active",
        ).order_by(Screenplay.version.desc())
    )).scalars().first()
    # 读取所有 NPC、地点、地图边、隐藏事件、派系、剧情线索、PC 目标
    npcs = (await s.execute(
        select(NPC).where(NPC.session_id == session_id)
    )).scalars().all()
    locations = (await s.execute(
        select(Location).where(Location.session_id == session_id)
    )).scalars().all()
    edges = (await s.execute(
        select(LocationEdge).where(LocationEdge.session_id == session_id)
    )).scalars().all()
    hidden = (await s.execute(
        select(HiddenEvent).where(HiddenEvent.session_id == session_id)
    )).scalars().all()
    factions = (await s.execute(
        select(Faction).where(Faction.session_id == session_id)
    )).scalars().all()
    threads = (await s.execute(
        select(PlotThread).where(PlotThread.session_id == session_id)
    )).scalars().all()
    goals = (await s.execute(
        select(PCGoal).where(PCGoal.session_id == session_id)
    )).scalars().all()

    # 把所有数据打包成一个大字典，保存需要回滚的字段值和当前存在的行 ID
    return {
        # 游戏存档的全局状态
        "session": {
            "doom_score": sess.doom_score if sess else 0,
            "scene_turn_count": sess.scene_turn_count if sess else 0,
            "turn_count": sess.turn_count if sess else 0,
            "world_time_json": (sess.world_time_json if sess else "") or "",
            "pc_mood_json": (sess.pc_mood_json if sess else "") or "",
            "recall_pending_json": (sess.recall_pending_json if sess else "") or "",
            "topology_warning_json": (sess.topology_warning_json if sess else "") or "",
        },
        # 角色状态（HP、背包）
        "char_state": {
            "stats_json": cs.stats_json or "" if cs else "",
            "inventory_json": cs.inventory_json or "" if cs else "",
        } if cs else None,
        # 剧本大纲（章节进度、已完成事件）
        "screenplay": {
            "id": sp.id, "current_chapter": sp.current_chapter,
            "completed_events_json": sp.completed_events_json or "",
            "chapters_json": sp.chapters_json or "",
            "status": sp.status,
        } if sp else None,
        # 所有 NPC 的可变字段 + 当前所有 NPC 的 ID 列表
        "npcs": [
            {
                "id": n.id, "favor": n.favor, "emotion_json": n.emotion_json or "",
                "affinity_json": n.affinity_json or "", "state": n.state or "",
                "last_seen_turn": n.last_seen_turn,
                "current_location": n.current_location or "",
                "last_initiative_turn": n.last_initiative_turn,
                "notes_json": n.notes_json or "",
                "revealed_json": n.revealed_json or "",
                "faction_id": n.faction_id,
            } for n in npcs
        ],
        # 快照时刻所有 NPC 的 ID（用于判断哪些是本回合新建的）
        "npc_ids": sorted(n.id for n in npcs),
        # 地点的可变字段 + ID 列表
        "locations": [
            {
                "id": loc.id, "is_current": bool(loc.is_current),
                "last_visited_turn": loc.last_visited_turn,
                "items_json": loc.items_json or "",
            } for loc in locations
        ],
        "location_ids": sorted(loc.id for loc in locations),
        # 地图边只需要 ID（边本身的属性不可变）
        "location_edge_ids": sorted(e.id for e in edges),
        # 隐藏事件的状态字段
        "hidden_events": [
            {"id": h.id, "status": h.status} for h in hidden
        ],
        "hidden_event_ids": sorted(h.id for h in hidden),
        # 派系的声望值
        "factions": [
            {"id": f.id, "pc_reputation": f.pc_reputation} for f in factions
        ],
        "faction_ids": sorted(f.id for f in factions),
        # 剧情线索的状态
        "plot_threads": [
            {"id": t.id, "status": t.status} for t in threads
        ],
        "plot_thread_ids": sorted(t.id for t in threads),
        # PC 目标的状态
        "pc_goals": [
            {"id": g.id, "status": g.status} for g in goals
        ],
        "pc_goal_ids": sorted(g.id for g in goals),
    }


async def restore_snapshot(
    s: AsyncSession, session_id: int, snap: dict[str, Any],
) -> None:
    # 按快照还原状态，用于"删除最后一回合"的回滚操作
    #
    # 三步操作：
    # 1. 恢复快照时刻已存在的行的可变字段（例如把 NPC 好感度改回去）
    # 2. 删除快照之后新建的行（例如本回合新创建的 NPC）
    # 3. 恢复快照时刻的状态字段（例如把 "completed" 的剧情线索改回 "active"）
    if not snap:
        return  # 空快照，无法还原

    # ── 还原游戏存档全局状态 ──────────────────────────────────────────────
    sess = await s.get(GameSession, session_id)
    if sess is not None and snap.get("session"):
        ss = snap["session"]
        sess.doom_score = ss.get("doom_score", sess.doom_score)
        sess.scene_turn_count = ss.get("scene_turn_count", sess.scene_turn_count)
        sess.turn_count = ss.get("turn_count", sess.turn_count)
        sess.world_time_json = ss.get("world_time_json", sess.world_time_json)
        sess.pc_mood_json = ss.get("pc_mood_json", sess.pc_mood_json)
        sess.recall_pending_json = ss.get("recall_pending_json", sess.recall_pending_json)
        sess.topology_warning_json = ss.get("topology_warning_json", sess.topology_warning_json)

    # ── 还原角色状态（HP、背包）────────────────────────────────────────────
    if snap.get("char_state"):
        cs = (await s.execute(
            select(CharState).where(CharState.session_id == session_id)
        )).scalar_one_or_none()
        if cs is not None:
            cs.stats_json = snap["char_state"].get("stats_json", cs.stats_json)
            cs.inventory_json = snap["char_state"].get("inventory_json", cs.inventory_json)

    # ── 还原剧本进度 ──────────────────────────────────────────────────────
    if snap.get("screenplay"):
        sp_snap = snap["screenplay"]
        sp = await s.get(Screenplay, sp_snap["id"])  # 按快照里存的 ID 找到对应行
        if sp is not None:
            sp.current_chapter = sp_snap.get("current_chapter", sp.current_chapter)
            sp.completed_events_json = sp_snap.get("completed_events_json", sp.completed_events_json)
            sp.chapters_json = sp_snap.get("chapters_json", sp.chapters_json)
            sp.status = sp_snap.get("status", sp.status)

    # ── 还原 NPC + 删除本回合新创建的 NPC ────────────────────────────────
    # 按 ID 建立快照中 NPC 数据的索引，方便查找
    snap_npcs_by_id = {n["id"]: n for n in snap.get("npcs", [])}
    # 快照时存在的所有 NPC ID 集合
    snap_npc_ids = set(snap.get("npc_ids", []))
    # 读取当前所有 NPC
    current_npcs = (await s.execute(
        select(NPC).where(NPC.session_id == session_id)
    )).scalars().all()
    for n in current_npcs:
        if n.id in snap_npcs_by_id:
            # 这个 NPC 在快照时就存在，恢复其可变字段
            d = snap_npcs_by_id[n.id]
            n.favor = d.get("favor", n.favor)
            n.emotion_json = d.get("emotion_json", n.emotion_json)
            n.affinity_json = d.get("affinity_json", n.affinity_json)
            n.state = d.get("state", n.state)
            n.last_seen_turn = d.get("last_seen_turn", n.last_seen_turn)
            n.current_location = d.get("current_location", n.current_location)
            n.last_initiative_turn = d.get("last_initiative_turn", n.last_initiative_turn)
            n.notes_json = d.get("notes_json", n.notes_json)
            n.revealed_json = d.get("revealed_json", n.revealed_json)
            n.faction_id = d.get("faction_id", n.faction_id)
    # 找出快照时不存在的 NPC（即本回合新建的），批量删除
    new_npc_ids = [n.id for n in current_npcs if n.id not in snap_npc_ids]
    if new_npc_ids:
        await s.execute(delete(NPC).where(NPC.id.in_(new_npc_ids)))

    # ── 还原地点 + 删除本回合新建的地点 ──────────────────────────────────
    snap_locs_by_id = {l["id"]: l for l in snap.get("locations", [])}
    snap_loc_ids = set(snap.get("location_ids", []))
    current_locs = (await s.execute(
        select(Location).where(Location.session_id == session_id)
    )).scalars().all()
    for loc in current_locs:
        if loc.id in snap_locs_by_id:
            d = snap_locs_by_id[loc.id]
            loc.is_current = d.get("is_current", loc.is_current)
            loc.last_visited_turn = d.get("last_visited_turn", loc.last_visited_turn)
            loc.items_json = d.get("items_json", loc.items_json)
    # 找出本回合新建的地点
    new_loc_ids = [loc.id for loc in current_locs if loc.id not in snap_loc_ids]
    if new_loc_ids:
        # 必须先删除指向这些地点的 LocationEdge（外键约束）
        await s.execute(delete(LocationEdge).where(
            (LocationEdge.from_loc_id.in_(new_loc_ids)) | (LocationEdge.to_loc_id.in_(new_loc_ids))
        ))
        await s.execute(delete(Location).where(Location.id.in_(new_loc_ids)))

    # ── 删除本回合新建的地图边 ────────────────────────────────────────────
    snap_edge_ids = set(snap.get("location_edge_ids", []))
    current_edge_ids = (await s.execute(
        select(LocationEdge.id).where(LocationEdge.session_id == session_id)
    )).scalars().all()
    new_edge_ids = [eid for eid in current_edge_ids if eid not in snap_edge_ids]
    if new_edge_ids:
        await s.execute(delete(LocationEdge).where(LocationEdge.id.in_(new_edge_ids)))

    # ── 还原隐藏事件状态 + 删除本回合新建的隐藏事件 ──────────────────────
    snap_hidden_by_id = {h["id"]: h for h in snap.get("hidden_events", [])}
    snap_hidden_ids = set(snap.get("hidden_event_ids", []))
    current_hidden = (await s.execute(
        select(HiddenEvent).where(HiddenEvent.session_id == session_id)
    )).scalars().all()
    for h in current_hidden:
        if h.id in snap_hidden_by_id:
            h.status = snap_hidden_by_id[h.id].get("status", h.status)
    new_hidden_ids = [h.id for h in current_hidden if h.id not in snap_hidden_ids]
    if new_hidden_ids:
        await s.execute(delete(HiddenEvent).where(HiddenEvent.id.in_(new_hidden_ids)))

    # ── 还原派系声望 + 删除本回合新建的派系 ──────────────────────────────
    snap_facs_by_id = {f["id"]: f for f in snap.get("factions", [])}
    snap_fac_ids = set(snap.get("faction_ids", []))
    current_factions = (await s.execute(
        select(Faction).where(Faction.session_id == session_id)
    )).scalars().all()
    for f in current_factions:
        if f.id in snap_facs_by_id:
            f.pc_reputation = snap_facs_by_id[f.id].get("pc_reputation", f.pc_reputation)
    new_fac_ids = [f.id for f in current_factions if f.id not in snap_fac_ids]
    if new_fac_ids:
        await s.execute(delete(Faction).where(Faction.id.in_(new_fac_ids)))

    # ── 还原剧情线索状态 + 删除本回合新建的剧情线索 ──────────────────────
    snap_threads_by_id = {t["id"]: t for t in snap.get("plot_threads", [])}
    snap_thread_ids = set(snap.get("plot_thread_ids", []))
    current_threads = (await s.execute(
        select(PlotThread).where(PlotThread.session_id == session_id)
    )).scalars().all()
    for t in current_threads:
        if t.id in snap_threads_by_id:
            t.status = snap_threads_by_id[t.id].get("status", t.status)
    new_thread_ids = [t.id for t in current_threads if t.id not in snap_thread_ids]
    if new_thread_ids:
        await s.execute(delete(PlotThread).where(PlotThread.id.in_(new_thread_ids)))

    # ── 还原 PC 目标状态 + 删除本回合新建的目标 ──────────────────────────
    snap_goals_by_id = {g["id"]: g for g in snap.get("pc_goals", [])}
    snap_goal_ids = set(snap.get("pc_goal_ids", []))
    current_goals = (await s.execute(
        select(PCGoal).where(PCGoal.session_id == session_id)
    )).scalars().all()
    for g in current_goals:
        if g.id in snap_goals_by_id:
            g.status = snap_goals_by_id[g.id].get("status", g.status)
    new_goal_ids = [g.id for g in current_goals if g.id not in snap_goal_ids]
    if new_goal_ids:
        await s.execute(delete(PCGoal).where(PCGoal.id.in_(new_goal_ids)))


def serialize_snapshot(snap: dict[str, Any]) -> str:
    # 把快照字典序列化成 JSON 字符串，存入数据库
    # ensure_ascii=False：中文字符直接写入，不转义
    return json.dumps(snap, ensure_ascii=False)


def deserialize_snapshot(raw: str) -> dict[str, Any]:
    # 从数据库读取的 JSON 字符串还原成 Python 字典
    # 如果为空或 JSON 损坏，返回空字典（调用方需检查 if not snap）
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return {}
