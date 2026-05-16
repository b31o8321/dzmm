# ============================================================
# orchestrator.py — 每回合的「总调度器」
#
# 【orchestrator 在整个系统里的角色】
# 每当玩家输入一条行动，游戏后端就调用 run_turn_v10()。
# 这个函数像一个乐队指挥，按顺序做三件事：
#   1. 决定本回合要不要让 Director（剧本导演）出手更新叙事方向
#   2. 调用 Scene（场景 agent）生成玩家看到的叙事文本
#   3. 让每个「在场 NPC」的 actor agent 对玩家行动作出反应
# 最终把所有 agent 输出合并成一条流（Stream），通过 SSE 实时推送给前端。
#
# 【为什么要判断 framework_id？】
# 系统支持两种剧本模式：
#   - 剧本章节模式（screenplay）：有明确章节/主线事件，用 run_director()
#   - 开放世界模式（open-world）：基于地图地点和世界事件，用 run_open_world_director()
# sess.framework_id 不为空时表示「开放世界」，调度器据此选择正确的 Director。
# ============================================================
"""v0.10 per-turn orchestrator.

Sequence per turn:
  1. Build session snapshot for Director triggers
  2. If Director should run -> run Director sync; else reuse last directive
  3. Stream Scene; collect narrative as it arrives
  4. After Scene completes, fan-out NPC actors in parallel; yield their tags
"""
from __future__ import annotations

import asyncio
import json as _json
import logging
import re
from collections.abc import AsyncIterator  # 用于类型注解：异步生成器迭代器

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession  # 异步数据库会话，不会阻塞事件循环

from dzmm.db.models import (
    AgentMessage,
    AgentStream,
    Character,
    CharState,
    HiddenEvent,
    Message as MessageRow,
    NPC,
    Screenplay,
    Session as GameSession,
    SessionCampaignState,
    SessionFactionState,
    SessionNpcState,
    WorldFaction,
    WorldNPCTemplate,
)
from dzmm.models.client import GenerationParams, Message, ModelClient
from dzmm.parsing.events import NarrativeDelta, ParseEvent, TagComplete, UsageSummary
from dzmm.service.agents.director import (
    STREAM_KIND_DIRECTOR,
    run_director,
)
from dzmm.service.agents.director_open_world import run_open_world_director
from dzmm.service.agents.npc_actor import run_npc_actor
from dzmm.service.agents.scene import run_scene
from dzmm.service.agents.streams import append_message, get_or_create_stream

STREAM_KIND_SCENE = "scene"
from dzmm.service.agents.triggers import should_run_director  # 判断本回合是否触发 Director

log = logging.getLogger(__name__)

# 同一回合最多并行运行几个 NPC actor（防止 token 爆炸）
NPC_MAX_PARALLEL = 4

# 用于剥离 XML 标签的正则，如 <say speaker="X">...</say> → 纯文字
_TAG_STRIP_RE = re.compile(r"<[^>]+>")


# ────────────────────────────────────────────────────────────
# 辅助函数：格式化最近对话，供 NPC actor 阅读
# ────────────────────────────────────────────────────────────

def _format_recent_dialogue(recent_messages: list[Message], max_turns: int = 4) -> str:
    # 把最近 N 轮（user/assistant 各算一条）拼成可读文字
    # NPC actor 需要知道「刚刚发生了什么」，但不需要完整历史
    # 剥去 XML 标签，截取前 200 字，避免 prompt 太长
    """Compact last N user/assistant pairs into NPC-readable lines.
    Strips XML tags so each entry is plain prose, capped at 200 chars."""
    if not recent_messages:
        return ""
    # 取最后 max_turns*2 条消息（每轮包含一问一答）
    take = recent_messages[-(max_turns * 2):]
    lines: list[str] = []
    for m in take:
        # role == "user" 是玩家说的话，否则是 GM（Scene agent）的叙事
        prefix = "玩家" if m.role == "user" else "GM"
        # 去除 XML 标签，合并多余空格，截到 200 字
        text = _TAG_STRIP_RE.sub(" ", m.content)
        text = " ".join(text.split())[:200]
        if text:
            lines.append(f"[{prefix}] {text}")
    return "\n".join(lines)


# ────────────────────────────────────────────────────────────
# 辅助函数：为每个 NPC 构建「与玩家的关系摘要」
# ────────────────────────────────────────────────────────────

