# ============================================================
# 调试链接口：每回合 LLM 调用链追踪
# ============================================================
# 【模块作用】
#   提供单个调试接口：
#   - GET /sessions/{id}/turns/{turn_num}/debug_chain
#
#   返回指定回合的完整 LLM 调用链，包括：
#   - 玩家行动
#   - Director Agent 的输入和输出（战略层）
#   - Scene Agent 的输入和输出（叙事层）
#   - 每个 NPC Actor 的输入和输出（角色扮演层）
#   - 该回合产生的所有结构化事件（state_change/dice 等）
#   - token 消耗统计
#
# 【多 Agent 架构背景（v0.10）】
#   这个游戏使用多 Agent 框架，每回合有多个 LLM 角色协作：
#   1. Director（导演）：分析当前剧情走向，给出本回合叙事指令
#   2. Scene（场景作者）：根据 Director 指令生成实际叙事文字和游戏事件标签
#   3. NPC Actors（NPC 演员）：各个 NPC 的独立 Agent，生成对白/行动
#   这个接口让开发者能看到每个 Agent 到底收到了什么、输出了什么，
#   方便排查 GM 行为异常（比如 NPC 性格突变、剧情不连贯等问题）。
# ============================================================
"""Debug chain endpoint — per-turn LLM call trace for debug mode.

GET /sessions/{session_id}/turns/{turn_num}/debug_chain
Returns the full agent chain for a turn: Director (input+output),
Scene (input+output), NPC actors (input+output), and applied events.
"""
import json
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.api.routes_sessions._common import get_session_dep
from dzmm.db.models import AgentMessage, AgentStream, Message as MessageRow, Session as GameSession

router = APIRouter(prefix="/sessions", tags=["sessions"])


# ── GET /sessions/{session_id}/turns/{turn_num}/debug_chain ──────────
@router.get("/{session_id}/turns/{turn_num}/debug_chain")
async def get_turn_debug_chain(
    session_id: int,
    turn_num: int,       # URL 路径参数：指定要查看哪一回合
    s: AsyncSession = Depends(get_session_dep),
):
    """Return the complete LLM call chain for a given turn in debug format.

    Covers: player action, Director snapshot+directive, Scene prompt+output,
    each NPC actor snapshot+response, and the applied state events.
    """
    sess = await s.get(GameSession, session_id)
    if sess is None:
        raise HTTPException(404, "session not found")

    # ── 查询该回合的玩家消息和 GM 消息 ──────────────────────────────
    msg_rows = (await s.execute(
        select(MessageRow)
        .where(
            MessageRow.session_id == session_id,
            MessageRow.turn == turn_num,  # 精确匹配回合号
        )
        .order_by(MessageRow.id)  # 按时间顺序（id 是自增主键，顺序等于时间顺序）
    )).scalars().all()

    # 遍历消息行，提取玩家行动、GM 输出和结构化事件
    player_action = ""
    gm_output = ""
    applied_events: list[dict] = []
    tok_in_total = 0    # 该回合总输入 token（可能来自多个 Agent）
    tok_out_total = 0   # 该回合总输出 token
    for m in msg_rows:
        if m.role == "user":
            player_action = m.content or ""
        elif m.role == "assistant":
            gm_output = m.content or ""
            tok_in_total += m.tokens_in or 0   # or 0：None 时当 0 处理
            tok_out_total += m.tokens_out or 0
            if m.events_json:
                try:
                    # events_json 存储该回合触发的游戏事件列表（JSON 字符串）
                    applied_events = json.loads(m.events_json)
                except (ValueError, TypeError):
                    applied_events = []

    # ── 加载 Agent 流（每个 Agent 维护一个持续的对话历史流）───────────
    # AgentStream 记录：kind（gm_director/scene/npc）+ ref（NPC 名字 或 空）
    # AgentMessage 记录：每一轮对话中发给该 Agent 的消息和它的回复
    streams = (await s.execute(
        select(AgentStream).where(AgentStream.session_id == session_id)
    )).scalars().all()
    # 构建 "kind:ref" → AgentStream 的查找字典，方便后面按名字查找
    stream_map: dict[str, AgentStream] = {f"{st.kind}:{st.ref}": st for st in streams}

    # 辅助函数：查询某个 Agent 在指定回合的消息历史
    async def get_turn_messages(kind: str, ref: str = "") -> list[dict]:
        # kind="gm_director", ref="" → Director Agent 的消息
        # kind="scene", ref="" → Scene Agent 的消息
        # kind="npc", ref="NPC名字" → 特定 NPC Actor 的消息
        key = f"{kind}:{ref}"
        st = stream_map.get(key)
        if st is None:
            return []  # 该 Agent 在本存档中没有历史
        rows = (await s.execute(
            select(AgentMessage)
            .where(
                AgentMessage.stream_id == st.id,
                AgentMessage.turn == turn_num,  # 只取指定回合的消息
            )
            .order_by(AgentMessage.id)
        )).scalars().all()
        return [
            {
                "role": r.role,          # "user"（发给 Agent 的）/ "assistant"（Agent 的回复）
                "content": r.content,    # 消息内容（可能很长，包含完整上下文）
                "tokens_in": r.tokens_in,
                "tokens_out": r.tokens_out,
                "is_summary": r.is_summary,  # True = 这是历史压缩后的摘要行
            }
            for r in rows
        ]

    # 查询 Director 和 Scene Agent 的消息
    director_msgs = await get_turn_messages("gm_director")
    scene_msgs = await get_turn_messages("scene")

    # NPC actors: all streams with kind="npc"
    # 找出所有 NPC Actor 的消息（一个 NPC 对应一个 AgentStream）
    npc_actors = []
    for st in streams:
        if st.kind != "npc" or not st.ref:
            continue  # 只处理 NPC 类型的流，且 ref 不为空（ref = NPC 名字）
        rows = (await s.execute(
            select(AgentMessage)
            .where(
                AgentMessage.stream_id == st.id,
                AgentMessage.turn == turn_num,
            )
            .order_by(AgentMessage.id)
        )).scalars().all()
        if rows:
            # 只有该回合有消息的 NPC 才加入列表（不是每个 NPC 每回合都会被激活）
            npc_actors.append({
                "name": st.ref,   # NPC 名字（存在 AgentStream.ref 字段里）
                "messages": [
                    {
                        "role": r.role,
                        "content": r.content,
                        "tokens_in": r.tokens_in,
                        "tokens_out": r.tokens_out,
                    }
                    for r in rows
                ],
            })

    # 返回完整调试信息：按 Agent 层次组织
    return {
        "turn": turn_num,
        "player_action": player_action,    # 玩家输入
        "gm_output": gm_output,            # GM 最终输出（呈现给玩家的叙事）
        "tokens_in_total": tok_in_total,   # 本回合总消耗
        "tokens_out_total": tok_out_total,
        "director": director_msgs,         # Director Agent 的调用链
        "scene": scene_msgs,               # Scene Agent 的调用链
        "npcs": npc_actors,                # 各 NPC Actor 的调用链
        "applied_events": applied_events,  # 本回合触发的游戏事件列表
    }
