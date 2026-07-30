# ============================================================
# state_apply 调度器（Dispatcher）
#
# 这是 state_apply 子系统的"总指挥"文件。
# 它本身不做任何具体的数据库写操作，而是：
#   1. 接收一个本回合解析到的标签列表（list[TagComplete]）
#   2. 根据每个标签的名字（tag.name），调用对应子模块的处理函数
#   3. 处理一些跨模块的收尾工作（如拓扑警告累积、NPC 出场标记）
#
# 【为什么要有调度器？】
# 各子模块只知道如何处理自己的标签，不知道其他标签的存在。
# 调度器把"有哪些标签"和"每种标签怎么处理"解耦开来，
# 未来增加新标签类型只需：
#   a) 写一个新的子模块 xxx.py，实现 _apply_xxx()
#   b) 在这里 import 并加一个 elif tag.name == "xxx" 分支
# ============================================================

"""state_apply dispatcher — routes parsed tags to per-domain handlers.

After the r4-a refactor, every handler lives in its own per-tag module
under `state_apply/`. This file now contains only:
  - `apply_tags(...)` — the dispatcher
  - re-exports for legacy callers that imported handler symbols from `_impl`
    directly (kept stable for `from state_apply._impl import *` users).
"""

import json
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession  # 异步数据库会话，不阻塞事件循环

# 从各子模块导入标签处理函数
from dzmm.db.models import NPC
from dzmm.parsing.events import TagComplete  # 一个已完整解析的 XML 标签（含 name/attrs/content）
from dzmm.service.state_apply.character_xp import _apply_character_xp  # XP 奖励
from dzmm.service.state_apply.hidden_event import _apply_hidden_event   # 隐藏事件（玩家不可见的故事伏笔）
from dzmm.service.state_apply.npc import (
    _NPC_REVEALABLE_FIELDS,    # 哪些 NPC 字段支持"逐步揭露"给玩家
    _apply_npc_update,         # NPC 创建 / 更新
    _auto_reveal_for_create,   # 新建 NPC 时自动标记已揭露字段
    _parse_reveal_attr,        # 解析 reveal="..." 属性
)
from dzmm.service.state_apply.npc_relation import _apply_npc_relation   # NPC 之间的关系
from dzmm.service.state_apply.pc_goal import _apply_pc_goal             # PC（玩家角色）目标
from dzmm.service.state_apply.pc_mood import _apply_pc_mood             # PC 情绪状态
from dzmm.service.state_apply.plot_event import _apply_plot_event       # 剧情线索 / 任务
from dzmm.service.state_apply.recall import _apply_recall               # NPC 回忆召回（下回合重注入档案）
from dzmm.service.state_apply.screenplay import (
    _apply_chapter_advance,          # 推进到下一章节
    _apply_ending,                   # 标记故事结局
    _apply_event_complete,           # 标记某个剧情事件完成（线性剧本 + 开放世界双路径）
    _apply_event_trigger,            # 开放世界：事件触发（pending → triggered）
    _apply_plot_turn,                # 剧情转折点（可能触发大纲重写）
)
from dzmm.service.state_apply.doom import _apply_doom                   # 末日时钟
from dzmm.service.state_apply.location import _apply_location_enter     # 进入新地点
from dzmm.service.state_apply.location_edge import _apply_location_edge # 地点间的空间关系边
from dzmm.service.state_apply.location_item import _apply_location_item # 地点内的道具
from dzmm.service.state_apply.state_change import _apply_state_change, _record_mechanic_warning  # 通用状态变更（JSON patch）
from dzmm.service.state_apply.world_time import _apply_time_advance     # 世界时间推进
from dzmm.service.state_apply.factions import _apply_faction_create, _apply_faction_change  # 派系系统
from dzmm.service.state_apply.mechanics import (  # v0.15 Batch 2+3: Python-engine mechanics
    _apply_attack,
    _apply_dice_request,
    _apply_initiative_request,
    _apply_item_use,
    _apply_skill_request,
)

log = logging.getLogger(__name__)

# Re-export for callers that imported these names from `_impl` directly
# (e.g. via the `from _impl import *` wildcard in __init__.py).
# 这些符号通过 __all__ 在通配符导入时暴露，维持旧接口不变
__all__ = [
    "_NPC_REVEALABLE_FIELDS",
    "_apply_npc_update",
    "_auto_reveal_for_create",
    "_parse_reveal_attr",
    "apply_tags",
]