async def _format_npc_relationship(
    s: AsyncSession, session_id: int, npc, recent_messages: list[Message],
) -> str:
    # 这个摘要会放入 NPC actor 的 prompt，让 NPC「记得」自己和玩家的关系
    # 包含：好感度数值+文字标签、多维亲密度（信任/恋慕等）、近几轮的具体互动
    """Build a per-NPC relationship snapshot for the actor's prompt.

    Includes:
    - current favor (+/- with label: 友好/中立/冷淡/敌对)
    - affinity dimensions (信任/羁绊/恋慕 etc., if any)
    - last 2-3 PC↔this-NPC exchanges (extracted from recent assistant
      messages filtered by speaker=this NPC, paired with adjacent PC user
      messages)
    """
    parts: list[str] = []

    # ── 好感度（favor）转文字标签 ──────────────────────────────
    # favor 是整数，代表 NPC 对玩家的总体态度，正值友好，负值敌对
    favor = int(getattr(npc, "favor", 0) or 0)
    if favor >= 30:
        favor_label = "深度信任 / 友好"
    elif favor >= 10:
        favor_label = "正面 / 友善"
    elif favor >= -9:
        favor_label = "中立 / 一般认识"
    elif favor >= -29:
        favor_label = "冷淡 / 警惕"
    else:
        favor_label = "敌对"
    parts.append(f"- favor = {favor:+d}（{favor_label}）")

    # ── 多维亲密度（affinity_json）─────────────────────────────
    # affinity_json 是 JSON 字符串，如 {"信任": 20, "恋慕": 5}
    # 某些剧本会定义多个维度，比单一 favor 更细腻
    try:
        aff = _json.loads(getattr(npc, "affinity_json", None) or "{}")
        if isinstance(aff, dict) and aff:
            aff_str = " / ".join(
                f"{k}:{int(v):+d}" for k, v in aff.items()
                if isinstance(v, (int, float))
            )
            if aff_str:
                parts.append(f"- 多维亲密度: {aff_str}")
    except (TypeError, ValueError):
        pass  # 解析失败就跳过，不影响主流程

    # ── 近期与玩家的具体互动 ───────────────────────────────────
    # 从最近 12 条消息里，找出这个 NPC 发言的段落，
    # 并配对玩家行动，形成 "PC: xxx → 你: yyy" 格式
    npc_name = getattr(npc, "name", "") or ""
    exchanges: list[str] = []
    take = recent_messages[-12:]  # last ~6 turns of pairs
    last_user = ""
    for m in take:
        if m.role == "user":
            # 记录玩家上一条行动（去标签、截短）
            last_user = _TAG_STRIP_RE.sub(" ", m.content).strip()[:120]
        elif m.role == "assistant":
            text = m.content or ""
            # 从 GM 叙事里提取这个 NPC 的 <say> 标签内容
            for match in re.finditer(
                r'<say\s+speaker="([^"]+)"[^>]*>([\s\S]*?)</say>',
                text,
            ):
                if match.group(1).strip() == npc_name:
                    line = _TAG_STRIP_RE.sub(" ", match.group(2)).strip()[:120]
                    if line:
                        if last_user:
                            exchanges.append(f"PC: {last_user}  → 你: {line}")
                        else:
                            exchanges.append(f"你: {line}")
    if exchanges:
        parts.append("- 近期与 PC 的交互（按时序）:")
        for e in exchanges[-3:]:  # 最多展示最近 3 条
            parts.append(f"  · {e}")
    else:
        parts.append("- 近期与 PC 的交互: （还没在叙事里直接互动过）")

    return "\n".join(parts)


# ────────────────────────────────────────────────────────────
# 辅助函数：构建当前场景上下文（地点 + 同台 NPC）
# ────────────────────────────────────────────────────────────

async def _format_scene_context(
    s: AsyncSession, session_id: int, on_stage: list[NPC],
) -> str:
    # NPC actor 需要知道「自己在哪里、周围还有谁」才能做出合理反应
    # 这里只取最精简的信息（地点名 + 描述 + 同台 NPC 列表）
    # 完整的地图/时间信息已经在 key_facts 里，Scene agent 能看到
    """Build a scene-context block: current location + on-stage NPCs.
    Topology / world_time blocks already live in key_facts (which Scene
    sees); NPC actors get a smaller subset here."""
    from dzmm.db.models import Location
    # 查找当前地点（is_current == True 表示玩家现在所在的地点）
    current = (await s.execute(
        select(Location).where(
            Location.session_id == session_id,
            Location.is_current == True,  # noqa: E712
        )
    )).scalar_one_or_none()
    parts: list[str] = []
    if current is not None:
        parts.append(f"地点：{current.name}")
        if (current.description or "").strip():
            # 截取前 120 字，避免太长
            parts.append(f"描述：{current.description.strip()[:120]}")
    if on_stage:
        # 把同台 NPC 名字用顿号拼在一起
        names = "、".join(n.name for n in on_stage)
        parts.append(f"同台 NPC：{names}")
    return "\n".join(parts)


# ────────────────────────────────────────────────────────────
# 辅助函数：给剧本章节模式的 Director 构建状态快照
# ────────────────────────────────────────────────────────────

