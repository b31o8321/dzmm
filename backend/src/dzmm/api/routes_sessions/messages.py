# ============================================================
# 消息历史 & 游戏状态查询接口
# ============================================================
# 【模块作用】
#   提供前端"重新加载页面后恢复数据"所需的两个 GET 接口：
#   - GET /sessions/{id}/messages → 完整消息历史（对话记录）
#   - GET /sessions/{id}/messages/{msg_id}/debug → 单条消息的调试详情
#   - GET /sessions/{id}/state → 当前游戏状态（属性、NPC、剧情线等）
#
# 【为什么需要这两个接口？】
#   前端是单页应用（SPA），刷新页面后内存状态会丢失。
#   所有游戏数据持久化在后端数据库，前端需要调用这些接口"重新水化"（rehydrate）
#   来恢复界面，就像 React 的 hydration 恢复服务端渲染的 HTML 状态。
# ============================================================
"""GET /messages and GET /state — frontend hydration on page reload."""
import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.api.routes_sessions._common import _parse_events_json, get_session_dep
from dzmm.db.models import (
    Character,
    CharState,
    Message as MessageRow,
    NPC,
    PlotThread,
    Session as GameSession,
)
from dzmm.engine.schema import parse_items, parse_skills

router = APIRouter(prefix="/sessions", tags=["sessions"])


# ── GET /sessions/{session_id}/messages ──────────────────────────────
@router.get("/{session_id}/messages")
async def get_messages(session_id: int, s: AsyncSession = Depends(get_session_dep)):
    """Return full message history for a session, ordered chronologically.
    Used by the frontend to rehydrate the conversation log on page reload."""
    sess = await s.get(GameSession, session_id)
    if sess is None:
        raise HTTPException(404, "session not found")

    # select(MessageRow) → 构建 SELECT * FROM messages
    # .where(...) → WHERE session_id = ?
    # .order_by(MessageRow.id) → ORDER BY id ASC（按插入顺序，即时间顺序）
    # .scalars() → 把结果从 Row 提取为 MessageRow 对象
    # .all() → 一次性加载所有结果到内存（消息量大时可考虑分页，但目前单存档消息量有限）
    rows = (
        await s.execute(
            select(MessageRow)
            .where(MessageRow.session_id == session_id)
            .order_by(MessageRow.id)
        )
    ).scalars().all()

    # 返回列表推导式构建的字典列表
    # 为什么不直接返回 ORM 对象？FastAPI 需要可序列化的 Python 原生类型（dict/list/str/int）
    return [
        {
            "id": m.id,
            "role": m.role,         # "user" 或 "assistant"
            "content": m.content,   # 消息正文（玩家行动 / GM 叙事）
            "turn": m.turn,         # 所属回合号
            "tokens_in": m.tokens_in,   # 本条消息消耗的输入 token 数（用于计费统计）
            "tokens_out": m.tokens_out, # 本条消息产生的输出 token 数
            "events": _parse_events_json(m.events_json),
            "diagnostics": _parse_events_json(m.diagnostics_json),
            # events_json：该回合解析到的结构化事件（state_change/dice 等），以 JSON 存储
            # _parse_events_json 安全地解析它，失败返回 []
        }
        for m in rows
    ]


# ── GET /sessions/{session_id}/messages/{msg_id}/debug ───────────────
@router.get("/{session_id}/messages/{msg_id}/debug")
async def get_message_debug(
    session_id: int,
    msg_id: int,
    s: AsyncSession = Depends(get_session_dep),
):
    # 获取单条消息的调试信息，主要是 prompt_json（发给 LLM 的完整提示词）
    # 这个接口只在 debug_mode 下由前端调用，普通玩法不使用
    msg = await s.get(MessageRow, msg_id)
    # 双重校验：消息存在 && 属于该存档（防止越权访问其他存档的消息）
    if msg is None or msg.session_id != session_id:
        raise HTTPException(404, "message not found")
    return {
        "id": msg.id,
        "turn": msg.turn,
        "prompt_json": msg.prompt_json or "",  # 发送给 LLM 的完整消息列表（JSON 格式）
        "content": msg.content,
        "tokens_in": msg.tokens_in,
        "tokens_out": msg.tokens_out,
        "diagnostics": _parse_events_json(msg.diagnostics_json),
    }


