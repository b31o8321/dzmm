# ============================================================
# routes_sessions 公共工具模块
# ============================================================
# 【模块作用】
#   这是整个 routes_sessions 包的"公共工具箱"，提供三类东西：
#   1. 依赖注入占位符（get_session_dep / get_session_maker_dep）
#      ——由 main.py 在应用启动时用真实实现替换
#   2. 公共辅助函数（_to_out / _parse_events_json / _npc_to_dict）
#      ——各路由模块共用，避免重复代码
#   3. 级联删除函数（delete_session_cascade）
#      ——删存档时清理所有关联数据
#
# 【为什么用占位符而不直接导入？】
#   数据库连接的创建方式（SQLite/PostgreSQL、连接池参数等）由 main.py 决定。
#   路由模块不应该硬编码"如何获取数据库连接"，只需声明"我需要一个连接"。
#   FastAPI 的 Depends() 机制会在每个请求到来时自动调用这些函数获取连接。
#   这种模式叫"依赖注入（Dependency Injection）"，与 Spring 的 @Autowired 思路相同。
# ============================================================
import json

from sqlalchemy import delete, select           # SQLAlchemy 的 SQL 构造工具
from sqlalchemy.ext.asyncio import AsyncSession  # 异步数据库会话类型

from dzmm.db.models import NPC
from dzmm.models.factory import build_client  # noqa: F401 — re-exported
# _effective_reveals: 根据 NPC 好感度/条件计算哪些字段对玩家可见
from dzmm.service.npc_dossier import _effective_reveals

# __all__ 声明本模块对外公开的名字
# 当别的模块 `from _common import *` 时，只导入这些
__all__ = [
    "get_session_dep",
    "get_session_maker_dep",
    "build_client",
    "_to_out",
    "_parse_events_json",
    "_npc_to_dict",
    "delete_session_cascade",
]


# ── 依赖注入占位符 ──────────────────────────────────────────────────────
# 这两个函数是"占位符"——它们本身会抛出异常，意味着不能在没有替换的情况下运行。
# main.py 启动时会用真正的实现（返回 AsyncSession 的异步生成器）覆盖它们。
# FastAPI 的 Depends(get_session_dep) 语法会在每个请求时调用这个函数，
# 如果是异步生成器，FastAPI 还会自动在请求结束后执行清理（关闭连接）。

def get_session_dep():
    # 占位：main.py 启动时覆盖为真正的数据库会话依赖
    raise RuntimeError("override")


def get_session_maker_dep():
    # 占位：main.py 启动时覆盖为真正的数据库会话工厂依赖
    # 与 get_session_dep 的区别：
    #   get_session_dep → 直接注入一个已经打开的 AsyncSession（简单路由用）
    #   get_session_maker_dep → 注入一个"会话工厂"，路由自己控制何时开关连接（SSE 流式路由用）
    raise RuntimeError("override")


# ── Session 输出序列化 ──────────────────────────────────────────────────
def _to_out(s):
    # 把数据库 Session ORM 对象转换成 Pydantic SessionOut 模式（API 响应格式）
    # 为什么不直接返回 ORM 对象？ORM 对象包含懒加载关系，直接序列化会出问题；
    # Pydantic 模型只包含明确定义的字段，序列化更安全、更可预测。
    from dzmm.api.schemas import SessionOut
    return SessionOut(
        id=s.id, name=s.name,
        screenplay_id=s.screenplay_id,
        world_id=s.world_id, character_id=s.character_id,
        gm_model_config_id=s.gm_model_config_id,
        summarizer_model_config_id=s.summarizer_model_config_id,
        turn_count=s.turn_count,
    )


# ── 消息事件 JSON 解析 ──────────────────────────────────────────────────
def _parse_events_json(raw: str | None) -> list[dict]:
    # 把 Message.events_json（存储在数据库里的 JSON 字符串）解析成 Python 列表
    # 这个字段记录了一回合里 LLM 输出中解析到的结构化事件（state_change/dice/npc_update 等）
    # "best-effort"（尽力而为）：无论字段是 None、空字符串还是损坏的 JSON，都安全返回 []
    if not raw:
        return []
    try:
        decoded = json.loads(raw)  # json.loads: 把 JSON 字符串解析成 Python 对象
    except (TypeError, ValueError):
        return []  # 解析失败就当没有事件，不抛出异常
    if not isinstance(decoded, list):
        return []  # 如果解析结果不是列表（比如是 dict），也当没有事件
    # 过滤掉列表中不是 dict 的元素（防御性编程，兼容历史脏数据）
    return [e for e in decoded if isinstance(e, dict)]