async def _build_director_snapshot(
    s: AsyncSession, session_id: int, current_turn: int,
) -> str:
    # TODO(Plan-C): Remove once all sessions use framework_id.
    # Director 需要一份「当前剧情状态摘要」才能决定下一步的叙事方向
    # 包括：当前章节进度、主线/支线事件完成情况、玩家生命值、隐藏事件倒计时等
    # 控制在约 600 字以内，为 prompt 留出空间
    """Build a richer state snapshot for Director's prompt.

    Includes: turn / doom / scene_turn_count（旧），plus 剧本章节进度、
    本章 [pending]/[done] 主线事件、active hidden_events 倒计时、PC vital
    state、最近 plot_turn major 决策。Keeps it under ~600 chars to leave
    room for history + system prompt.
    """
    sess = await s.get(GameSession, session_id)
    if sess is None:
        return f"第 {current_turn} 回合（无 session 数据）"

    parts = [
        f"# Snapshot @ turn {current_turn}",
        f"- doom: {sess.doom_score}",           # doom 是末日倒计时分数，越高越危险
        f"- scene_turn_count: {sess.scene_turn_count}",  # 当前场景持续了多少回合
    ]

    # ── 玩家角色（PC）的生命/理智/体力状态 ───────────────────────
    cs = (await s.execute(
        select(CharState).where(CharState.session_id == session_id)
    )).scalar_one_or_none()
    char = await s.get(Character, sess.character_id) if sess.character_id else None
    if cs and cs.stats_json:
        try:
            stats = _json.loads(cs.stats_json)  # stats_json 是 JSON 字符串
            hp = stats.get("hp")
            sanity = stats.get("sanity")
            stam = stats.get("stamina")
            kvs = [
                (k, v) for k, v in (("hp", hp), ("sanity", sanity), ("stamina", stam))
                if v is not None
            ]
            if kvs:
                parts.append("- PC: " + " / ".join(f"{k}={v}" for k, v in kvs))
        except (TypeError, ValueError):
            pass
    if char and char.level and char.level > 1:
        parts.append(f"- PC level: {char.level}")

    # ── 当前活跃剧本的章节进度 ────────────────────────────────
    # 找出最新版本且状态为 active 的剧本
    sp = (await s.execute(
        select(Screenplay)
        .where(Screenplay.session_id == session_id, Screenplay.status == "active")
        .order_by(Screenplay.version.desc())
    )).scalars().first()
    if sp is not None:
        try:
            chapters = _json.loads(sp.chapters_json or "[]")  # 所有章节的列表
        except (TypeError, ValueError):
            chapters = []
        try:
            completed = _json.loads(sp.completed_events_json or "[]")  # 已完成的事件
        except (TypeError, ValueError):
            completed = []
        if isinstance(chapters, list) and chapters:
            # 取当前章节（索引从 0 开始，current_chapter 从 1 开始）
            ch_idx = max(0, min(sp.current_chapter - 1, len(chapters) - 1))
            cur_ch = chapters[ch_idx] if isinstance(chapters[ch_idx], dict) else {}
            title = str(cur_ch.get("title", "")).strip()
            main_events = cur_ch.get("main_events") or []
            # 找出本章已完成的主线事件索引集合
            done_idxs = {
                c.get("event_idx") for c in completed
                if isinstance(c, dict)
                and c.get("chapter") == sp.current_chapter
                and (c.get("type") or "main") == "main"
            }
            n_done = sum(1 for i, _ in enumerate(main_events) if i in done_idxs)
            n_total = len(main_events) if isinstance(main_events, list) else 0
            parts.append(
                f"- 章节: 第{sp.current_chapter}章「{title}」 主线 {n_done}/{n_total}"
            )
            # 列出每条主线事件及完成状态（[done] / [pending]）
            if isinstance(main_events, list):
                parts.append(f"- 本章主线事件列表（章节={sp.current_chapter}）:")
                for i, e in enumerate(main_events):
                    if not isinstance(e, dict):
                        continue
                    status = "[done]" if i in done_idxs else "[pending]"
                    desc = str(e.get("description", ""))[:80]
                    parts.append(f"  事件{i+1} {status} {desc}")
            # ── 支线事件 ─────────────────────────────────────
            opt_events = cur_ch.get("optional_events") or []
            done_opt_idxs = {
                c.get("event_idx") for c in completed
                if isinstance(c, dict)
                and c.get("chapter") == sp.current_chapter
                and c.get("type") == "optional"
            }
            if isinstance(opt_events, list) and opt_events:
                parts.append("- 本章支线事件:")
                for i, e in enumerate(opt_events):
                    if not isinstance(e, dict):
                        continue
                    status = "[done]" if i in done_opt_idxs else "[pending]"
                    desc = str(e.get("description", ""))[:60]
                    parts.append(f"  支线{i+1} {status} {desc}")

    # ── 活跃隐藏事件（玩家不可见的幕后事件）────────────────────
    # 隐藏事件是 GM 设置的「定时炸弹」，到期后会触发后果
    hidden_rows = (await s.execute(
        select(HiddenEvent).where(
            HiddenEvent.session_id == session_id,
            HiddenEvent.status == "active",
        ).order_by(HiddenEvent.introduced_turn.desc()).limit(3)
    )).scalars().all()
    if hidden_rows:
        for he in hidden_rows:
            age = current_turn - he.introduced_turn  # 这个事件存在了多少回合
            parts.append(
                f"- 隐藏事件: [{he.subject}/{he.kind}/t+{age}] {(he.description or '')[:50]}"
            )

    # ── 最近几回合的重大剧情转折 ──────────────────────────────
    # 扫描最近 8 条 assistant 消息里的 events_json 字段，
    # 找出 type="plot_turn" 且 impact="major" 的事件
    plot_rows = (await s.execute(
        select(MessageRow.events_json, MessageRow.turn)
        .where(
            MessageRow.session_id == session_id,
            MessageRow.role == "assistant",
            MessageRow.turn >= max(1, current_turn - 8),
        )
        .order_by(MessageRow.turn.desc())
    )).all()
    plot_majors: list[str] = []
    for events_json, turn in plot_rows:
        if not events_json:
            continue
        try:
            evs = _json.loads(events_json)
        except (TypeError, ValueError):
            continue
        if not isinstance(evs, list):
            continue
        for ev in evs:
            if not isinstance(ev, dict):
                continue
            if ev.get("type") == "plot_turn":
                impact = (ev.get("payload") or {}).get("impact", "")
                if impact == "major":
                    desc = (ev.get("payload") or {}).get("description", "")
                    if desc:
                        plot_majors.append(f"  · t{turn}: {str(desc)[:60]}")
    if plot_majors:
        parts.append("- 最近重大决策:")
        parts.extend(plot_majors[:3])

    # ── 上一回合的玩家行动 + 场景叙事摘要 ─────────────────────
    # 让 Director 能判断「上一回合的主线事件是否已经完成」
    last_msgs = (await s.execute(
        select(MessageRow.role, MessageRow.content, MessageRow.turn)
        .where(
            MessageRow.session_id == session_id,
            MessageRow.turn == current_turn - 1,
        )
        .order_by(MessageRow.id)
    )).all()
    if last_msgs:
        parts.append(f"- 上一回合（t{current_turn - 1}）概况:")
        for role, content, _t in last_msgs:
            if role == "user":
                parts.append(f"  PC行动: {(content or '')[:120]}")
            elif role == "assistant":
                # 去除 XML 标签，只保留叙事纯文字
                plain = re.sub(r"<[^>]+>", " ", content or "")
                plain = " ".join(plain.split())[:200]
                parts.append(f"  场景叙事: {plain}")

    return "\n".join(parts)


# ────────────────────────────────────────────────────────────
# 辅助函数：计算「是否应触发 Director」所需的状态字段
# ────────────────────────────────────────────────────────────

