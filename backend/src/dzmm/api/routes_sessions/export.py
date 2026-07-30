# ============================================================
# 存档导出接口
# ============================================================
# 【模块作用】
#   提供单个接口：
#   - GET /sessions/{id}/export?format=json|md
#
# 【导出的用途】
#   - format=json：结构化的完整存档，用于：
#     * 外部分析（把跑团记录发给 LLM 让它写总结）
#     * 将来的"导入"功能（重建存档）
#     * 开发调试
#   - format=md：人类可读的 Markdown 报告，用于：
#     * 玩家归档保存自己的游戏记录
#     * 分享给朋友阅读
#     * 作为下一段故事的背景材料
#
# 【导出的内容】
#   一次性查询并打包所有关联数据：
#   存档基本信息 + 世界设定 + 角色 + 完整对话历史 +
#   故事摘要 + 角色状态 + 所有 NPC + NPC 关系 +
#   剧情线 + 任务目标 + 隐藏事件 + 玩家反馈
# ============================================================
"""Session export endpoint — split out from _impl.py.

Provides GET /sessions/{session_id}/export?format=json|md plus the
helpers used to build/render the archive payload."""
import json
import os
from datetime import datetime, UTC

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.db.models import (
    Character,
    CharState,
    Feedback,
    HiddenEvent,
    Message as MessageRow,
    NPC,
    NpcRelation,
    PCGoal,
    PlotThread,
    Session as GameSession,
    StorySummary,
    World,
)

from dzmm.api.routes_sessions._common import (
    _npc_to_dict,
    _parse_events_json,
    get_session_dep,
)

router = APIRouter(prefix="/sessions", tags=["sessions"])


# ── 文件名处理辅助函数 ────────────────────────────────────────────────

def _redact_portrait(p: str | None) -> str:
    """Strip directory prefix from a portrait path so exports don't leak
    absolute filesystem locations. Returns just the basename (or '')."""
    # 导出文件不应该包含服务器上的绝对路径（安全考虑）
    # os.path.basename("/home/user/portraits/alex.png") → "alex.png"
    if not p:
        return ""
    return os.path.basename(p)


def _safe_filename(name: str) -> str:
    """Sanitize a session name for use in HTTP Content-Disposition filename.

    HTTP headers are latin-1 only, so we strip non-ASCII (Python's str.isalnum
    returns True for CJK chars but they can't be header-encoded). Callers
    that want to preserve the original CJK name should additionally emit a
    `filename*=UTF-8''<percent-encoded>` per RFC 5987 — see _disposition_header.
    """
    # HTTP 响应头只支持 Latin-1 编码，中文字符会导致编码错误
    # 把非 ASCII 字符（包括中文）和非字母数字字符替换成下划线
    cleaned = "".join(c if (c.isascii() and c.isalnum()) else "_" for c in (name or ""))
    # strip("_") 去除首尾下划线，如果结果为空则用 "session" 兜底
    return cleaned.strip("_") or "session"


def _disposition_header(original_name: str, ext: str) -> str:
    """Build a Content-Disposition value with both ASCII fallback and RFC 5987
    UTF-8 encoded filename* so browsers can recover the original CJK name."""
    # HTTP Content-Disposition 告诉浏览器："这是一个下载文件，文件名是..."
    # RFC 5987 允许用 filename*=UTF-8''<百分比编码> 的格式传递非 ASCII 文件名
    # 现代浏览器优先使用 filename*，旧版本浏览器使用 filename（ASCII 安全回退）
    from urllib.parse import quote  # quote 做百分比编码（URL 编码）
    safe = _safe_filename(original_name)
    fallback = f"dzmm_export_{safe}.{ext}"  # ASCII 安全的文件名（给旧浏览器用）
    # safe="" 表示不把斜杠等特殊字符当作安全字符（全部编码）
    encoded = quote(f"dzmm_export_{original_name or 'session'}.{ext}", safe="")
    # 同时提供两种格式，浏览器自动选择支持的那个
    return f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{encoded}"