async def _record_legacy_dice_warning(
    session: AsyncSession,
    session_id: int,
    current_turn: int,
) -> None:
    """Record a mechanic warning when the GM emits a legacy <dice> tag.

    The <dice> tag outcome is NOT applied to state (it never was — the tag is
    narrative-only). But we now explicitly warn the GM so they migrate to
    <skill_request> or <dice_request>.
    """
    await _record_mechanic_warning(session, session_id, {
        "turn": current_turn,
        "kind": "rejected_dice",
        "tag": "dice",
        "reason": "旧版 <dice> 不再被系统解析，请用 <skill_request> 或 <dice_request>",
    })


def _enforce_dice_outcome(tags: list[TagComplete]) -> None:
    # -------------------------------------------------------
    # 骰子结果校正函数
    #
    # 背景：GM（LLM）在叙事中会 emit 这样的标签：
    #   <dice pc_roll="12" mod="+3" dc="15" outcome="成功"/>
    # 但 LLM 有时会算错：明明 12+3=15 >= 15（成功），
    # 却把 outcome 写成"失败"，或反之。
    #
    # 这个函数遍历所有 dice 标签，用真实的数学运算重新判断结果，
    # 如果与 GM 声称的 outcome 不符，就原地纠正 tag.attrs["outcome"]。
    #
    # 为什么要纠正？
    # - 前端"骰子展示"组件会读取 outcome 字段来渲染动画和颜色
    # - "卡骰检测器"（stuck-dice detector）也依赖这个值
    # - 叙事文字已经写死了，无法改，但至少让数据层的值是正确的
    # -------------------------------------------------------
    """Correct dice outcome attrs where LLM arithmetic was wrong.

    The LLM may claim "成功" when roll+mod < dc (or vice versa). We re-compute
    from the numeric attrs and overwrite the outcome in-place so events_json
    stores the correct result. The narrative text is already written and can't
    be changed, but downstream consumers (frontend dice display, stuck-dice
    detector) see the authoritative value.
    """
    # 成功状态的所有可能写法（LLM 可能输出中英文混杂）
    _outcome_success = {"success", "成功", "succeed", "pass", "passed"}
    for tag in tags:
        if tag.name != "dice":  # 只处理 dice 标签，跳过其他
            continue
        attrs = tag.attrs or {}
        try:
            pc_roll = int(attrs.get("pc_roll", 0))   # 玩家骰出的原始数字
            dc = int(attrs.get("dc", 0))              # 难度等级（Difficulty Class）
            # mod 可能是 "+3" 或 "-2" 这样的字符串，先去掉加号再转整数
            mod_raw = str(attrs.get("mod", "0")).replace("+", "")
            mod = int(mod_raw) if mod_raw.lstrip("-").isdigit() else 0
        except (TypeError, ValueError):
            continue  # 属性值非数字时跳过，不崩溃
        if pc_roll <= 0 or dc <= 0:
            continue  # 缺少必要数值，无法判断，跳过
        total = pc_roll + mod   # 玩家实际投出的总点数
        correct = "成功" if total >= dc else "失败"  # 数学上正确的结果
        claimed = (attrs.get("outcome") or "").strip()  # GM 声称的结果
        # 把 GM 输出的各种"成功"写法统一成"成功"，方便比对
        if claimed.lower() in _outcome_success:
            claimed_normalized = "成功"
        else:
            claimed_normalized = "失败"
        if claimed_normalized != correct:
            # GM 算错了，记录警告并纠正
            log.warning(
                "dice outcome corrected: roll=%d mod=%d total=%d dc=%d "
                "LLM_claimed=%r corrected_to=%r",
                pc_roll, mod, total, dc, claimed, correct,
            )
            tag.attrs["outcome"] = correct
            tag.attrs["outcome_corrected"] = "true"  # 标记"已被系统纠正"，供前端调试用
        elif claimed not in ("成功", "失败"):
            # GM 用英文写了 outcome，但算对了；统一转成中文
            tag.attrs["outcome"] = correct