async def _build_director_trigger_state(
    s: AsyncSession, session_id: int, sess: GameSession, current_turn: int,
):
    # 这个函数把数据库里散落各处的信息整合成一个简单对象，
    # 供 should_run_director() 做触发判断（详见 triggers.py）
    # v0.10.3 之前这些字段全是硬编码的 False/99，现在改为真实值
    """Compute the trigger-relevant fields from real session state.

    v0.10.3 — replaces hard-coded False/99 values so Director can fire
    synchronously when major events happened on the prior turn or when PC
    is in critical state. Trigger fields scanned:
      - chapter_advanced_last_turn / major_plot_turn_last_turn: from prior
        turn's assistant Message.events_json
      - hp / sanity: from CharState.stats_json
      - hidden_event_due: severity-keyed threshold on active HiddenEvents
        (severity 1→5 turns / 2→3 / 3→2)
    """
    # ── 上一回合的 events_json：判断是否发生了章节推进或重大剧情转折 ──
    last_msg = (await s.execute(
        select(MessageRow.events_json)
        .where(
            MessageRow.session_id == session_id,
            MessageRow.role == "assistant",
            MessageRow.turn == sess.turn_count,  # last completed turn
        )
        .limit(1)
    )).scalar_one_or_none()

    chapter_advanced = False
    plot_turn_major = False
    if last_msg:
        try:
            events = _json.loads(last_msg)
        except (TypeError, ValueError):
            events = []
        if isinstance(events, list):
            for ev in events:
                if not isinstance(ev, dict):
                    continue
                t = ev.get("type")
                if t == "chapter_advance":
                    chapter_advanced = True  # 刚刚发生了章节推进
                if t == "plot_turn":
                    if (ev.get("payload") or {}).get("impact", "") == "major":
                        plot_turn_major = True  # 刚刚发生了重大剧情转折

    # ── 玩家角色的 HP 和理智值 ─────────────────────────────────
    # 如果 HP 或理智值过低，Director 需要立刻出手做出应对
    cs = (await s.execute(
        select(CharState).where(CharState.session_id == session_id)
    )).scalar_one_or_none()
    hp = 99      # 默认值 99 表示「健康」，不会触发临界状态
    sanity = 99
    if cs and cs.stats_json:
        try:
            stats = _json.loads(cs.stats_json)
            hp = int(stats.get("hp", 99))
            sanity = int(stats.get("sanity", 99))
        except (TypeError, ValueError):
            pass

    # ── 隐藏事件是否到期 ──────────────────────────────────────
    # 用简单启发式：severity 1 → 5 回合到期，severity 2 → 3 回合，severity 3 → 2 回合
    # 没有精确的 consequence_turn 字段，所以根据严重程度猜阈值
    hidden_due = False
    hidden_rows = (await s.execute(
        select(HiddenEvent).where(
            HiddenEvent.session_id == session_id,
            HiddenEvent.status == "active",
        )
    )).scalars().all()
    sev_to_threshold = {1: 5, 2: 3, 3: 2}  # 严重程度 → 几回合后到期
    for he in hidden_rows:
        thresh = sev_to_threshold.get(he.severity or 2, 3)
        if (current_turn - (he.introduced_turn or 0)) >= thresh:
            hidden_due = True  # 找到至少一个到期的隐藏事件
            break

    # ── Framework (open-world) 触发字段 ─────────────────────────
    # 只有 framework_id 非空时才查询这些字段，节省数据库开销
    is_framework_mode = bool(sess.framework_id)
    event_triggered_last_turn = False
    event_completed_last_turn = False
    phase_advanced_last_turn = False
    faction_tension_breached = False
    proactive_npc_pending = False

    if is_framework_mode:
        # 复用上方已解析的 events 列表，扫描开放世界事件类型
        if last_msg:
            try:
                fw_events = _json.loads(last_msg)
            except (TypeError, ValueError):
                fw_events = []
            if isinstance(fw_events, list):
                for ev in fw_events:
                    if not isinstance(ev, dict):
                        continue
                    t = ev.get("type")
                    if t == "event_trigger":
                        event_triggered_last_turn = True
                    if t == "event_complete":
                        payload = ev.get("payload") or {}
                        if payload.get("event_id"):
                            event_completed_last_turn = True

        # phase_advanced_last_turn: True iff event_completed_last_turn AND
        # a SessionCampaignState row exists for this session.
        # Approximation: we don't snapshot phase_id at turn start, so we
        # assume any event completion that coincides with an active campaign
        # represents a phase advance. A more precise check would require
        # comparing current_phase_id to a per-turn snapshot.
        if event_completed_last_turn:
            campaign_state = (await s.execute(
                select(SessionCampaignState).where(
                    SessionCampaignState.session_id == session_id
                )
            )).scalar_one_or_none()
            if campaign_state is not None:
                phase_advanced_last_turn = True

        # faction_tension_breached: True if any active faction's tension
        # meets or exceeds its threshold_conflict value
        faction_states = (await s.execute(
            select(SessionFactionState, WorldFaction).join(
                WorldFaction, WorldFaction.id == SessionFactionState.faction_id
            ).where(
                SessionFactionState.session_id == session_id,
                SessionFactionState.is_active == True,  # noqa: E712
            )
        )).all()
        for fs, wf in faction_states:
            try:
                rules = _json.loads(wf.tension_rules_json or "{}")
                threshold = int(rules.get("threshold_conflict", 999))
            except (TypeError, ValueError):
                threshold = 999
            if fs.tension >= threshold:
                faction_tension_breached = True
                break

        # proactive_npc_pending: True if any revealed+alive NPC has
        # favor >= contact_favor_threshold AND cooldown has elapsed
        npc_rows = (await s.execute(
            select(SessionNpcState, WorldNPCTemplate).join(
                WorldNPCTemplate,
                WorldNPCTemplate.id == SessionNpcState.npc_template_id,
            ).where(
                SessionNpcState.session_id == session_id,
                SessionNpcState.is_alive == True,   # noqa: E712
                SessionNpcState.is_revealed == True,  # noqa: E712
            )
        )).all()
        for ns, wt in npc_rows:
            favor_ok = ns.favor >= wt.contact_favor_threshold
            cooldown_ok = (current_turn - ns.last_contact_turn) >= wt.contact_cooldown_turns
            if favor_ok and cooldown_ok:
                proactive_npc_pending = True
                break

    # 用 type() 动态构建一个简单对象（类似 namedtuple），
    # 这样 should_run_director() 可以用 .属性名 来访问各字段
    return type("S", (), {
        "turn_count": sess.turn_count,
        "doom_score": sess.doom_score,
        "scene_turn_count": sess.scene_turn_count,
        "chapter_advanced_last_turn": chapter_advanced,
        "major_plot_turn_last_turn": plot_turn_major,
        "hp": hp,
        "sanity": sanity,
        "hidden_event_due": hidden_due,
        # framework-mode fields (False when not in open-world mode)
        "is_framework_mode": is_framework_mode,
        "event_triggered_last_turn": event_triggered_last_turn,
        "event_completed_last_turn": event_completed_last_turn,
        "phase_advanced_last_turn": phase_advanced_last_turn,
        "faction_tension_breached": faction_tension_breached,
        "proactive_npc_pending": proactive_npc_pending,
    })()