# ── 构建导出 payload（JSON 格式）────────────────────────────────────
def _build_export_payload(
    sess: GameSession,
    world: World | None,
    char: Character | None,
    messages: list[MessageRow],
    summary: StorySummary | None,
    cs: CharState | None,
    npcs: list[NPC],
    relations: list[NpcRelation],
    threads: list[PlotThread],
    goals: list[PCGoal],
    hidden: list[HiddenEvent],
    feedbacks: list[Feedback],
) -> dict:
    # 把所有数据库对象转换成纯 Python 字典，组成嵌套的 JSON 结构
    return {
        "version": "0.10",   # 导出格式版本（将来格式变化时用于兼容性检测）
        # datetime.now(UTC)：获取当前 UTC 时间（时区感知）
        # .replace(tzinfo=None)：去掉时区信息（isoformat 不带 +00:00 后缀）
        "exported_at": datetime.now(UTC).replace(tzinfo=None).isoformat(),
        "session": {
            "id": sess.id,
            "name": sess.name,
            "world_id": sess.world_id,
            "character_id": sess.character_id,
            "turn_count": sess.turn_count,
            "schema_version": sess.schema_version,  # 数据库 schema 版本（用于迁移检测）
            "pc_mood_json": sess.pc_mood_json,
            # .isoformat() 把 datetime 对象转为 ISO 8601 字符串（"2024-01-15T10:30:00"）
            "created_at": sess.created_at.isoformat() if sess.created_at else None,
            "last_played": sess.last_played.isoformat() if sess.last_played else None,
        },
        # 条件表达式：world 不为 None 时展开其字段，否则为 None
        "world": (
            {
                "id": world.id,
                "name": world.name,
                "content_md": world.content_md,  # 世界设定的 Markdown 正文
                "rules_json": world.rules_json,  # 游戏规则 JSON
                "style": world.style,            # 叙事风格
            } if world else None
        ),
        "character": (
            {
                "id": char.id,
                "name": char.name,
                "profile_md": char.profile_md,        # 角色背景 Markdown
                "base_stats_json": char.base_stats_json,  # 初始属性
                "level": char.level,
                "xp": char.xp,
                "portrait_path": _redact_portrait(char.portrait_path),  # 脱敏：只保留文件名
            } if char else None
        ),
        "messages": [
            {
                "id": m.id,
                "role": m.role,
                "content": m.content,
                "turn": m.turn,
                "tokens_in": m.tokens_in,
                "tokens_out": m.tokens_out,
                "events": _parse_events_json(m.events_json),  # 解析为列表
                "diagnostics": _parse_events_json(m.diagnostics_json),
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in messages
        ],
        "story_summary": (
            {
                "summary_text": summary.summary_text,  # LLM 生成的故事摘要文本
                "last_summarized_msg_id": summary.last_summarized_msg_id,  # 摘要覆盖到哪条消息
                "summary_tokens": summary.summary_tokens,  # 摘要占用的 token 数
                "updated_at": summary.updated_at.isoformat() if summary.updated_at else None,
            } if summary else None
        ),
        "char_state": (
            {
                "stats_json": cs.stats_json,      # 当前属性（HP/San 等）
                "inventory_json": cs.inventory_json,  # 当前背包
                "updated_at": cs.updated_at.isoformat() if cs.updated_at else None,
            } if cs else None
        ),
        # _npc_to_dict: 把 NPC ORM 对象转为含所有字段的字典（包括解析后的 JSON 字段）
        "npcs": [_npc_to_dict(n) for n in npcs],
        "npc_relations": [
            {
                "id": r.id, "npc_a": r.npc_a, "npc_b": r.npc_b,
                "kind": r.kind, "description": r.description,
                "introduced_turn": r.introduced_turn,
            }
            for r in relations
        ],
        "plot_threads": [
            {
                "id": t.id, "type": t.type, "description": t.description,
                "introduced_turn": t.introduced_turn,
                "importance": t.importance, "status": t.status,
                "resolution": t.resolution,
            }
            for t in threads
        ],
        "pc_goals": [
            {
                "id": g.id, "description": g.description,
                "priority": g.priority, "status": g.status,
                "introduced_turn": g.introduced_turn,
                "completed_turn": g.completed_turn,       # 完成时的回合号
                "completion_note": g.completion_note,     # 完成时的附注
            }
            for g in goals
        ],
        "hidden_events": [
            {
                "id": h.id, "subject": h.subject, "kind": h.kind,
                "severity": h.severity, "description": h.description,
                "consequence": h.consequence,
                "introduced_turn": h.introduced_turn,
                "trigger_turn": h.trigger_turn,   # 预计触发回合（deadline 类型）
                "status": h.status, "resolution": h.resolution,
                "resolved_turn": h.resolved_turn, # 实际解决/触发的回合号
            }
            for h in hidden
        ],
        "feedbacks": [
            {
                "id": f.id, "turn": f.turn, "message_id": f.message_id,
                "kind": f.kind,      # 反馈类型（like/dislike/bug_report 等）
                "content": f.content,
                "created_at": f.created_at.isoformat() if f.created_at else None,
            }
            for f in feedbacks
        ],
    }


# ── 渲染 Markdown 格式导出 ────────────────────────────────────────────
def _render_export_md(payload: dict) -> str:
    """Render a human/LLM readable Markdown archive from the JSON payload."""
    # 从 payload 字典里取出各部分数据
    sess = payload["session"]
    world = payload.get("world") or {}     # or {} 确保 None 时不出错
    char = payload.get("character") or {}
    summary = payload.get("story_summary") or {}
    cs = payload.get("char_state") or {}
    npcs = payload.get("npcs") or []
    relations = payload.get("npc_relations") or []
    threads = payload.get("plot_threads") or []
    goals = payload.get("pc_goals") or []
    hidden = payload.get("hidden_events") or []
    feedbacks = payload.get("feedbacks") or []
    messages = payload.get("messages") or []

    lines: list[str] = []  # 用列表收集所有行，最后 join 成字符串（比字符串拼接更高效）

    # ── 封面信息 ─────────────────────────────────────────────────────
    lines.append(f"# {sess.get('name', '')}")  # 一级标题：存档名
    lines.append("")
    lines.append(f"- 世界：{world.get('name', '(未知)')}（{world.get('style', '')}）")
    char_name = char.get("name", "(未知)")
    lines.append(
        f"- 角色：{char_name} (Lv {char.get('level', 1)}, {char.get('xp', 0)} XP)"
    )
    lines.append(f"- 创建时间：{sess.get('created_at', '')}")
    lines.append(f"- 总回合：{sess.get('turn_count', 0)}")
    lines.append(f"- 导出时间：{payload.get('exported_at', '')}")
    lines.append("")

    # ── 故事概要 ─────────────────────────────────────────────────────
    lines.append("## 故事概要")
    lines.append(summary.get("summary_text") or "（暂无）")
    lines.append("")

    # ── 当前状态 ─────────────────────────────────────────────────────
    lines.append("## 当前状态")
    try:
        stats = json.loads(cs.get("stats_json") or "{}")
    except (TypeError, ValueError):
        stats = {}
    try:
        inventory = json.loads(cs.get("inventory_json") or "[]")
    except (TypeError, ValueError):
        inventory = []
    if stats:
        # 把 {"HP": 80, "San": 60} 格式化为 "HP=80, San=60"
        stats_str = ", ".join(f"{k}={v}" for k, v in stats.items())
    else:
        stats_str = "（无）"
    lines.append(f"- 属性：{stats_str}")
    lines.append(
        "- 物品：" + (", ".join(str(x) for x in inventory) if inventory else "（无）")
    )

    # 只显示活跃的目标
    active_goals = [g for g in goals if g.get("status") == "active"]
    if active_goals:
        lines.append("- 当前任务：")
        for g in active_goals:
            lines.append(f"  - [{g.get('priority', 'normal')}] {g.get('description', '')}")
    else:
        lines.append("- 当前任务：（无）")

    # 只显示活跃的隐藏事件（导出时解锁给玩家/阅读者看）
    active_hidden = [h for h in hidden if h.get("status") == "active"]
    if active_hidden:
        lines.append("- 暗中状态：")
        for h in active_hidden:
            lines.append(
                f"  - [{h.get('kind', '')}/sev{h.get('severity', 0)}] "
                f"{h.get('subject', '')}: {h.get('description', '')}"
            )
    else:
        lines.append("- 暗中状态：（无）")
    lines.append("")

    # ── 角色档案 ─────────────────────────────────────────────────────
    lines.append("## 角色档案")
    lines.append(f"### {char_name}")
    lines.append(char.get("profile_md", "") or "（无）")
    lines.append("")

    # ── NPC 列表 ─────────────────────────────────────────────────────
    if npcs:
        lines.append("## 主要 NPC")
        for n in npcs:
            lines.append(f"### {n.get('name', '')}")
            lines.append(
                f"- 好感: {n.get('favor', 0)}, 状态: {n.get('state', '')}, "
                f"原型: {n.get('archetype', '')}"
            )
            if n.get("description"):
                lines.append(f"- 描述: {n['description']}")
            if n.get("purpose"):
                lines.append(f"- 动机: {n['purpose']}")
            emo = n.get("emotion") or {}
            if isinstance(emo, dict) and emo:
                # 情绪字典格式化为 "愤怒=3, 恐惧=2"
                emo_str = ", ".join(f"{k}={v}" for k, v in emo.items())
                lines.append(f"- 情绪: {emo_str}")
            lines.append("")

    # ── 关系网 ───────────────────────────────────────────────────────
    if relations:
        lines.append("## 关系网")
        for r in relations:
            desc = r.get("description") or ""
            tail = f": {desc}" if desc else ""
            lines.append(
                f"- {r.get('npc_a', '')} ←→ {r.get('npc_b', '')} "
                f"({r.get('kind', '')}){tail}"
            )
        lines.append("")

    # ── 剧情线 ───────────────────────────────────────────────────────
    if threads:
        lines.append("## 剧情线 (Plot Threads)")
        for t in threads:
            lines.append(
                f"- [{t.get('status', '')}/{t.get('type', '')}] "
                f"{t.get('description', '')}"
            )
        lines.append("")

    # ── 跑团记录（按回合组织）───────────────────────────────────────
    if messages:
        lines.append("## 跑团记录")
        # Bucket by turn number — first user message + first assistant message
        # within that turn make a "回合 N" block. Fall back to per-message dump
        # if turns aren't paired.
        # 把消息列表按回合号分组
        turns: dict[int, dict] = {}  # 回合号 → {"user": ..., "assistant": ..., "events": [...]}
        order: list[int] = []        # 保持回合号的原始顺序（字典在 Python 3.7+ 保持插入顺序）
        for m in messages:
            t = int(m.get("turn", 0) or 0)  # or 0 处理 None 值
            if t not in turns:
                turns[t] = {"user": None, "assistant": None, "events": []}
                order.append(t)
            slot = m.get("role")
            # 每个回合只记录第一条 user 和第一条 assistant 消息（理论上每回合各一条）
            if slot in ("user", "assistant") and turns[t][slot] is None:
                turns[t][slot] = m
            # 收集该回合的所有事件
            for ev in (m.get("events") or []):
                turns[t]["events"].append(ev)

        for t in order:
            if t == 0:
                continue  # turn 0 是游戏前的系统消息，不展示

            entry = turns[t]
            lines.append(f"### 回合 {t}")
            u = entry.get("user")
            a = entry.get("assistant")
            if u:
                lines.append(f"**玩家行动**：{u.get('content', '')}")
            if a:
                lines.append(f"**GM**：{a.get('content', '')}")
            evs = entry.get("events") or []
            if evs:
                # 把事件列表格式化为简短摘要
                ev_summaries = []
                for ev in evs:
                    et = ev.get("type", "?")
                    payload_obj = ev.get("payload")
                    ev_summaries.append(
                        f"{et}={json.dumps(payload_obj, ensure_ascii=False)}"
                    )
                lines.append(f"事件：{', '.join(ev_summaries)}")
            lines.append("")

    # ── 玩家反馈 ─────────────────────────────────────────────────────
    if feedbacks:
        lines.append("## 玩家反馈")
        for f in feedbacks:
            lines.append(
                f"- [{f.get('kind', 'other')} @ 回合 {f.get('turn', 0)} / "
                f"{f.get('created_at', '')}] {f.get('content', '')}"
            )
        lines.append("")

    # "\n".join(lines) 把所有行用换行符连接，.rstrip() 去除末尾多余空行，再加一个换行
    return "\n".join(lines).rstrip() + "\n"


# ── GET /sessions/{session_id}/export ────────────────────────────────
@router.get("/{session_id}/export")
async def export_session(
    session_id: int,
    format: str = "json",  # 查询参数，默认 json；可选 md
    s: AsyncSession = Depends(get_session_dep),
):
    """Full archive export. format=json (default) returns a structured dump
    suitable for re-import / external LLM analysis. format=md returns a
    human-readable Markdown report with Content-Disposition for download."""
    if format not in ("json", "md"):
        raise HTTPException(400, "format must be 'json' or 'md'")

    sess = await s.get(GameSession, session_id)
    if sess is None:
        raise HTTPException(404, "session not found")

    # 一次性查询所有关联数据（一个 DB 事务内完成，保证数据一致性）
    world = await s.get(World, sess.world_id)
    char = await s.get(Character, sess.character_id)

    # 消息历史：按 id 升序（时间顺序）
    messages = (await s.execute(
        select(MessageRow).where(MessageRow.session_id == session_id)
        .order_by(MessageRow.id)
    )).scalars().all()

    # scalar_one_or_none()：查询结果为一行时返回，无结果时返回 None
    summary = (await s.execute(
        select(StorySummary).where(StorySummary.session_id == session_id)
    )).scalar_one_or_none()

    cs = (await s.execute(
        select(CharState).where(CharState.session_id == session_id)
    )).scalar_one_or_none()

    npcs = (await s.execute(
        select(NPC).where(NPC.session_id == session_id).order_by(NPC.id)
    )).scalars().all()

    relations = (await s.execute(
        select(NpcRelation).where(NpcRelation.session_id == session_id)
        .order_by(NpcRelation.id)
    )).scalars().all()

    threads = (await s.execute(
        select(PlotThread).where(PlotThread.session_id == session_id)
        .order_by(PlotThread.id)
    )).scalars().all()

    goals = (await s.execute(
        select(PCGoal).where(PCGoal.session_id == session_id)
        .order_by(PCGoal.id)
    )).scalars().all()

    # hidden_events: include both active + resolved for archival/analysis.
    # 导出时包含所有隐藏事件（含已解决的），用于完整存档
    hidden = (await s.execute(
        select(HiddenEvent).where(HiddenEvent.session_id == session_id)
        .order_by(HiddenEvent.introduced_turn, HiddenEvent.id)
    )).scalars().all()

    feedbacks = (await s.execute(
        select(Feedback).where(Feedback.session_id == session_id)
        .order_by(Feedback.created_at, Feedback.id)
    )).scalars().all()

    # 调用辅助函数构建统一的 payload 字典
    payload = _build_export_payload(
        sess=sess, world=world, char=char, messages=messages,
        summary=summary, cs=cs, npcs=npcs, relations=relations,
        threads=threads, goals=goals,
        hidden=hidden, feedbacks=feedbacks,
    )

    if format == "md":
        # Markdown 格式：渲染后用 Response 返回纯文本
        md_text = _render_export_md(payload)
        return Response(
            content=md_text,
            media_type="text/markdown; charset=utf-8",  # 告知浏览器这是 Markdown 文件
            headers={
                # Content-Disposition: attachment 触发浏览器"另存为"对话框
                "Content-Disposition": _disposition_header(sess.name, "md"),
            },
        )

    # JSON 格式：用 JSONResponse 返回
    # JSONResponse 比直接 return dict 多了设置响应头的能力（用于 Content-Disposition）
    return JSONResponse(
        content=payload,
        headers={
            "Content-Disposition": _disposition_header(sess.name, "json"),
        },
    )