# ── GET /sessions/{session_id}/state ─────────────────────────────────
@router.get("/{session_id}/state")
async def get_state(session_id: int, s: AsyncSession = Depends(get_session_dep)):
    """Return current PC state, NPCs, and active plot threads.
    Used by the frontend to rehydrate the right-side StatePanel on reload."""
    sess = await s.get(GameSession, session_id)
    if sess is None:
        raise HTTPException(404, "session not found")

    # 查询角色状态（HP/San 等属性和背包物品）
    # scalar_one_or_none()：查询结果恰好有一行时返回它，没有时返回 None（不报错）
    cs = (
        await s.execute(select(CharState).where(CharState.session_id == session_id))
    ).scalar_one_or_none()
    stats: dict = {}
    inventory: list[str] = []
    if cs is not None:
        stats = json.loads(cs.stats_json or "{}")
        inventory = json.loads(cs.inventory_json or "[]")

    # All NPCs in the session — frontend renders met (last_seen_turn>0)
    # in full color and unmet (=0) in greyed "未登场" style. Avoids the
    # confusing empty-list early game while still distinguishing on-stage
    # NPCs visually.
    # 返回所有 NPC（不只是已出场的），前端根据 met 字段决定显示样式：
    # 已出场 → 正常彩色显示；未出场 → 灰色"未登场"显示
    npc_rows = (
        await s.execute(
            select(NPC)
            .where(NPC.session_id == session_id)
            .order_by(
                # 排序逻辑：已出场的排前面，按最近出场回合倒序；未出场的排后面
                # (NPC.last_seen_turn == 0).asc() → False(已出场)排前，True(未出场)排后
                (NPC.last_seen_turn == 0).asc(),
                NPC.last_seen_turn.desc(),  # 最近出场的排最前
                NPC.id.asc(),              # id 作为最终排序稳定键
            )
        )
    ).scalars().all()

    # 查询活跃的剧情线（已结束的不显示）
    thread_rows = (
        await s.execute(
            select(PlotThread)
            .where(
                PlotThread.session_id == session_id,
                PlotThread.status == "active",  # 只要活跃的剧情线
            )
            .order_by(PlotThread.importance.desc(), PlotThread.id.desc())
            # 按重要性倒序，同重要性的按 id 倒序（新线在前）
        )
    ).scalars().all()

    # 解析 PC 心情状态（存为 JSON 字符串）
    try:
        pc_mood = json.loads(sess.pc_mood_json or "{}")
        if not isinstance(pc_mood, dict):
            pc_mood = {}
    except (TypeError, ValueError):
        pc_mood = {}

    # 解析世界时间（天/时段/天气）
    try:
        world_time = json.loads(sess.world_time_json or "{}")
        if not isinstance(world_time, dict):
            world_time = {}
    except (TypeError, ValueError):
        world_time = {}
    # setdefault: 如果字典里没有该键，就设置默认值（不覆盖已有值）
    world_time.setdefault("day", 1)
    world_time.setdefault("period", "morning")
    world_time.setdefault("weather", "clear")

    # ── v0.15 — extended fields from Character + Session ───────────────────
    char = await s.get(Character, sess.character_id)

    # Attributes (D&D-style 6 stats from Character columns)
    attributes: dict = {}
    vitals: dict = {}
    skills: dict = {}
    inventory_v2: list = []
    equipment: dict = {}
    if char is not None:
        attributes = {
            "strength": char.strength,
            "dexterity": char.dexterity,
            "constitution": char.constitution,
            "intelligence": char.intelligence,
            "wisdom": char.wisdom,
            "charisma": char.charisma,
        }
        # Vitals: current from CharState, max from Character
        hp_current = int(stats.get("hp", stats.get("HP", char.max_hp)))
        san_current = int(stats.get("sanity", stats.get("san", char.max_sanity)))
        stamina_current = cs.stamina if cs is not None else char.max_stamina
        vitals = {
            "hp": hp_current,
            "max_hp": char.max_hp,
            "sanity": san_current,
            "max_sanity": char.max_sanity,
            "stamina": stamina_current,
            "max_stamina": char.max_stamina,
        }
        # Skills: parse from Character.skills_json
        skills = parse_skills(char.skills_json or "{}")
        # Inventory v2: structured items from Character.inventory_json
        items = parse_items(char.inventory_json or "[]")
        inventory_v2 = [
            {
                "name": it.name,
                "qty": it.qty,
                "item_type": it.item_type,
                "effects": [e.model_dump(exclude_none=True) for e in it.effects],
                "description": it.description,
            }
            for it in items
        ]
        # Equipment: slot→name dict from Character.equipment_json
        try:
            eq = json.loads(char.equipment_json or "{}")
            equipment = eq if isinstance(eq, dict) else {}
        except (TypeError, ValueError):
            equipment = {}

    # Recent resolutions: last 5 from Session.pending_resolutions_json
    try:
        all_resolutions = json.loads(sess.pending_resolutions_json or "[]")
        if not isinstance(all_resolutions, list):
            all_resolutions = []
        recent_resolutions = all_resolutions[-5:]
    except (TypeError, ValueError):
        recent_resolutions = []

    # Combat order from Session.combat_order_json
    try:
        combat_order = json.loads(sess.combat_order_json or "[]")
        if not isinstance(combat_order, list):
            combat_order = []
    except (TypeError, ValueError):
        combat_order = []

    return {
        "stats": stats,
        "inventory": inventory,
        "pc_mood": pc_mood,
        "world_time": world_time,
        # topology_warning_json：地图拓扑检测到的警告（如孤立地点、环路等）
        "topology_warnings": json.loads(sess.topology_warning_json or "[]"),
        "npcs": [
            {
                "name": n.name,
                "favor": n.favor,   # 好感度
                "state": n.state,   # 当前状态
                "met": n.last_seen_turn > 0,  # True = 已出场（玩家见过这个 NPC）
                # emotion_json 解析：如果字段为空则给空字典
                "emotion": json.loads(n.emotion_json or "{}") if n.emotion_json else {},
            }
            for n in npc_rows
        ],
        "threads": [
            {
                "type": t.type,           # 剧情线类型（main/side/faction 等）
                "description": t.description,
                "importance": t.importance,  # 重要性（0-10）
            }
            for t in thread_rows
        ],
        # v0.15 extended fields — optional; absent on old sessions where Character
        # row lacks the new columns (they all default so will be present).
        "attributes": attributes,
        "vitals": vitals,
        "skills": skills,
        "inventory_v2": inventory_v2,
        "equipment": equipment,
        "combat_order": combat_order,
        "recent_resolutions": recent_resolutions,
    }