# ── 级联删除存档 ──────────────────────────────────────────────────────
async def delete_session_cascade(s: AsyncSession, session_id: int) -> None:
    # 删除一个存档的所有关联数据（不删 Session 本身，调用方负责）
    #
    # 【为什么要手动删？】
    #   SQLite 默认不启用外键约束（PRAGMA foreign_keys = OFF），
    #   所以删除父表行不会自动级联删子表。必须手动按依赖顺序逐表删除。
    #   Order 很重要：被引用的行必须在引用它的行之后删除。
    #
    # 【async def 与 await】
    #   async def 声明这是一个"协程函数"，调用它返回协程对象（不立即执行）。
    #   await 暂停当前协程，把控制权交给事件循环去执行数据库 IO，完成后再继续。
    #   这样一个线程可以同时服务多个请求（非阻塞 IO），不需要多线程。

    from dzmm.service.npc_memory import delete_npc_memory
    # local import to avoid cycle (db.models imports light, but routes_sessions
    # is loaded before _common from base.py — keeping this import local is
    # consistent with the rest of this file)
    from dzmm.db.models import (
        AgentMessage,
        AgentStream,
        CharState,
        Faction,
        Feedback,
        HiddenEvent,
        Location,
        LocationEdge,
        Message as MessageRow,
        NPC as NPCModel,
        NpcRelation,
        PCGoal,
        PlotThread,
        Screenplay,
        ScreenplayRevision,
        StorySummary,
    )

    # ── 第一步：清理 Agent 流历史（v0.10 新增）──────────────────────────
    # AgentMessage 有外键指向 AgentStream，必须先删 AgentMessage 才能删 AgentStream
    # select(AgentStream.id).where(...) → 只查 id 列，不加载整个对象（更高效）
    # .scalars().all() → 把查询结果从"Row 对象列表"提取成"Python 值列表"
    stream_ids = (await s.execute(
        select(AgentStream.id).where(AgentStream.session_id == session_id)
    )).scalars().all()
    if stream_ids:
        # delete(AgentMessage).where(...in_(stream_ids)) → SQL 的 DELETE WHERE id IN (...)
        await s.execute(
            delete(AgentMessage).where(AgentMessage.stream_id.in_(stream_ids))
        )
        await s.execute(
            delete(AgentStream).where(AgentStream.session_id == session_id)
        )

    # ── 第二步：处理剧本（Screenplay）──────────────────────────────────
    # 两种剧本有不同的处理策略：
    #   world_id IS NULL  → 旧式存档专属剧本，随存档一起彻底删除
    #   world_id IS NOT NULL → 世界级模板剧本（向导生成），保留但"解绑"：
    #     把 session_id 置 None，重置进度字段，以便以后开新存档复用

    # Two flavors of session-attached screenplays:
    # - world_id IS NULL  → 完全 session-only 的旧档剧本，跟存档一起删
    # - world_id IS NOT NULL → 通过向导/auto-generate 建出来的"世界级模板"，
    #   detach 不 delete，保留 chapters/main_characters/ending 让玩家以后能
    #   再开新存档复用；进度字段（current_chapter / completed_events_json）
    #   重置回初始状态。要彻底清掉剧本，前端走 tier-2 的
    #   DELETE /screenplays/{id}?cascade=true。
    sps = (await s.execute(
        select(Screenplay).where(Screenplay.session_id == session_id)
    )).scalars().all()
    legacy_ids: list[int] = []  # 需要彻底删除的旧式剧本 ID
    for sp in sps:
        if sp.world_id is None:
            # 旧式剧本：记录 id，稍后删除
            legacy_ids.append(sp.id)
        else:
            # 世界级模板：只解绑，重置进度，保留内容
            sp.session_id = None          # 解绑存档关联
            sp.current_chapter = 1        # 重置到第 1 章
            sp.completed_events_json = "[]"  # 清空已完成事件记录
            sp.status = "active"          # 恢复激活状态
    if legacy_ids:
        # 先删 ScreenplayRevision（子表），再删 Screenplay（父表）
        await s.execute(
            delete(ScreenplayRevision).where(
                ScreenplayRevision.screenplay_id.in_(legacy_ids)
            )
        )
        await s.execute(
            delete(Screenplay).where(Screenplay.id.in_(legacy_ids))
        )

    # ── 第三步：记录 NPC ID，用于后续清理向量数据库 ───────────────────
    # 在删除 NPC 数据库行之前先把 ID 收集起来，
    # 删除后再用这些 ID 清理 ChromaDB 里的向量记忆集合
    npc_ids = (await s.execute(
        select(NPCModel.id).where(NPCModel.session_id == session_id)
    )).scalars().all()

    # ── 第四步：删除位置边（LocationEdge 有外键指向 Location，必须先删）─
    # v0.10 T12: LocationEdge has FKs to Location, must be wiped before
    # the Location rows it references.
    await s.execute(
        delete(LocationEdge).where(LocationEdge.session_id == session_id)
    )

    # ── 第五步：批量删除剩余所有关联表的数据 ──────────────────────────
    # 用 Python for 循环避免重复写 12 条几乎一样的 delete 语句
    # NB: Location and Faction were missing from the pre-extraction loop
    # in routes_sessions/base.py — they're session-scoped (FK to sessions)
    # but used to be left orphaned. Adding them here fixes that bug.
    for model in (
        MessageRow, NPCModel, NpcRelation, PlotThread,
        CharState, StorySummary, PCGoal, HiddenEvent, Feedback,
        Location, Faction,
    ):
        # 每个模型类都有 session_id 字段，统一按此字段过滤删除
        await s.execute(
            delete(model).where(model.session_id == session_id)
        )

    # ── 第六步：清理每个 NPC 在 ChromaDB 里的向量记忆集合 ─────────────
    # NPC 记忆存在向量数据库（ChromaDB）中，SQL 删除不会触及它，必须手动清理。
    # 不清理会导致磁盘占用随新存档的创建/删除无限增长。
    for nid in npc_ids:
        delete_npc_memory(nid)  # best-effort：失败也不影响 SQL 事务