# ────────────────────────────────────────────────────────────
# 辅助函数：读取上次 Director 输出的指令（本回合不运行 Director 时复用）
# ────────────────────────────────────────────────────────────

async def _last_director_directive(s: AsyncSession, stream_id: int) -> str:
    # Director 不是每回合都运行，不运行时复用上次的「剧情指令」（plot_directive）
    # 如果完全没有历史记录（第一次），返回一个默认的中性指令
    """Read the most recent assistant message from the director stream as
    a fallback directive when this turn isn't running Director."""
    row = (await s.execute(
        select(AgentMessage)
        .where(AgentMessage.stream_id == stream_id,
               AgentMessage.role == "assistant")
        .order_by(AgentMessage.id.desc())
        .limit(1)
    )).scalar_one_or_none()
    if row is None:
        # 兜底指令：让 Scene agent 自然推进，不做特殊限制
        return (
            "<plot_directive>\n- 本回合主推：自然推进\n- NPC 重点：（无）\n"
            "- 节奏：常态\n- 禁止：（无）\n</plot_directive>"
        )
    return row.content


# ────────────────────────────────────────────────────────────
# 辅助函数：选取本回合「在场」的 NPC 列表
# ────────────────────────────────────────────────────────────

async def _select_on_stage_npcs(
    s: AsyncSession, session_id: int, current_turn: int, max_count: int,
) -> list[NPC]:
    # 「在场」NPC 的选取规则：
    #   1. pinned == True 的 NPC（GM 手动固定的）一定上场
    #   2. 最近 3 回合内出现过（last_seen_turn 较大）的 NPC 补充到上限
    # v0.10.7 之后这个函数是 fallback，正常路径改由 Scene 的 <npc_cue> 标签决定
    """Pinned + recently-seen NPCs (top-K by last_seen_turn)."""
    pinned = (await s.execute(
        select(NPC).where(
            NPC.session_id == session_id, NPC.pinned == True,  # noqa: E712
        )
    )).scalars().all()
    recent = (await s.execute(
        select(NPC).where(
            NPC.session_id == session_id,
            NPC.last_seen_turn >= max(0, current_turn - 3),  # 最近 3 回合内
        )
        .order_by(NPC.last_seen_turn.desc())
    )).scalars().all()
    # 用字典去重（同一个 NPC 可能既是 pinned 又是 recent）
    seen: dict[int, NPC] = {}
    for n in pinned:
        seen[n.id] = n
    for n in recent:
        if len(seen) >= max_count:
            break
        seen.setdefault(n.id, n)  # setdefault：已存在就不覆盖
    return list(seen.values())[:max_count]


# ────────────────────────────────────────────────────────────
# 辅助函数：对本回合 NPC 列表排序（决定输出顺序，不影响并发）
# ────────────────────────────────────────────────────────────

def _sort_npcs_for_turn(npcs: list, user_action: str) -> list:
    # 玩家看到的 NPC 反应顺序按「相关性」排：
    #   最高优先：玩家在行动里点名提到的 NPC
    #   次高：情绪激烈（愤怒/恐惧/爱意 >= 70）的 NPC
    #   其余：按最近出现的回合倒序
    # 注意：LLM 调用是并发发出的，这里只影响 yield 的顺序（谁先推给前端）
    """Sort NPCs to determine yield order (LLM calls run in parallel anyway).

    Buckets (smaller bucket = yields first):
      0. NPC name appears in user_action (PC directly cued them)
      1. Highest emotion >= 70 (anger/fear/love etc.)
      2. Everyone else, by last_seen_turn descending

    Pure function (no DB access) — safe to call before fan-out."""
    user_action = user_action or ""

    def _key(n) -> tuple[int, int, int]:
        name = (getattr(n, "name", None) or "").strip()
        # 玩家提到了这个 NPC 吗？cue=-1 排在前面（升序排列，-1 < 0）
        cue = -1 if name and name in user_action else 0
        try:
            emo = _json.loads(getattr(n, "emotion_json", None) or "{}")
            max_emo = max(int(v) for v in emo.values()) if emo else 0
        except (TypeError, ValueError):
            max_emo = 0
        # 排序是升序，所以用负数让「情绪值高的」排在前面
        return (cue, -max_emo, -(getattr(n, "last_seen_turn", 0) or 0))

    return sorted(npcs, key=_key)