async def apply_tags(
    session: AsyncSession,  # SQLAlchemy 异步会话，用来查询和修改数据库
    session_id: int,        # 当前游戏局的 ID
    current_turn: int,      # 当前回合编号
    tags: list[TagComplete], # 本回合 GM 输出中解析到的所有 XML 标签
) -> list[TagComplete]:
    # -------------------------------------------------------
    # 核心公共入口：把本回合所有标签应用到数据库
    #
    # 调用方（通常是 FastAPI 路由或消息处理器）负责事务管理：
    # 它们在 apply_tags 返回后调用 session.commit()。
    # apply_tags 本身只做写操作，不提交事务。
    #
    # 执行顺序：
    #   1. 纠正骰子结果（_enforce_dice_outcome）
    #   2. 遍历所有标签，按名字分发到对应子模块
    #   3. 累积地点拓扑警告（如果 GM 跳跃地点时缺少 location_edge）
    #   4. 根据叙事内容自动更新 NPC 出场时间（_bump_appearances_from_narrative）
    # -------------------------------------------------------
    """Mutate state and return only tags accepted by authoritative handlers."""
    _enforce_dice_outcome(tags)  # 先纠正骰子结果，后续所有处理都用纠正后的值
    topology_warnings: list[str] = []  # 收集本回合的地点拓扑警告
    accepted_tags: list[TagComplete] = []
    for tag in tags:
        accepted = True
        # 根据标签名路由到对应处理函数
        if tag.name == "state_change":
            # 通用状态变更，content 是 JSON patch 字符串
            accepted = await _apply_state_change(
                session, session_id, tag.content, current_turn,
            )
        elif tag.name == "npc_update":
            # NPC 信息更新（创建或修改），attrs 含 name/favor_delta/state 等
            await _apply_npc_update(
                session, session_id, current_turn, tag.attrs, tag.content
            )
        elif tag.name == "plot_event":
            # 剧情事件（任务/钩子/重大事件），写入 PlotThread 表
            await _apply_plot_event(session, session_id, current_turn, tag.attrs, tag.content)
        elif tag.name == "character_xp":
            # PC 经验值奖励，attrs 含 delta="N"
            await _apply_character_xp(session, session_id, tag.attrs, tag.content)
        elif tag.name == "recall":
            # 通知系统下回合重新把某 NPC 的完整档案注入 GM 提示词
            await _apply_recall(session, session_id, tag.attrs, tag.content)
        elif tag.name == "pc_goal":
            # 玩家角色的当前目标/任务
            await _apply_pc_goal(session, session_id, current_turn, tag.attrs, tag.content)
        elif tag.name == "pc_mood":
            # PC 情绪变化，content 是 JSON 格式的情绪增量
            await _apply_pc_mood(session, session_id, tag.content)
        elif tag.name == "npc_relation":
            # NPC 之间的关系（好友/仇敌/家人等）
            await _apply_npc_relation(
                session, session_id, current_turn, tag.attrs, tag.content
            )
        elif tag.name == "hidden_event":
            # 隐藏事件：玩家看不见但会影响未来剧情的内部状态（如"炸弹倒计时"）
            await _apply_hidden_event(
                session, session_id, current_turn, tag.attrs, tag.content
            )
        elif tag.name == "chapter_advance":
            # 推进到剧本的下一章节
            accepted = await _apply_chapter_advance(
                session, session_id, tag.attrs, current_turn
            )
        elif tag.name == "event_complete":
            # 标记某个剧情事件已完成；线性剧本路径自动奖励 XP，开放世界路径推进 Campaign 阶段
            accepted = await _apply_event_complete(
                session, session_id, tag.attrs, current_turn
            )
        elif tag.name == "event_trigger":
            # 开放世界：Director 声明某候选事件已在叙事中发生（pending/triggered → triggered）
            accepted = await _apply_event_trigger(
                session, session_id, tag.attrs, current_turn
            )
        elif tag.name == "plot_turn":
            # 剧情重大转折，可能触发大纲自动重写
            accepted = await _apply_plot_turn(
                session, session_id, tag.attrs, current_turn
            )
        elif tag.name == "ending":
            # 故事结局，将剧本标记为 "concluded"
            accepted = await _apply_ending(
                session, session_id, tag.attrs, current_turn
            )
        elif tag.name == "doom":
            # 末日时钟增减，attrs 含 delta="±N"
            await _apply_doom(session, session_id, tag.attrs)
        elif tag.name == "location_enter":
            # 进入新地点；如果缺少空间关系边，会返回警告字符串
            w = await _apply_location_enter(
                session, session_id, current_turn, tag.attrs, tag.content
            )
            accepted = bool((tag.attrs or {}).get("name")) and not (
                w and "地点登记被拒绝" in w
            )
            if w:
                topology_warnings.append(w)  # 收集警告，稍后写入数据库
        elif tag.name == "location_edge":
            # 声明两个地点之间的空间关系（相邻/包含/连接）
            await _apply_location_edge(session, session_id, tag.attrs, current_turn)
        elif tag.name == "location_item":
            # 在地点里增加或修改道具
            await _apply_location_item(session, session_id, current_turn, tag.attrs, tag.content)
        elif tag.name == "time_advance":
            # 推进世界内的时间（小时/天/周等）
            await _apply_time_advance(session, session_id, tag.attrs)
        elif tag.name == "faction_create":
            # 创建一个新派系（势力/组织）
            await _apply_faction_create(session, session_id, tag.attrs, tag.content)
        elif tag.name == "faction_change":
            # 修改派系的状态/属性
            await _apply_faction_change(session, session_id, tag.attrs)
        # v0.15 Batch 2 — Python-engine mechanics tags
        elif tag.name == "dice_request":
            # GM asks Python to roll; result appended to pending_resolutions_json
            await _apply_dice_request(session, session_id, tag.attrs, current_turn)
        elif tag.name == "skill_request":
            # GM asks Python to perform skill check
            await _apply_skill_request(session, session_id, tag.attrs, current_turn)
        elif tag.name == "item_use":
            # GM signals player consumed/used an item
            await _apply_item_use(session, session_id, tag.attrs, current_turn)
        # v0.15 Batch 3 — combat resolution tags
        elif tag.name == "attack":
            # GM triggers a single attack roll + damage resolution
            await _apply_attack(session, session_id, tag.attrs, current_turn)
        elif tag.name == "initiative_request":
            # GM triggers initiative rolling for a list of combatants
            await _apply_initiative_request(session, session_id, tag.attrs, current_turn)
        elif tag.name == "say":
            # Auto-create NPC row when GM uses <say speaker="..."> for an unknown speaker.
            await _apply_say(session, session_id, tag.attrs, current_turn)
        elif tag.name == "dice":
            # v0.54: legacy <dice> tag — outcome is NOT applied to state.
            # _enforce_dice_outcome above already corrects arithmetic; dice_monitor
            # uses extract_d20_value for stuck-dice detection (both safe to keep).
            # Record a warning so _build_key_facts can surface it to the GM.
            await _record_legacy_dice_warning(session, session_id, current_turn)
        if accepted:
            accepted_tags.append(tag)

    # -------------------------------------------------------
    # 拓扑警告写回数据库
    #
    # 如果本回合出现了"地点跳跃但缺少 LocationEdge"的问题，
    # 把警告字符串追加到 Session.topology_warning_json（最多保留 5 条）。
    # 下回合构建 GM 提示词时（_build_key_facts），会把这些警告注入 prompt，
    # 强制 GM 在下一回合补发 <location_edge> 标签来修复地图拓扑。
    # -------------------------------------------------------
    # v0.10 T12 — accumulate topology warnings into Session.topology_warning_json
    # so the next turn's _build_key_facts can drain & inject them into the prompt,
    # forcing the GM to emit the missing <location_edge>.
    if topology_warnings:
        from dzmm.db.models import Session as GameSession
        sess = await session.get(GameSession, session_id)
        if sess is not None:
            try:
                existing = json.loads(sess.topology_warning_json or "[]")
                if not isinstance(existing, list):
                    existing = []
            except (TypeError, ValueError):
                existing = []
            existing.extend(topology_warnings)
            # 只保留最近 5 条警告，避免无限膨胀
            sess.topology_warning_json = json.dumps(
                existing[-5:], ensure_ascii=False
            )

    # -------------------------------------------------------
    # 自动更新 NPC 出场时间（Post-pass）
    #
    # 铁规则 17：GM 只在 NPC 首次出现时 emit <npc_update>。
    # 问题：向导（wizard）预先固定的 NPC 之后再出场，不会触发 npc_update，
    # 导致 last_seen_turn 永远停在 0，前端面板一直显示"未登场"。
    #
    # 解决方案：在应用完所有标签之后，扫描本回合所有叙事性文本内容，
    # 如果某个 NPC 的名字出现在文本中，就把它的 last_seen_turn 更新到当前回合。
    # -------------------------------------------------------
    # Post-pass: mark "appeared" for any NPC whose name shows up in this
    # turn's narrative / say / reaction / dice scene content (or in say /
    # reaction speaker= attrs). The GM only emits <npc_update> for first-time
    # named NPCs (iron rule 17) — pre-pinned NPCs from the wizard never get
    # a fresh npc_update, so without this pass their last_seen_turn stays
    # 0 and the panel keeps showing 未登场 even when they're actively in
    # the scene.
    await _bump_appearances_from_narrative(session, session_id, current_turn, tags)
    return accepted_tags


