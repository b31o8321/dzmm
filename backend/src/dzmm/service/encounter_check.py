# ============================================================
# encounter_check.py — NPC 巧合遭遇检查（软验证）
# ============================================================
# 【什么是巧合遭遇（encounter_check）？】
#   "巧合遭遇"是跑团设计术语，指玩家在意想不到的地方遇到某个 NPC。
#   例如：玩家在码头，但平时住在城堡的贵族 NPC 突然出现。
#   如果不加解释，玩家会觉得很违和（"他怎么在这里？"）。
#
# 【这个文件解决什么问题？】
#   GM（AI）有时会"懒"——直接让一个 NPC 登场，却没有说明他为什么在这里。
#   这个模块在每回合结束后检查：
#   - 本回合新出现的 NPC，是否在他们的"常驻场所"之外出现？
#   - 如果是，GM 是否在近 2 回合内用 encounter_setup 事件铺垫过？
#   - 如果没有，就生成一个警告，注入下回合的 Prompt，要求 GM 补上说明。
#
# 【软验证的含义】
#   "软"= 不会中止当前回合的输出（不抛异常，不中断 SSE 流）。
#   警告会在下一回合开头注入 Prompt，GM 被"温和地提醒"补充合理解释。
#   这样既不破坏流畅性，又能维持世界的逻辑一致性。
#
# v0.10.5 实现说明
# ============================================================
from __future__ import annotations

import json
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.db.models import (
    Location,
    Message as MessageRow,
    NPC,
    Screenplay,
    Session as GameSession,
)
from dzmm.parsing.events import TagComplete  # 解析器输出的"完整标签"对象

log = logging.getLogger(__name__)


async def _pc_current_location(s: AsyncSession, session_id: int) -> str:
    # 查询 PC（玩家角色）当前所在的地点名称
    # Location 表中 is_current=True 的那一行就是当前位置
    cur = (await s.execute(
        select(Location).where(
            Location.session_id == session_id,
            Location.is_current == True,  # noqa: E712（SQLAlchemy 需要 == True，不能用 is True）
        )
    )).scalar_one_or_none()
    return cur.name if cur is not None else ""


async def _primary_location_of_npc(
    s: AsyncSession, session_id: int, npc_name: str,
) -> str:
    # 从当前活跃剧本的 main_characters 列表里读取这个 NPC 的"常驻场所"
    # 返回空字符串表示：剧本没有声明这个 NPC 的常驻场所（旧格式剧本）
    #
    # 【为什么存在这个字段？】
    #   main_characters 里每个角色可以有 primary_location 字段，
    #   例如：{"name": "老商人", "primary_location": "集市"}
    #   这是 v0.10.5 新增的字段，旧剧本没有，所以要做兼容性处理

    # 找到当前存档的最新活跃剧本
    sp = (await s.execute(
        select(Screenplay)
        .where(
            Screenplay.session_id == session_id,
            Screenplay.status == "active",
        )
        .order_by(Screenplay.version.desc())  # 取版本最高的（最新的）
    )).scalars().first()
    if sp is None:
        return ""

    try:
        chars = json.loads(sp.main_characters_json or "[]")
    except (TypeError, ValueError):
        return ""
    if not isinstance(chars, list):
        return ""

    # 在角色列表里找到这个 NPC，读取其 primary_location
    for c in chars:
        if isinstance(c, dict) and str(c.get("name", "")).strip() == npc_name:
            return str(c.get("primary_location", "")).strip()
    return ""  # 这个 NPC 不在 main_characters 列表里


async def _had_encounter_setup_recently(
    s: AsyncSession,
    session_id: int,
    current_turn: int,
    npc_name: str,
    lookback: int = 2,  # 往前看几回合
) -> bool:
    # 扫描最近 lookback 回合的助手消息，检查是否有针对此 NPC 的 encounter_setup 事件
    #
    # 【encounter_setup 是什么？】
    #   一种 plot_event 类型，GM 用它提前铺垫 NPC 出场的理由。
    #   例如：<plot_event type="encounter_setup" importance="2">
    #           老商人追踪货物线索来到港口
    #         </plot_event>
    #   有了这个铺垫，NPC 的出现就有了合理解释，玩家不会觉得突兀。

    rows = (await s.execute(
        select(MessageRow.events_json)
        .where(
            MessageRow.session_id == session_id,
            MessageRow.role == "assistant",
            MessageRow.turn >= max(1, current_turn - lookback),  # 只看最近几回合
            MessageRow.turn < current_turn,                       # 不包括当前回合
        )
    )).scalars().all()

    for raw in rows:
        if not raw:
            continue
        try:
            events = json.loads(raw)
        except (TypeError, ValueError):
            continue
        if not isinstance(events, list):
            continue
        for ev in events:
            if not isinstance(ev, dict):
                continue
            if ev.get("type") != "plot_event":
                continue  # 只关心 plot_event 类型
            payload = ev.get("payload") or {}
            if not isinstance(payload, dict):
                continue
            if (str(payload.get("type") or "")).strip() != "encounter_setup":
                continue  # 只关心 encounter_setup 子类型
            content = str(ev.get("content") or "")
            try:
                payload_str = json.dumps(payload, ensure_ascii=False)
            except (TypeError, ValueError):
                payload_str = ""
            # 宽松匹配：NPC 名字出现在 content 或 payload 任何地方即视为有铺垫
            if npc_name in content or npc_name in payload_str:
                return True
    return False  # 近期没有相关的 encounter_setup