# ── NPC ORM 对象转字典 ───────────────────────────────────────────────
def _npc_to_dict(n: NPC) -> dict:
    # 把 NPC 数据库行转换成前端需要的字典格式
    # 需要处理三个 JSON 字段（存储为字符串，需要解析）以及 revealed（渐进披露映射）

    # affinity_json: NPC 对其他 NPC/派系的情感倾向，格式 {"人名": 数值}
    try:
        affinity = json.loads(n.affinity_json or "{}")
        if not isinstance(affinity, dict):
            affinity = {}
    except (TypeError, ValueError):
        affinity = {}

    # notes_json: GM/玩家对该 NPC 的备注列表
    try:
        notes = json.loads(n.notes_json or "[]")
        if not isinstance(notes, list):
            notes = []
    except (TypeError, ValueError):
        notes = []

    # emotion_json: NPC 当前情绪状态，格式 {"情绪名": 强度}
    try:
        emotion = json.loads(n.emotion_json or "{}")
        if not isinstance(emotion, dict):
            emotion = {}
    except (TypeError, ValueError):
        emotion = {}

    # v0.11: progressive reveal map — frontend masks fields not in this dict.
    # Threshold rules (v0.2.5) live in `_effective_reveals` so the GM dossier
    # builder agrees with what the frontend renders. See npc_dossier.py.
    # 渐进披露：根据好感度阈值计算哪些字段当前对玩家可见
    # 前端根据这个映射决定是否显示（或模糊显示）NPC 的背景/动机等敏感信息
    revealed = _effective_reveals(n)

    return {
        "id": n.id,
        "name": n.name,
        "gender": n.gender or "",   # or "" 确保 None 时返回空字符串而非 null
        "description": n.description,
        "favor": n.favor,           # 好感度数值
        "state": n.state,           # 当前状态（活跃/失联/死亡等）
        "last_seen_turn": n.last_seen_turn,  # 最后出场的回合号，0 表示还没出场
        "purpose": n.purpose,       # NPC 的动机/目的
        "archetype": n.archetype,   # 人物原型（mentor/rival/ally 等）
        "affinity": affinity,
        "emotion": emotion,
        "pinned": bool(n.pinned),   # 是否被钉选（重要 NPC）
        "notes": notes,
        "revealed": revealed,       # 渐进披露字段映射
        "current_location": n.current_location,  # 当前所在地点
        "tts_voice": n.tts_voice or "",  # 语音合成使用的音色
    }