# ────────────────────────────────────────────────────────────
# 辅助函数：在独立数据库会话中运行单个 NPC actor
# ────────────────────────────────────────────────────────────

async def _run_npc_with_isolated_session(
    session_maker,
    npc: NPC,
    *,
    session_id: int,
    plot_directive: str,
    scene_narrative: str,
    user_action: str,
    client: ModelClient,
    current_turn: int,
    scene_context: str,
    recent_dialogue: str,
    relationship_summary: str = "",
    cue_intent: str = "",
) -> tuple[NPC, list[ParseEvent], int, int]:
    # 【为什么需要「独立 session」？】
    # 多个 NPC 并发运行时，如果共用同一个 SQLAlchemy session，
    # 并发写入会导致「数据库被锁」错误（SQLite 同一时刻只允许一个写入）。
    # 给每个 NPC 创建自己的 session，就像给每人分配一张独立的工作台。
    """Run one NPC actor on its own AsyncSession.

    Returns (npc, events, tokens_in, tokens_out) so the caller can yield
    in sorted order and accumulate token counts."""
    try:
        async with session_maker() as ns:  # 打开一个新的数据库连接
            try:
                events, tok_in, tok_out = await run_npc_actor(
                    ns, npc=npc, session_id=session_id,
                    plot_directive=plot_directive,
                    scene_narrative=scene_narrative,
                    user_action=user_action,
                    client=client,
                    current_turn=current_turn,
                    scene_context=scene_context,
                    recent_dialogue=recent_dialogue,
                    relationship_summary=relationship_summary,
                    cue_intent=cue_intent,
                )
                await ns.commit()  # 成功后提交数据库写入
                return npc, events, tok_in, tok_out
            except Exception as exc:  # noqa: BLE001
                log.warning("npc_actor(%s) failed: %s", npc.name, exc)
                try:
                    await ns.rollback()  # 出错时回滚，避免写入脏数据
                except Exception:  # noqa: BLE001
                    pass
                return npc, [], 0, 0  # 出错时返回空结果，不影响其他 NPC
    except Exception as exc:  # noqa: BLE001
        log.warning("npc_actor(%s) session open failed: %s", npc.name, exc)
        return npc, [], 0, 0


# ────────────────────────────────────────────────────────────
# 辅助函数：从会话设置里读取玩家当前的地点 ID
# ────────────────────────────────────────────────────────────

def _get_pc_location_id(sess) -> int:
    # 开放世界模式需要知道玩家在哪个地点，才能算事件距离
    # 这个 ID 存在 settings_json 里，由 <location_enter> 事件处理器更新
    # 还没设置过时返回 0（框架根节点）
    """Return the PC's current WorldLocation ID. Returns 0 if not tracked yet.

    Framework sessions store pc_location_id in settings_json.
    This is updated by the <location_enter> handler (Plan C will add this).
    Defaults to 0 (framework root) when not yet set.
    """
    try:
        import json
        settings = json.loads(sess.settings_json or "{}")
        return int(settings.get("pc_location_id", 0))
    except (TypeError, ValueError):
        return 0


# ════════════════════════════════════════════════════════════
# 核心函数：每回合的总调度入口
# ════════════════════════════════════════════════════════════

