# ============================================================
# 隐藏事件（Hidden Event）处理模块
#
# 负责处理 <hidden_event> XML 标签，管理"隐藏的故事状态"。
#
# 【什么是隐藏事件？】
# 隐藏事件是 GM 知道但玩家（PC）不知道的故事状态，例如：
#   - "炸弹已被触发，还有 3 回合爆炸"
#   - "NPC 王欣已经怀疑 PC 的真实身份"
#   - "雇主暗中监视 PC 的行动"
#
# 这类信息在故事中是"存在但未被玩家发现的事实"，
# 会影响 GM 的叙事决策（例如 3 回合后不管如何都触发爆炸），
# 但不应该直接显示在玩家可见的面板上。
#
# 【设计意图（"引信"机制）】
# hidden_event 有 severity（严重程度 1-3）字段，
# 系统可以根据严重程度决定是否把这个隐藏状态注入 GM 的提示词，
# 提醒 GM "记住这个潜在的爆炸点还没解决"。
#
# 【两种操作模式】
# 1. 创建：GM 声明"存在某个隐藏状态"（需要 kind 字段）
# 2. 解决：GM 声明"某个隐藏状态已被触发/解决"（需要 subject 字段 + resolve 指令）
#
# 典型的 GM 输出示例：
#   <hidden_event kind="time_pressure" subject="炸弹" severity="3">还有3回合爆炸</hidden_event>
#   <hidden_event resolve="true" subject="炸弹" resolution="PC 剪断红线，炸弹拆除"/>
# ============================================================

"""<hidden_event> handler — implicit story state with a fuse."""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.db.models import HiddenEvent
from dzmm.parsing.repair import parse_loose_json  # 宽松 JSON 解析

log = logging.getLogger(__name__)


async def _apply_hidden_event(
    session: AsyncSession,
    session_id: int,
    current_turn: int,
    attrs: dict[str, str],   # XML 属性
    content: str,            # 标签 body（可能含 JSON 或纯文字描述）
) -> None:
    # -------------------------------------------------------
    # 处理 <hidden_event> 标签的主函数
    #
    # payload 的来源和合并逻辑与 npc_update 相同：
    #   XML 属性优先，body JSON 覆盖（GM 写 JSON 时更严谨）
    # -------------------------------------------------------
    """Process <hidden_event> tag — implicit story state with a fuse.

    Two modes:
      1. Create: requires `kind` in attrs (or in JSON body). Subject/severity/
         description/consequence are optional; defaults applied.
      2. Resolve: attrs has `resolve` (any value) or `type="resolve"`. Marks
         all currently-active rows for the given subject as resolved.

    Tolerant input: payload may live in attrs OR be JSON in body. Body wins
    on conflict because GM tends to be more deliberate when emitting JSON.
    """
    payload: dict = {}
    payload.update({k: v for k, v in (attrs or {}).items()})  # 先读 XML 属性
    body = (content or "").strip()
    if body:
        parsed = parse_loose_json(body)  # 尝试把 body 当 JSON 解析
        if isinstance(parsed, dict):
            payload.update(parsed)  # body JSON 覆盖同名属性

    # -------------------------------------------------------
    # 判断是"解决"操作还是"创建"操作
    # 有 "resolve" 键（任意值）或 type="resolve" → 解决模式
    # -------------------------------------------------------
    is_resolve = (
        "resolve" in payload
        or str(payload.get("type", "")).strip().lower() == "resolve"
    )
    if is_resolve:
        # 解决已有隐藏事件
        subject = str(payload.get("subject", "")).strip()
        if not subject:
            return  # 没有指定 subject，无法定位要解决哪个事件，跳过

        # 查找所有匹配 subject 的活跃隐藏事件
        stmt = select(HiddenEvent).where(
            HiddenEvent.session_id == session_id,
            HiddenEvent.subject == subject,
            HiddenEvent.status == "active",
        )
        rows = (await session.execute(stmt)).scalars().all()
        if not rows:
            return  # silent skip — non-existent subject is not an error

        resolution = str(payload.get("resolution", "")).strip()  # 解决方式描述
        for ev in rows:
            ev.status = "resolved"          # 标记为已解决
            ev.resolved_turn = current_turn # 记录在哪个回合解决的
            if resolution:
                ev.resolution = resolution  # 保存解决方式
        return

    # -------------------------------------------------------
    # 创建新隐藏事件
    # kind 是必需字段，标识事件的类别（如 "time_pressure"/"surveillance"/"trap" 等）
    # -------------------------------------------------------
    kind = str(payload.get("kind", "")).strip()
    if not kind:
        return  # invalid create — kind is required

    # severity（严重程度）：1=轻微，2=中等，3=严重；超出范围则截断
    try:
        severity = int(payload.get("severity", 2) or 2)
    except (TypeError, ValueError):
        severity = 2
    severity = max(1, min(3, severity))  # 限制在 [1, 3]

    # 字段长度截断，防止超长文本入库（数据库字段有长度限制）
    subject = str(payload.get("subject", "")).strip()[:120]
    kind = kind[:60]
    description = str(payload.get("description", ""))[:1000]     # 事件描述
    consequence = str(payload.get("consequence", ""))[:1000]     # 后果（如果不处理会发生什么）

    # -------------------------------------------------------
    # 去重检查
    #
    # 同一个 (subject, kind) 组合如果已有活跃记录，就更新而不是新增。
    # 这是因为 GM 可能在多个回合重复描述同一个隐藏威胁（措辞略有不同）。
    # 不去重的话，"炸弹倒计时"可能会在列表里出现 6 次，
    # 既污染提示词又让前端显示混乱。
    # -------------------------------------------------------
    # v0.1.9 dedup: same (subject, kind) already active → update instead of
    # inserting a new row. Fixes GM repeating the same hidden_event 6 times in a
    # single playthrough and polluting the implicit-state injection list.
    existing = (await session.execute(
        select(HiddenEvent).where(
            HiddenEvent.session_id == session_id,
            HiddenEvent.subject == subject,
            HiddenEvent.kind == kind,
            HiddenEvent.status == "active",
        )
    )).scalars().first()
    if existing is not None:
        # 已存在相同事件，更新描述而不是插入新行
        if description:
            existing.description = description
        if consequence:
            existing.consequence = consequence
        log.info(
            "hidden_event dedup: updating existing #%d (%s/%s) instead of inserting",
            existing.id, subject, kind,
        )
        return

    # 去重通过，创建新隐藏事件行
    ev = HiddenEvent(
        session_id=session_id,
        subject=subject,               # 事件主体（"炸弹"/"王欣"等）
        kind=kind,                     # 事件类别（"time_pressure"/"surveillance"等）
        severity=severity,             # 严重程度（1-3）
        description=description,       # 详细描述
        consequence=consequence,       # 不处理的后果
        introduced_turn=current_turn,  # 引入回合
        status="active",               # 初始状态为活跃（等待解决）
    )
    session.add(ev)
