# ============================================================
# NPC 状态更新模块
#
# 负责处理 <npc_update> XML 标签，该标签是 GM 用来创建或修改 NPC 信息的。
#
# 典型的 GM 输出示例：
#   <npc_update name="记者王欣" favor_delta="+2" state="对PC友好" reveal="description,favor"/>
#   <npc_update name="老陈">{"description": "身形消瘦的老人", "archetype": "知情者"}</npc_update>
#
# 【逐步揭露（Progressive Reveal）系统】
# 每个 NPC 有一个 revealed_json 字段，记录哪些属性已经对玩家可见。
# 例如 NPC 的真实目的（purpose）可能在故事初期是隐藏的，
# 直到 GM 通过 reveal="purpose" 显式解锁，玩家才能在面板里看到。
#
# 自动揭露规则：
# - 如果 GM 在标签里给某字段赋了值，该字段自动标记为"已揭露"
#   （逻辑：GM 把信息写进叙事，玩家已经看到了）
# - GM 也可以用 reveal="field1,field2" 显式揭露字段
# ============================================================

"""NPC-related state_apply handlers.

Carved out of `_impl.py` in r3-a. Covers:
  - <npc_update> handler + progressive-reveal bookkeeping

The dispatcher (`apply_tags` in `_impl.py`) imports the handlers below;
shared helpers (e.g. `_normalize_for_dedup`) remain in `_impl.py`.
"""

import json
import logging
import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.db.models import NPC
from dzmm.parsing.repair import parse_loose_json  # 宽松 JSON 解析，容忍 LLM 输出的不规范格式

log = logging.getLogger(__name__)


# 支持"逐步揭露"的字段白名单
# 只有这些字段可以通过 reveal="..." 属性解锁给玩家
# 不在此列表里的字段名会被静默忽略，避免 GM 乱填字段名搞崩数据
# v0.11 progressive reveal: only these field names can be marked revealed.
# Unknown reveal targets are silently ignored. "name" is always revealed
# implicitly (defaulted in revealed_json), but listing it here is harmless.
_NPC_REVEALABLE_FIELDS = frozenset({
    "name", "description", "purpose", "archetype",
    "state", "favor", "affinity", "emotion",
})

# 用于把 reveal="description, state favor" 这样的字符串切割成列表的正则
# 支持逗号、空格或两者混合分隔
_REVEAL_SPLIT_RE = re.compile(r"[,\s]+")


# 性别字段合法值（数据库只存 "male" / "female" / ""）
_GENDER_VALID = {"male", "female"}
# 把 GM 可能输出的各种性别写法统一映射到标准值
_GENDER_ALIAS = {
    "男": "male", "男性": "male", "m": "male", "boy": "male", "man": "male",
    "女": "female", "女性": "female", "f": "female", "girl": "female", "woman": "female",
}


def _normalize_gender_str(raw: object) -> str:
    # 把 GM 输出的性别值（可能是中文/英文/大小写混合）统一成 "male"/"female"/""
    # 返回空字符串表示"未知"或"不合法"，不会写入数据库
    # 注意：这里故意没有导入 service.wizard 模块里的同名函数，
    # 因为 state_apply 是比 wizard 更底层的模块，不应反向依赖
    """Coerce a payload gender value to "male"/"female"/"" — same enum as
    `service.wizard._normalize_gender`. Duplicated locally to avoid a
    state_apply→service.wizard import (state_apply is the lower layer)."""
    if not raw:
        return ""
    s = str(raw).strip().lower()
    if not s:
        return ""
    if s in _GENDER_VALID:   # 已经是标准值，直接返回
        return s
    return _GENDER_ALIAS.get(s, "")  # 查别名表；找不到则返回空字符串


def _auto_reveal_for_create(payload: dict) -> dict:
    # -------------------------------------------------------
    # 新建 NPC 时的自动揭露逻辑
    #
    # 当 GM 第一次 emit 某个 NPC 的 npc_update 标签时，
    # 凡是这次 payload 里有值的字段，都应该自动标记为"玩家已见"，
    # 因为 GM 在叙事里描述这个 NPC 时，玩家当然已经看到了这些信息。
    #
    # 返回一个 revealed_json 的初始值，例如：
    #   {"name": true, "description": true, "state": true}
    # -------------------------------------------------------
    """When creating a new NPC, fields whose value is being set in the same
    payload (description / state / archetype / purpose / favor_delta / etc.)
    should be auto-marked revealed=true — the GM is writing them now, so the
    player has just seen them.

    name is always revealed (the GM has to name an NPC for them to exist)."""
    # name 永远揭露：GM 在叙事里说出了这个名字，玩家肯定已经知道
    revealed = {"name": True}
    # 这些文本字段：只要 payload 里有值就自动揭露
    for f in ("description", "state", "archetype", "purpose"):
        if payload.get(f):
            revealed[f] = True
    # 好感度：如果本次就调整了好感，说明玩家已经能感受到
    if payload.get("favor_delta") is not None:
        revealed["favor"] = True
    # 亲密度轴：同上
    if payload.get("affinity"):
        revealed["affinity"] = True
    # 情绪轴：同上
    if payload.get("emotion"):
        revealed["emotion"] = True
    return revealed