async def _bump_appearances_from_narrative(
    session: AsyncSession,
    session_id: int,
    current_turn: int,
    tags: list[TagComplete],
) -> None:
    # -------------------------------------------------------
    # 从叙事文本中自动识别 NPC 出场
    #
    # 策略：
    # 1. 把本回合所有"叙事类"标签（narrative/say/reaction/scene/dice/pc_action）
    #    的文本内容和 speaker 属性拼成一个大字符串（haystack）
    # 2. 遍历数据库中所有 NPC，检查名字是否出现在 haystack 里
    # 3. 支持后缀匹配：如果 NPC 全名是"记者王欣"，haystack 里出现"王欣"也算匹配
    #    （因为 GM 有时用简称，而数据库里存的是全称）
    # -------------------------------------------------------
    npcs = (
        await session.execute(
            select(NPC).where(NPC.session_id == session_id)
        )
    ).scalars().all()
    if not npcs:
        return  # 没有 NPC 时直接返回，避免无意义循环

    # Concatenate every visible narrative-ish surface from the turn. Speaker
    # attrs go in too (a `<say speaker="丽莎">` is a clear appearance).
    haystacks: list[str] = []
    for tag in tags:
        # 只从叙事类标签里提取文本（system 标签、state 标签等不含角色名）
        if tag.name in ("narrative", "say", "reaction", "scene", "dice", "pc_action"):
            if tag.content:
                haystacks.append(tag.content)
            # say/reaction 标签有 speaker 属性，也算出场
            speaker = tag.attrs.get("speaker") if tag.attrs else None
            if speaker:
                haystacks.append(speaker)
    haystack = "\n".join(haystacks)  # 拼成一个大文本供搜索
    if not haystack:
        return  # 本回合没有叙事内容，跳过

    for npc in npcs:
        name = (npc.name or "").strip()
        if len(name) < 2:
            continue  # skip 1-char names — too risky to false-positive on
        # Match full name OR any 2+ char suffix (handles "记者王欣" → "王欣").
        matched = name in haystack
        if not matched and len(name) > 2:
            # 尝试从名字第 1、2、3... 个字符开始的后缀
            for start in range(1, len(name) - 1):
                if name[start:] in haystack:
                    matched = True
                    break
        # 只有当 last_seen_turn 还没更新到当前回合时才写入，避免重复赋值
        if matched and (npc.last_seen_turn or 0) < current_turn:
            npc.last_seen_turn = current_turn