async def run_turn_v10(
    s: AsyncSession,
    *,
    session_id: int,
    user_action: str,           # 玩家这回合输入的行动文字
    scene_client: ModelClient,  # 负责生成场景叙事的 LLM 客户端
    director_client: ModelClient,  # 负责剧情决策的 Director LLM 客户端
    npc_client: ModelClient,    # 负责 NPC 反应的 LLM 客户端
    session_maker=None,         # 数据库 session 工厂，用于 NPC 并发（None 时顺序执行）
    world_md: str,              # 世界设定 Markdown 文本
    character_md: str,          # 玩家角色 Markdown 文本
    live_state_text: str,       # 当前状态的实时文本（血量/位置等）
    key_facts: str,             # 关键事实摘要（地图/时间等）
    recent_messages: list[Message],  # 最近的对话历史
    scene_params: GenerationParams | None = None,  # 场景生成参数（可覆盖默认值）
) -> AsyncIterator[ParseEvent | UsageSummary]:
    # 【流式响应（SSE）的工作原理】
    # 这个函数是一个「异步生成器」（async generator）。
    # 它用 `yield` 关键字把事件一个一个「推出去」，
    # 调用方（game.py）把这些事件转成 SSE（Server-Sent Events）格式发给浏览器。
    # 浏览器收到后实时更新界面，玩家就看到文字逐字出现的效果。
    #
    # 【yield 在异步生成器里的作用】
    # 普通函数用 return 一次性返回结果。
    # 生成器函数用 yield 把结果「分批」推出——每次 yield 都暂停函数、
    # 把值交给调用方处理，然后等待下一次 next() 调用时继续。
    # 异步生成器（async def + yield）在此基础上允许在 yield 之间 await 异步操作，
    # 这样既不阻塞事件循环，又能实时推送数据。
    """Per-turn coordination. Runs Director (sync if triggered) ->
    streams Scene -> fan-out NPC actors. Yields ParseEvents followed by
    a final UsageSummary (filtered out by game.py before SSE forwarding).

    `session_maker`: when provided, NPC actors run in parallel with
    isolated AsyncSessions (production path — fast). When None, falls
    back to sequential execution on the shared session `s` (back-compat
    for tests that pass a single session in)."""
    sess = await s.get(GameSession, session_id)
    if sess is None:
        return  # 找不到会话就直接退出（生成器结束）
    current_turn = sess.turn_count + 1  # 下一回合的编号

    # 获取或创建 Director 的「对话历史流」（AgentStream）
    # 每个 agent 都有自己的私有历史，不和玩家可见的消息混在一起
    director_stream = await get_or_create_stream(
        s, session_id, STREAM_KIND_DIRECTOR, "",
    )

    # v0.10.3: 从真实数据计算 Director 触发所需的字段
    cs_obj = await _build_director_trigger_state(s, session_id, sess, current_turn)

    total_tok_in = 0   # 累计输入 token 数（用于计费统计）
    total_tok_out = 0  # 累计输出 token 数

    # 提前加载玩家角色数据，Director 和 Scene 都需要知道 PC 的名字
    char = await s.get(Character, sess.character_id)

    # ── 步骤 1：判断并运行 Director ──────────────────────────
    fire, reason = should_run_director(director_stream, cs_obj, current_turn)
    if fire:
        log.info("director firing (reason=%s) at turn %d", reason, current_turn)
        # 【关键：根据 framework_id 选择 Director 类型】
        # framework_id 非空 → 开放世界模式，用地图/事件权重来决策
        # framework_id 为空 → 章节剧本模式，用章节进度快照来决策
        if sess.framework_id:
            directive, d_in, d_out = await run_open_world_director(
                s=s,
                session_id=session_id,
                framework_id=sess.framework_id,
                client=director_client,
                current_turn=current_turn,
                pc_location_id=_get_pc_location_id(sess),
                character_name=(char.name if char else "PC"),
                character_md=(getattr(char, "profile_md", "") or ""),
            )
        else:
            snapshot = await _build_director_snapshot(s, session_id, current_turn)
            directive, d_in, d_out = await run_director(
                s, session_id, director_client, current_turn, snapshot,
            )
        total_tok_in += d_in
        total_tok_out += d_out
        # Director 可能在 directive 文本里附带 <event_complete> 或 <event_trigger> 标签，
        # 提前 yield 出去，让 apply_tags 在 Scene 运行前就处理完成/触发标记
        for m in re.finditer(
            r'<event_complete\b([^/]*/?)>',
            directive,
        ):
            attr_str = m.group(1)
            attrs: dict[str, str] = {}
            for am in re.finditer(r'(\w+)=["\']([^"\']*)["\']', attr_str):
                attrs[am.group(1)] = am.group(2)
            if "chapter" in attrs and "event" in attrs:
                log.info(
                    "director yielded event_complete ch=%s ev=%s type=%s",
                    attrs.get("chapter"), attrs.get("event"), attrs.get("type", "main"),
                )
                yield TagComplete(name="event_complete", attrs=attrs)  # 推送给 game.py（线性剧本路径）
            elif "event_id" in attrs:
                log.info(
                    "director yielded event_complete event_id=%s (open-world)",
                    attrs.get("event_id"),
                )
                yield TagComplete(name="event_complete", attrs=attrs)  # 推送给 game.py（开放世界路径）

        # 开放世界：Director 声明事件触发（pending → triggered）
        for m in re.finditer(
            r'<event_trigger\b([^/]*/?)>',
            directive,
        ):
            attr_str = m.group(1)
            attrs_t: dict[str, str] = {}
            for am in re.finditer(r'(\w+)=["\']([^"\']*)["\']', attr_str):
                attrs_t[am.group(1)] = am.group(2)
            if "event_id" in attrs_t:
                log.info(
                    "director yielded event_trigger event_id=%s",
                    attrs_t.get("event_id"),
                )
                yield TagComplete(name="event_trigger", attrs=attrs_t)  # 推送给 game.py
    else:
        # 本回合不运行 Director，复用上次的 directive
        directive = await _last_director_directive(s, director_stream.id)

    # 从 Character 表读取 PC 名字，防止叙事里 PC 名字漂移
    pc_name = "PC"
    if char and char.name:
        pc_name = char.name

    # ── 步骤 2：运行 Scene agent，收集叙事文本 ──────────────
    narrative_buf: list[str] = []   # 收集所有 NarrativeDelta 的文本
    scene_raw_parts: list[str] = [] # 收集完整原始输出（含 XML 标签），用于调试存档
    # v0.10.7：收集 Scene 里的 <npc_cue> 标签，以确定哪些 NPC 需要发言
    # 格式：{NPC名字: 意图字符串}，保持 Scene 叙事里的出现顺序
    cued_npcs: dict[str, str] = {}
    scene_tok_in = scene_tok_out = 0
    # 遍历 Scene agent 的输出流（异步生成器）
    async for ev in run_scene(
        client=scene_client,
        pc_name=pc_name,
        plot_directive=directive,
        world_md=world_md, character_md=character_md,
        live_state_text=live_state_text, key_facts=key_facts,
        recent_messages=recent_messages,
        current_action=user_action,
        params=scene_params,
    ):
        if isinstance(ev, UsageSummary):
            # UsageSummary 是 token 统计，不转发给前端
            scene_tok_in = ev.tokens_in
            scene_tok_out = ev.tokens_out
            total_tok_in += ev.tokens_in
            total_tok_out += ev.tokens_out
            continue  # 跳过，不 yield 给 SSE
        if isinstance(ev, NarrativeDelta):
            # NarrativeDelta 是叙事文本片段（逐字流），收集起来备用
            narrative_buf.append(ev.text)
            scene_raw_parts.append(ev.text)
        elif isinstance(ev, TagComplete):
            if ev.name == "npc_cue":
                # <npc_cue speaker="艾莲娜" intent="紧张询问"> 标签
                # 记录 Scene 认为本回合应该发言的 NPC 及其意图
                speaker = (ev.attrs or {}).get("speaker", "").strip()
                intent = (ev.attrs or {}).get("intent", "").strip()
                if speaker and speaker not in cued_npcs:
                    cued_npcs[speaker] = intent  # 保持首次出现的顺序
            # 重建 XML 字符串存入调试档案（近似，非完全精确）
            attr_str = " ".join(f'{k}="{v}"' for k, v in (ev.attrs or {}).items())
            tag_open = f"<{ev.name}{' ' + attr_str if attr_str else ''}>"
            if ev.content:
                scene_raw_parts.append(f"{tag_open}{ev.content}</{ev.name}>")
            else:
                scene_raw_parts.append(f"{tag_open}</{ev.name}>")
        yield ev  # 把每个事件实时推给前端（SSE 流式响应的关键）

    scene_narrative = "".join(narrative_buf)  # Scene 完整叙事文本

    # 把 Scene 的输入摘要 + 完整输出存入 AgentStream，用于调试回溯
    scene_input_summary = (
        f"# directive\n{directive[:400]}\n\n"
        f"# key_facts\n{(key_facts or '')[:600]}\n\n"
        f"# user_action\n{user_action[:200]}"
    )
    scene_stream = await get_or_create_stream(s, session_id, STREAM_KIND_SCENE, "")
    await append_message(s, scene_stream.id, current_turn, "user",
                         scene_input_summary, tokens_in=scene_tok_in)
    await append_message(s, scene_stream.id, current_turn, "assistant",
                         "".join(scene_raw_parts), tokens_out=scene_tok_out)

    # ── 步骤 3：确定本回合「在场」的 NPC 列表 ─────────────────
    # v0.10.7：优先用 Scene 的 <npc_cue> 驱动，避免「pinned NPC 无故冒出来」的 bug
    on_stage: list[NPC] = []
    if cued_npcs:
        cue_names = list(cued_npcs.keys())
        # 按名字批量查询 NPC（只查这个会话里的）
        rows = (await s.execute(
            select(NPC).where(
                NPC.session_id == session_id,
                NPC.name.in_(cue_names),  # SQL IN 子句
            )
        )).scalars().all()
        rows_by_name = {n.name: n for n in rows}
        # 按 cue 出现顺序排列（保持 Scene 叙事的顺序感）
        # 如果 NPC 名字在数据库里不存在，跳过（避免崩溃）
        for name in cue_names:
            if name in rows_by_name:
                on_stage.append(rows_by_name[name])
    else:
        # 兜底路径：Scene 没有 cue 任何 NPC（旧版场景 prompt 可能如此）
        # 退回到 pinned + 最近出现 的启发式方法
        on_stage = await _select_on_stage_npcs(
            s, session_id, current_turn, NPC_MAX_PARALLEL,
        )
    if on_stage:
        # 对 NPC 排序，决定推给前端的顺序（最相关的先推）
        ordered = _sort_npcs_for_turn(on_stage, user_action)
        recent_dialogue = _format_recent_dialogue(recent_messages)
        scene_context = await _format_scene_context(s, session_id, on_stage)

        # v0.10.6：在扇出之前统一构建每个 NPC 的关系摘要
        # 这样所有 NPC 看到的 recent_messages 快照一致
        npc_relationships: dict[str, str] = {}
        for npc in ordered:
            npc_relationships[npc.name] = await _format_npc_relationship(
                s, session_id, npc, recent_messages,
            )

        if session_maker is not None:
            # ── 并发扇出（production 路径）────────────────────
            # asyncio.gather 让所有 NPC 的 LLM 调用「同时发出」，
            # 而不是等一个完成再调下一个，大幅降低总延迟。
            #
            # 扇出前先 commit 外层 session：
            # SQLite 持有独占写锁时，新 session 会遇到「database is locked」，
            # 提前 commit 释放锁，让各 NPC 的独立 session 能顺利写入。
            try:
                await s.commit()
            except Exception as exc:  # noqa: BLE001
                log.warning("pre-fanout commit failed: %s", exc)
            # 为每个 NPC 创建一个异步任务
            tasks = [
                _run_npc_with_isolated_session(
                    session_maker, npc,
                    session_id=session_id,
                    plot_directive=directive,
                    scene_narrative=scene_narrative,
                    user_action=user_action,
                    client=npc_client,
                    current_turn=current_turn,
                    scene_context=scene_context,
                    recent_dialogue=recent_dialogue,
                    relationship_summary=npc_relationships.get(npc.name, ""),
                    cue_intent=cued_npcs.get(npc.name, ""),
                )
                for npc in ordered
            ]
            # gather 等待所有任务并发完成，返回顺序和 tasks 列表一致
            results = await asyncio.gather(*tasks)
            # 按排序后的顺序 yield（gather 结果可能乱序，用名字做 key 重排）
            result_map = {n.name: (evs, ti, to) for n, evs, ti, to in results}
            for npc in ordered:
                evs, ti, to = result_map.get(npc.name, ([], 0, 0))
                total_tok_in += ti
                total_tok_out += to
                for ev in evs:
                    yield ev  # 把 NPC 的 <say>/<npc_update> 事件推给前端
        else:
            # ── 顺序执行（测试/兼容路径）─────────────────────
            # 没有 session_maker 时（如单元测试传入同一个 session），
            # 改为顺序调用，yield 顺序和排序一致
            for npc in ordered:
                try:
                    events, n_in, n_out = await run_npc_actor(
                        s, npc=npc, session_id=session_id,
                        plot_directive=directive,
                        scene_narrative=scene_narrative,
                        user_action=user_action,
                        client=npc_client,
                        current_turn=current_turn,
                        scene_context=scene_context,
                        recent_dialogue=recent_dialogue,
                        relationship_summary=npc_relationships.get(npc.name, ""),
                        cue_intent=cued_npcs.get(npc.name, ""),
                    )
                    total_tok_in += n_in
                    total_tok_out += n_out
                except Exception as exc:  # noqa: BLE001
                    log.warning("npc_actor(%s) failed: %s", npc.name, exc)
                    continue
                for ev in events:
                    yield ev
    # 最后 yield 一个 token 统计汇总（game.py 会拦截并记录，不转发给前端）
    yield UsageSummary(tokens_in=total_tok_in, tokens_out=total_tok_out)