def _parse_reveal_attr(reveal_str: str) -> list[str]:
    # 解析 reveal="description, state favor" 属性字符串
    # 返回经过白名单过滤后的字段名列表
    # 不在白名单里的字段名会被静默丢弃（不报错，避免 GM 拼写错误导致崩溃）
    """Split a reveal="..." attribute into a list of recognised field names.
    Accepts commas, whitespace, or both as separators. Unknown fields are
    silently dropped."""
    if not reveal_str:
        return []
    fields = [f.strip() for f in _REVEAL_SPLIT_RE.split(reveal_str) if f.strip()]
    return [f for f in fields if f in _NPC_REVEALABLE_FIELDS]  # 白名单过滤


async def _apply_npc_update(
    session: AsyncSession,   # 数据库会话
    session_id: int,         # 当前游戏局
    current_turn: int,       # 当前回合
    attrs: dict[str, str],   # XML 属性（name/favor_delta/state 等），值都是字符串
    raw: str,                # 标签 body 中的 JSON 文本（可能为空）
) -> None:
    # -------------------------------------------------------
    # 核心处理函数：解析 <npc_update> 标签，创建或更新 NPC 行
    #
    # payload 来源有两个：
    #   1. XML 属性（attrs）：<npc_update name="王欣" favor_delta="+2"/>
    #   2. 标签 body 里的 JSON：<npc_update>{"description": "...","state": "..."}</npc_update>
    # 两者合并，body JSON 优先（GM 写 JSON 时更严谨）
    # -------------------------------------------------------
    # Merge attrs with body JSON. Body wins on conflict (GM is more deliberate
    # when it serialises a JSON payload than when it inlines attrs).
    payload: dict = {}
    payload.update({k: v for k, v in (attrs or {}).items()})  # 先载入 XML 属性
    body_payload = parse_loose_json(raw)  # 尝试把 body 当 JSON 解析（宽松模式）
    if body_payload:
        payload.update(body_payload)  # body JSON 覆盖同名属性

    # name 是必需字段，没有 name 就无法定位或创建 NPC
    name = payload.get("name")
    if not name:
        return
    name = str(name).strip()
    if not name:
        return

    # 精确匹配：先按名字在数据库里找这个 NPC
    npc = (
        await session.execute(
            select(NPC).where(NPC.session_id == session_id, NPC.name == name)
        )
    ).scalar_one_or_none()

    # -------------------------------------------------------
    # 模糊匹配回退
    #
    # 问题：GM 有时用简称"王欣"，但数据库里存的是"记者王欣"（全名）。
    # 精确匹配失败后，尝试子字符串匹配：
    #   - payload 里的名字是数据库名字的子串（"王欣" ∈ "记者王欣"）
    #   - 或者数据库名字是 payload 名字的子串（反向）
    # 取第一个匹配到的 NPC
    # -------------------------------------------------------
    # Fuzzy fallback: LLM may use a short name ("王欣") while the DB stores
    # the full name ("记者王欣"). If exact match fails, find any NPC whose DB
    # name contains the given name as a substring, or vice-versa.
    if npc is None and len(name) >= 2:
        candidates = (await session.execute(
            select(NPC).where(NPC.session_id == session_id)
        )).scalars().all()
        for cand in candidates:
            cname = (cand.name or "").strip()
            if cname and (name in cname or cname in name):
                log.info("npc_update fuzzy match: %r → %r", name, cname)
                npc = cand
                break

    # 解析 reveal 属性（需要在 is_create 判断之前做）
    reveal_fields = _parse_reveal_attr(str(payload.get("reveal", "")))

    is_create = npc is None  # 数据库里还没有这个 NPC → 需要新建
    if is_create:
        # -------------------------------------------------------
        # 特殊情况：纯揭露操作对不存在的 NPC 是无意义的空操作
        #
        # 如果 payload 里只有 name 和 reveal（没有任何实质内容字段），
        # 不应该凭空创建一个空壳 NPC——这很可能是 GM 拼写错了名字。
        # 只有当 payload 包含实质字段（description/state/...）时才创建。
        # -------------------------------------------------------
        # Special case: a payload that ONLY carries a reveal=... directive
        # against a non-existent NPC is a silent no-op. The intent is
        # "unlock previously-hidden fields"; without an existing NPC, there's
        # nothing to unlock and we don't fabricate a stub from a typo.
        # Any other shape (name only, name + value fields, etc.) creates.
        keys_other_than_name_and_reveal = [
            k for k in payload.keys() if k not in ("name", "reveal")
        ]
        if reveal_fields and not keys_other_than_name_and_reveal:
            return  # 只有 reveal 指令但 NPC 不存在，静默跳过

        # 创建新 NPC 行，字段赋默认值
        npc = NPC(
            session_id=session_id,
            name=name,
            gender=_normalize_gender_str(payload.get("gender")),  # 性别（标准化）
            description=payload.get("description", ""),            # NPC 描述
            favor=0,                                                # 初始好感度为 0
            state=payload.get("state", "未知"),                    # 当前状态
            last_seen_turn=current_turn,                            # 第一次出场回合
            notes_json="[]",                                        # GM 备注列表
            purpose="",                                             # 存在目的（可能是隐藏信息）
            archetype="",                                           # NPC 类型（知情者/敌人/...）
            affinity_json="{}",                                     # 多维度亲密度
            pinned=False,                                           # 未固定（向导预置 NPC 会设为 True）
            revealed_json=json.dumps(
                _auto_reveal_for_create(payload), ensure_ascii=False  # 初始化揭露状态
            ),
        )
        session.add(npc)  # 把新 NPC 对象加入会话（稍后随 commit 写入数据库）

    # -------------------------------------------------------
    # 更新好感度（favor）
    #
    # favor_delta 是相对增量（正/负整数），不是绝对值。
    # 这样设计是因为 GM 不需要知道当前的好感度是多少，
    # 只需要声明"这次交互让 NPC 对 PC 好感增加 2"。
    # -------------------------------------------------------
    favor_delta_raw = payload.get("favor_delta", 0)
    favor_delta_num = 0
    if isinstance(favor_delta_raw, bool):
        favor_delta_num = 0  # True/False 不是合法的 delta，忽略
    elif isinstance(favor_delta_raw, (int, float)):
        favor_delta_num = int(favor_delta_raw)
    elif isinstance(favor_delta_raw, str):
        # XML 属性全部是字符串，例如 favor_delta="+2"，需要转换为整数
        try:
            favor_delta_num = int(favor_delta_raw)
        except ValueError:
            favor_delta_num = 0
    if favor_delta_num:
        npc.favor += favor_delta_num  # 累加到当前好感度

    # 更新状态描述（例如"对PC友好" → "因冲突开始疑虑PC"）
    if "state" in payload and payload["state"] is not None:
        npc.state = str(payload["state"])

    # 更新外貌/背景描述，但只在原来为空时才写入（不覆盖已有描述）
    if "description" in payload and not npc.description:
        npc.description = str(payload["description"])

    # 更新 NPC 在故事中的存在目的（可能是隐藏信息，要配合 reveal 使用）
    purpose = payload.get("purpose")
    if purpose is not None:
        npc.purpose = str(purpose)

    # 更新 NPC 原型/类型（如"守护者"/"阻碍者"/"引路人"等叙事功能标签）
    archetype = payload.get("archetype")
    if archetype is not None:
        npc.archetype = str(archetype)

    # -------------------------------------------------------
    # 更新性别
    #
    # 只在数据库里当前没有性别时才写入（避免覆盖）。
    # 原因：中途改变 NPC 性别会破坏故事一致性，
    # 很可能是 GM 在不同回合重复描述同一 NPC 时的笔误。
    # -------------------------------------------------------
    # Gender — only set if currently empty (legacy data); never overwrite an
    # existing male/female assignment from a later GM emit, since flipping
    # gender mid-story corrupts continuity.
    if not (npc.gender or "").strip():
        new_gender = _normalize_gender_str(payload.get("gender"))
        if new_gender:
            npc.gender = new_gender

    # -------------------------------------------------------
    # 更新多维度亲密度（affinity）
    #
    # affinity 是一个字典，键是自定义轴名（GM 自由定义），
    # 值是该轴上的累计分数。例如：
    #   {"信任度": 30, "浪漫": 10}
    # payload 里也是字典，表示增量，会累加到已有值上。
    # -------------------------------------------------------
    affinity_delta = payload.get("affinity")
    if isinstance(affinity_delta, dict):
        existing = json.loads(npc.affinity_json or "{}")
        if not isinstance(existing, dict):
            existing = {}
        for axis, delta in affinity_delta.items():
            if not isinstance(delta, (int, float)):
                continue  # 非数字的值跳过
            axis_key = str(axis)
            existing[axis_key] = int(existing.get(axis_key, 0)) + int(delta)
        npc.affinity_json = json.dumps(existing, ensure_ascii=False)

    # -------------------------------------------------------
    # 更新情绪状态（emotion）
    #
    # 情绪使用固定的五个轴，每轴范围 0-100，通过 delta 累加变化：
    #   anger（愤怒）/ love（爱）/ fear（恐惧）/ respect（尊重）/ jealousy（嫉妒）
    #
    # 为什么用固定轴？
    # - 便于前端渲染五维雷达图
    # - 防止 GM 随意发明轴名导致数据混乱
    # - 五个维度覆盖了跑团中最常见的人物情感关系
    # -------------------------------------------------------
    emotion_delta = payload.get("emotion")
    if isinstance(emotion_delta, dict):
        emotions = json.loads(npc.emotion_json or "{}")
        if not isinstance(emotions, dict):
            emotions = {}
        for axis, delta in emotion_delta.items():
            # 只接受白名单内的情绪轴，未知轴名静默忽略
            if axis not in ("anger", "love", "fear", "respect", "jealousy"):
                continue
            if not isinstance(delta, (int, float)):
                continue
            new_val = int(emotions.get(axis, 0) + delta)
            # 强制限制在 [0, 100] 范围，防止情绪值溢出
            emotions[axis] = max(0, min(100, new_val))
        npc.emotion_json = json.dumps(emotions, ensure_ascii=False)

    # 更新 NPC 当前所在地点（场景绑定）
    # v0.2.6: scene binding — sets or clears NPC's current location.
    if "location" in payload:
        loc_val = payload["location"]
        if isinstance(loc_val, str):
            npc.current_location = loc_val.strip() or None  # 空字符串视为"清除位置"
        else:
            npc.current_location = None

    # 添加 GM 备注（note）——用于记录重要的剧情笔记
    note = payload.get("note")
    if note:
        notes = json.loads(npc.notes_json or "[]")
        notes.append({"turn": current_turn, "text": str(note)})  # 带回合号的备注
        npc.notes_json = json.dumps(notes, ensure_ascii=False)
    npc.last_seen_turn = current_turn  # 更新最后出场回合

    # -------------------------------------------------------
    # 更新逐步揭露状态（revealed_json）
    #
    # 两个来源合并：
    #   1. 本次 payload 里有值的字段 → 自动标记为已揭露
    #      （GM 把这个字段写进了叙事，玩家已经看到了）
    #   2. reveal="field1,field2" 属性里显式列出的字段 → 手动揭露
    #
    # 只增不减：已揭露的字段不会被重新隐藏。
    # -------------------------------------------------------
    # Progressive reveal bookkeeping. Two sources merge into revealed_json:
    #   1. fields that have a concrete value in this payload
    #      (auto-revealed: GM just wrote them, so the player has seen them)
    #   2. names listed in the reveal="..." attribute
    # Both add to the existing set; never clear what was previously revealed.
    try:
        revealed = json.loads(npc.revealed_json or '{"name": true}')
        if not isinstance(revealed, dict):
            revealed = {"name": True}
    except (TypeError, ValueError):
        revealed = {"name": True}  # 数据损坏时用默认值兜底

    # Auto-reveal: any field with a meaningful value in this update was visible
    # to the player when the GM emitted it — mark revealed. (For updates only;
    # create path already auto-revealed via _auto_reveal_for_create above.)
    if not is_create:
        # 更新路径下：有值的字段自动揭露（创建路径已经在上面处理过了）
        if payload.get("description"):
            revealed["description"] = True
        if payload.get("state") not in (None, ""):
            revealed["state"] = True
        if payload.get("archetype"):
            revealed["archetype"] = True
        if payload.get("purpose"):
            revealed["purpose"] = True
        if payload.get("favor_delta") is not None and favor_delta_num:
            revealed["favor"] = True
        if payload.get("affinity"):
            revealed["affinity"] = True
        if payload.get("emotion"):
            revealed["emotion"] = True

    # 合并 reveal 属性里显式声明的字段
    for f in reveal_fields:
        revealed[f] = True

    npc.revealed_json = json.dumps(revealed, ensure_ascii=False)  # 写回数据库