async def _apply_say(
    session: AsyncSession,
    session_id: int,
    attrs: dict | None,
    current_turn: int,
) -> None:
    """Auto-create an NPC row when GM emits <say speaker="..."> for an unknown name.

    This ensures that NPCs introduced purely through dialogue (without a prior
    <npc_update>) are tracked in the NPC table and will receive dossier injection
    on the next turn. The auto-created row uses safe defaults; the GM can refine
    them later via <npc_update>.

    Non-fatal: any exception during NPC creation is caught and logged.
    """
    if not attrs:
        return
    speaker = (attrs.get("speaker") or "").strip()
    if not speaker:
        return  # empty or whitespace-only speaker — nothing to do

    # Skip if the speaker is the PC themselves; the PC has its own Character
    # row and should never appear in the NPC table.
    try:
        from dzmm.db.models import Character as _Character, Session as _Session
        sess_row = await session.get(_Session, session_id)
        if sess_row is not None and sess_row.character_id is not None:
            pc_row = await session.get(_Character, sess_row.character_id)
            if pc_row is not None and pc_row.name and pc_row.name.strip() == speaker:
                return
    except Exception:  # noqa: BLE001
        pass  # best-effort guard; fall through to NPC creation logic

    try:
        # Check whether this NPC already exists to avoid duplicates.
        existing = (
            await session.execute(
                select(NPC).where(
                    NPC.session_id == session_id,
                    NPC.name == speaker,
                )
            )
        ).scalar_one_or_none()

        if existing is not None:
            return  # already tracked — nothing to do

        npc = NPC(
            session_id=session_id,
            name=speaker,
            state="alive",
            favor=0,
            description="",
            emotion_json="{}",
            affinity_json="{}",
            last_seen_turn=current_turn,
            current_location=None,
            purpose="",
            archetype="neutral",
            pinned=False,
            revealed_json='{"name": true}',
        )
        session.add(npc)
        log.info(
            "_apply_say: auto-created NPC %r in session %d (first appearance via <say>)",
            speaker,
            session_id,
        )
    except Exception:  # noqa: BLE001
        log.warning(
            "_apply_say: failed to auto-create NPC %r in session %d — skipping",
            speaker,
            session_id,
            exc_info=True,
        )