async def check_encounter_warnings(
    s: AsyncSession,
    session_id: int,
    completed_tags: list[TagComplete],  # 本回合解析完成的所有 XML 标签
    current_turn: int,
) -> None:
    # 主入口：检查本回合是否有 NPC"凭空出场"，如有则生成警告
    #
    # 【工作流程】
    # 1. 从本回合的标签里收集涉及的 NPC 名字（say 说话者 + npc_update 提到的 NPC）
    # 2. 对每个名字检查：这是不是首次登场？（last_seen_turn == current_turn）
    # 3. 如果是首次登场：
    #    a. 是否在 NPC 的常驻场所？→ 合理，跳过
    #    b. 近 2 回合是否有 encounter_setup 铺垫？→ 合理，跳过
    #    c. 两者都没有 → 生成警告，写入 session.topology_warning_json
    # 4. 警告在下回合被 _build_key_facts 读取并注入 Prompt
    #
    # 软验证：永远不抛异常，内部错误只记日志

    sess = await s.get(GameSession, session_id)
    if sess is None:
        return

    # 收集本回合涉及的所有 NPC 名字
    candidate_names: set[str] = set()
    for tag in completed_tags or []:
        if tag is None:
            continue
        if tag.name == "say":
            # <say speaker="NPC名">...</say> 里的 speaker 属性
            speaker = str((tag.attrs or {}).get("speaker", "")).strip()
            if speaker:
                candidate_names.add(speaker)
        elif tag.name == "npc_update":
            # <npc_update name="NPC名">...</npc_update> 里的 name 属性
            name = str((tag.attrs or {}).get("name", "")).strip()
            if name and name.lower() != "none":
                candidate_names.add(name)
    if not candidate_names:
        return  # 本回合没有涉及任何 NPC，无需检查

    # 读取 PC 当前位置
    pc_loc = (await _pc_current_location(s, session_id)).strip()

    warnings: list[str] = []
    for name in candidate_names:
        # 查找这个 NPC 的数据库行
        npc = (await s.execute(
            select(NPC).where(
                NPC.session_id == session_id, NPC.name == name,
            )
        )).scalar_one_or_none()
        if npc is None:
            continue  # 数据库里没有这个 NPC（可能是新创建的但还没 flush），跳过

        # 首次登场判断：apply_tags 把 last_seen_turn 更新为 current_turn，
        # 如果值等于 current_turn，说明这是今天第一次出现（不一定是历史首次）
        if (npc.last_seen_turn or 0) != current_turn:
            continue  # 之前见过，不是首次，不需要 encounter 铺垫

        # 再验证"历史首次"：扫描之前的助手消息，看是否提到过这个 NPC
        prior_rows = (await s.execute(
            select(MessageRow.content, MessageRow.events_json)
            .where(
                MessageRow.session_id == session_id,
                MessageRow.role == "assistant",
                MessageRow.turn < current_turn,  # 不含当前回合
            )
        )).all()
        prior_appearance = False
        for content, events_json in prior_rows:
            # 宽松检查：NPC 名字在 content 或 events_json 任何地方出现即视为曾经登场
            if (content and name in content) or (events_json and name in events_json):
                prior_appearance = True
                break
        if prior_appearance:
            continue  # 之前的叙述里提到过，不是真正意义上的首次，放行

        # 查询这个 NPC 的常驻场所（来自剧本 main_characters）
        primary_loc = await _primary_location_of_npc(s, session_id, name)
        if not primary_loc:
            # 旧格式剧本没有 primary_location 字段，向后兼容：不警告
            continue

        if pc_loc and pc_loc == primary_loc:
            # PC 正好在 NPC 的常驻场所，自然相遇，合理，跳过
            continue

        if await _had_encounter_setup_recently(s, session_id, current_turn, name):
            # GM 已经在上一两回合做了铺垫，合理，跳过
            continue

        # 走到这里 = 首次登场 + 不在常驻场所 + 没有铺垫 → 生成警告
        warnings.append(
            f"⚠️ NPC 凭空出场：「{name}」是首次登场，但 PC 当前不在其常驻场所"
            f"「{primary_loc}」，且近 2 回合没有 encounter_setup 铺垫。"
            f"下回合开头**必须**先 emit "
            f"`<plot_event type=\"encounter_setup\" importance=\"2\">"
            f"{name} 出现的合理原因（追踪 / 巧遇 / 受邀 / 信件等）"
            f"</plot_event>` 补上语义。"
        )

    if not warnings:
        return  # 没有警告，直接返回

    # 把警告追加到 session.topology_warning_json（与拓扑越界警告共用同一个字段）
    # _build_key_facts 每回合会读取并清空这个列表，注入到 Prompt 里
    try:
        existing = json.loads(sess.topology_warning_json or "[]")
        if not isinstance(existing, list):
            existing = []
    except (TypeError, ValueError):
        existing = []
    existing.extend(warnings)
    # 保留最后 5 条（防止旧警告无限堆积）
    sess.topology_warning_json = json.dumps(existing[-5:], ensure_ascii=False)
