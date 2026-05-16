# ============================================================
# db/base.py — 数据库引擎 & 迁移工具
# ============================================================
#
# 【这个文件干什么？】
#   1. 创建全局 SQLAlchemy 异步引擎（AsyncEngine），相当于"数据库连接工厂"
#   2. 提供 async_session() 工厂，用于在业务代码里开启一次数据库会话
#   3. 定义所有"渐进式列迁移"数据（_VNNN_MIGRATIONS 字典），
#      以及把它们实际执行到 SQLite 文件里的逻辑
#
# 【什么是 ORM？为什么要用 ORM？】
#   ORM（Object-Relational Mapper，对象关系映射器）让你用 Python 类操作数据库，
#   而不是手写 SQL 字符串。好处：
#     - 类型安全：IDE 能自动补全字段名，拼错字段名会在 Python 层报错
#     - 防 SQL 注入：参数由框架自动转义，不会拼出危险字符串
#     - 跨数据库：同一套代码可以跑在 SQLite（开发）/ PostgreSQL（生产）上
#   SQLAlchemy 是 Python 最流行的 ORM，
#   SQLAlchemy 2.x（本项目使用）引入了更现代的 Mapped/mapped_column 语法。
#
# 【什么是"数据库迁移"？为什么要 _VNNN_MIGRATIONS？】
#   当你的软件已经发布、用户已经有真实数据时，你不能直接删掉旧数据库再重建。
#   你需要"迁移"：在已有的表上增加/修改列，同时保留原有数据。
#   本项目选择了最轻量的方案：
#     - 用 _V07_MIGRATIONS、_V09_MIGRATIONS …… 这些字典记录"哪个版本加了哪些列"
#     - 启动时调用 _add_missing_columns_sync() 尝试 ALTER TABLE ADD COLUMN
#     - 如果列已经存在，就跳过（幂等性：多次运行结果一样）
#   命名里的数字（07 / 09 / 10 / …）对应项目版本号，方便追踪"这列是什么时候加的"。
# ============================================================

from sqlalchemy.ext.asyncio import (
    AsyncEngine,       # 异步数据库引擎（持有连接池）
    AsyncSession,      # 异步会话（代表一次"事务上下文"）
    async_sessionmaker, # 异步会话工厂类
    create_async_engine, # 根据 URL 创建引擎的函数
)
from sqlalchemy.orm import DeclarativeBase  # 所有 ORM 模型类的公共基类

from dzmm.config import DEFAULT_DB_URL  # 默认数据库连接字符串，如 sqlite+aiosqlite:///./data.db


# ── 公共基类 ──────────────────────────────────────────────
# DeclarativeBase 是 SQLAlchemy 2.x 的新式基类写法。
# 所有 ORM 模型（World / Character / Session …）都继承自这个 Base。
# SQLAlchemy 通过 Base.metadata 追踪所有已注册的表定义，
# create_all() 时会读取 metadata 来知道要建哪些表。
# 【Java 对比】相当于 JPA 里加了 @Entity 的父类 + EntityManagerFactory 共同维护的元数据注册表。
class Base(DeclarativeBase):
    pass


# ── 引擎工厂 ──────────────────────────────────────────────
# AsyncEngine 是"连接池 + 驱动"的封装。
# 一个进程里通常只创建一个引擎（单例），然后反复从它拿连接。
def get_engine(url: str = DEFAULT_DB_URL) -> AsyncEngine:
    # create_async_engine: 根据 URL 创建支持 async/await 的引擎
    #   url    - 连接字符串，SQLite 示例: "sqlite+aiosqlite:///./dzmm.db"
    #   echo   - True 时把每条 SQL 打到控制台（调试用）；生产环境设 False
    #   future - True 表示启用 SQLAlchemy 2.0 的新行为（必须加）
    return create_async_engine(url, echo=False, future=True)


# ── 会话工厂 ──────────────────────────────────────────────
# AsyncSession 是一次"工作单元"（Unit of Work）：
#   - 在会话内读写的对象被"跟踪"，commit() 时统一写库
#   - close/rollback 时所有未提交改动丢弃
# async_sessionmaker 是"会话工厂"：每次调用它都返回一个新的 AsyncSession 实例。
# 【Java 对比】AsyncSession ≈ EntityManager；async_sessionmaker ≈ EntityManagerFactory.createEntityManager()
def async_session(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(
        engine,
        expire_on_commit=False,  # commit 后对象字段不自动失效（避免访问时再查库，减少 N+1 问题）
        class_=AsyncSession,     # 明确要异步会话而非同步会话
    )


# ============================================================
# 渐进式列迁移字典
# ============================================================
# 结构：{ "表名": [("列名", "完整 DDL 片段"), ...], ... }
# 例：("xp", "xp INTEGER NOT NULL DEFAULT 0")
#   → 对应 ALTER TABLE characters ADD COLUMN xp INTEGER NOT NULL DEFAULT 0
#
# 为什么不用 Alembic？
#   Alembic 是 SQLAlchemy 官方的迁移工具，功能完整但引入了额外的迁移脚本文件。
#   本项目选择了更简单的"直接在代码里写迁移"方案，适合小团队快速迭代。
#   代价是只能"加列"，不能改列类型或删列（SQLite 限制更多）。
# ============================================================

# v0.7 — 角色头像、经验值、等级；会话记忆待回溯；NPC 扩展字段
_V07_MIGRATIONS: dict[str, list[tuple[str, str]]] = {
    # table → list of (column_name, full_DDL_fragment)
    "characters": [
        ("portrait_path", "portrait_path VARCHAR(255) NOT NULL DEFAULT ''"),
        ("xp", "xp INTEGER NOT NULL DEFAULT 0"),
        ("level", "level INTEGER NOT NULL DEFAULT 1"),
    ],
    "sessions": [
        ("recall_pending_json", "recall_pending_json TEXT NOT NULL DEFAULT '[]'"),
    ],
    "npcs": [
        ("purpose", "purpose TEXT NOT NULL DEFAULT ''"),
        ("archetype", "archetype VARCHAR(120) NOT NULL DEFAULT ''"),
        ("affinity_json", "affinity_json TEXT NOT NULL DEFAULT '{}'"),
        ("pinned", "pinned BOOLEAN NOT NULL DEFAULT 0"),
        ("emotion_json", "emotion_json TEXT NOT NULL DEFAULT '{}'"),
    ],
}

# v0.9 — PC 心情 JSON
_V09_MIGRATIONS: dict[str, list[tuple[str, str]]] = {
    "sessions": [
        ("pc_mood_json", "pc_mood_json TEXT NOT NULL DEFAULT '{}'"),
    ],
}

# v0.10 — 每条消息的结构化事件列表和气泡分段数据
_V10_MIGRATIONS: dict[str, list[tuple[str, str]]] = {
    "messages": [
        ("events_json", "events_json TEXT NOT NULL DEFAULT '[]'"),
        ("parts_json", "parts_json TEXT NOT NULL DEFAULT '[]'"),
    ],
}

# v0.11 — NPC 信息揭示状态（哪些字段玩家已经知道）
_V11_MIGRATIONS: dict[str, list[tuple[str, str]]] = {
    "npcs": [
        ("revealed_json", "revealed_json TEXT NOT NULL DEFAULT '{\"name\": true}'"),
    ],
}

# v0.13.1 — Player feedback table is created via Base.metadata.create_all.
# Nothing to migrate column-wise.

# v0.25 — 会话设置开关；NPC 当前位置；地点物品列表
_V025_MIGRATIONS: dict[str, list[tuple[str, str]]] = {
    "sessions": [
        ("settings_json", "settings_json TEXT NOT NULL DEFAULT '{}'"),
    ],
    "npcs": [
        ("current_location", "current_location VARCHAR(120)"),  # nullable, no DEFAULT
    ],
    "locations": [
        ("items_json", "items_json TEXT NOT NULL DEFAULT '[]'"),
    ],
}

# v0.26 — 厄运值（0-100 的剧情张力指标）
_V026_MIGRATIONS: dict[str, list[tuple[str, str]]] = {
    "sessions": [
        ("doom_score", "doom_score INTEGER NOT NULL DEFAULT 0"),
    ],
}

# v0.27 — NPC 主动出现的上次回合记录（防止同一回合反复出现）
_V027_MIGRATIONS: dict[str, list[tuple[str, str]]] = {
    "npcs": [("last_initiative_turn", "last_initiative_turn INTEGER NOT NULL DEFAULT 0")],
}

# v0.28 — 剧本绑定世界、PC 模板字段；会话绑定剧本
_V028_MIGRATIONS: dict[str, list[tuple[str, str]]] = {
    "screenplays": [
        ("world_id", "world_id INTEGER REFERENCES worlds(id)"),
        ("title", "title VARCHAR(120) NOT NULL DEFAULT ''"),
        ("pc_name", "pc_name VARCHAR(120) NOT NULL DEFAULT ''"),
        ("pc_profile_md", "pc_profile_md TEXT NOT NULL DEFAULT ''"),
        ("pc_base_stats_json", "pc_base_stats_json TEXT NOT NULL DEFAULT '{}'"),
    ],
    "sessions": [
        ("screenplay_id", "screenplay_id INTEGER REFERENCES screenplays(id)"),
    ],
}

# v0.29 — NPC TTS 配音声线；剧本 PC 的 TTS 声线
_V029_MIGRATIONS: dict[str, list[tuple[str, str]]] = {
    "npcs": [
        ("tts_voice", "tts_voice VARCHAR(120) NOT NULL DEFAULT ''"),
    ],
    "screenplays": [
        ("pc_tts_voice", "pc_tts_voice VARCHAR(120) NOT NULL DEFAULT ''"),
    ],
}

# v0.30 — 当前场景已停留回合数（用于触发"场景切换"提示）
_V030_MIGRATIONS: dict[str, list[tuple[str, str]]] = {
    "sessions": [
        ("scene_turn_count", "scene_turn_count INTEGER NOT NULL DEFAULT 0"),
    ],
}

# v0.31 — 调试用：存储发送给 LLM 的完整 prompt（仅 debug_mode 下填充）
_V031_MIGRATIONS: dict[str, list[tuple[str, str]]] = {
    "messages": [
        ("prompt_json", "prompt_json TEXT NOT NULL DEFAULT ''"),
    ],
}

# v0.32 — 世界内时间（日期 / 时段 / 天气）
_V032_MIGRATIONS: dict[str, list[tuple[str, str]]] = {
    "sessions": [
        ("world_time_json", "world_time_json TEXT NOT NULL DEFAULT '{\"day\": 1, \"period\": \"morning\", \"weather\": \"clear\"}'"),
    ],
}

# v0.33 — NPC 所属势力（FK 到 factions 表）
_V033_MIGRATIONS: dict[str, list[tuple[str, str]]] = {
    "npcs": [
        ("faction_id", "faction_id INTEGER"),
    ],
}

# v0.34 — 模型配置最大并发数（0 = 不限制）
_V034_MIGRATIONS: dict[str, list[tuple[str, str]]] = {
    "model_configs": [
        ("max_concurrent", "max_concurrent INTEGER NOT NULL DEFAULT 0"),
    ],
}

# v0.10 — gender attribute on PC + NPC + Screenplay PC template.
# Empty string ("") means legacy / unset; new wizard-generated content
# always populates with "male" or "female".
# v0.35 — PC、NPC、剧本 PC 模板的性别字段
_V035_MIGRATIONS: dict[str, list[tuple[str, str]]] = {
    "characters": [
        ("gender", "gender VARCHAR(10) NOT NULL DEFAULT ''"),
    ],
    "npcs": [
        ("gender", "gender VARCHAR(10) NOT NULL DEFAULT ''"),
    ],
    "screenplays": [
        ("pc_gender", "pc_gender VARCHAR(10) NOT NULL DEFAULT ''"),
    ],
}

# v0.10 — user-designated default model_config. Wizard + one-shot LLM calls
# (no session context) pick this row first; falls back to "first row by id"
# when no default is set. Mutually exclusive: at most one row may have
# is_default=1; the /model_configs/{id}/default endpoint enforces this.
# v0.36 — 用户显式指定的"默认模型配置"（Wizard / 无 session 上下文时使用）
_V036_MIGRATIONS: dict[str, list[tuple[str, str]]] = {
    "model_configs": [
        ("is_default", "is_default INTEGER NOT NULL DEFAULT 0"),
    ],
}

# v0.10 — multi-agent stateful streams. New tables; no column-add migration
# needed (Base.metadata.create_all picks them up automatically). Listed here
# only for documentation symmetry with prior _VNNN_MIGRATIONS dicts.
# v0.40 — 多 Agent 状态化流。新建 agent_streams / agent_messages 两张表，
# 由 Base.metadata.create_all 自动建表，无需列迁移，此处仅作文档说明。
_V040_NEW_TABLES = ("agent_streams", "agent_messages")

# v0.10 — Scene topology. New table `location_edges` is created by
# Base.metadata.create_all; only the new column on `sessions` needs an
# additive migration for legacy DBs.
# v0.41 — 场景拓扑警告：记录上回合检测到的"无 edge 跨场景"警告，
# 下回合注入 prompt 让 GM 补发 emit 指令
_V041_MIGRATIONS: dict[str, list[tuple[str, str]]] = {
    "sessions": [
        ("topology_warning_json",
         "topology_warning_json TEXT NOT NULL DEFAULT '[]'"),
    ],
}

# v0.10.5 — turn-effect rollback: store a JSON snapshot of mutable state at
# turn START on each assistant message; delete_last_turn deserializes the
# snapshot to revert every effect of that turn (stats, NPC favor/emotion,
# locations, plot progress, hidden events, factions, etc.).
# v0.42 — 回合效果回滚快照：每条 assistant 消息存储回合开始时的状态快照，
# 支持"撤销上一回合"功能
_V042_MIGRATIONS: dict[str, list[tuple[str, str]]] = {
    "messages": [
        ("snapshot_json", "snapshot_json TEXT NOT NULL DEFAULT ''"),
    ],
}

# v0.43 — 剧本内嵌 NPC 模板列表（JSON 数组）
_V043_MIGRATIONS: dict[str, list[tuple[str, str]]] = {
    "screenplays": [
        ("npcs_json", "npcs_json TEXT NOT NULL DEFAULT '[]'"),
    ],
}

# v0.44 — 会话关联开放世界框架（nullable：旧存档不使用 framework）
_V044_MIGRATIONS: dict[str, list[tuple[str, str]]] = {
    "sessions": [
        ("framework_id", "framework_id INTEGER REFERENCES world_frameworks(id)"),
    ],
}

# v0.50 — Python-first mechanical engine (v0.15 feature batch 1).
# Adds D&D-style attributes, max vitals, skills/inventory/equipment JSON,
# NPC stat block, CharState stamina column, and ruleset_version on Session.
# ruleset_version: 1 = legacy LLM-driven, 2 = Python-driven (default for new sessions).
_V050_MIGRATIONS: dict[str, list[tuple[str, str]]] = {
    "characters": [
        ("strength",     "strength INTEGER NOT NULL DEFAULT 10"),
        ("dexterity",    "dexterity INTEGER NOT NULL DEFAULT 10"),
        ("constitution", "constitution INTEGER NOT NULL DEFAULT 10"),
        ("intelligence", "intelligence INTEGER NOT NULL DEFAULT 10"),
        ("wisdom",       "wisdom INTEGER NOT NULL DEFAULT 10"),
        ("charisma",     "charisma INTEGER NOT NULL DEFAULT 10"),
        ("max_hp",       "max_hp INTEGER NOT NULL DEFAULT 30"),
        ("max_sanity",   "max_sanity INTEGER NOT NULL DEFAULT 50"),
        ("max_stamina",  "max_stamina INTEGER NOT NULL DEFAULT 30"),
        ("skills_json",  "skills_json TEXT NOT NULL DEFAULT '{}'"),
        ("inventory_json", "inventory_json TEXT NOT NULL DEFAULT '[]'"),
        ("equipment_json", "equipment_json TEXT NOT NULL DEFAULT '{}'"),
    ],
    "npcs": [
        ("stat_block_json", "stat_block_json TEXT NOT NULL DEFAULT '{}'"),
    ],
    "char_states": [
        ("stamina", "stamina INTEGER NOT NULL DEFAULT 30"),
    ],
    "sessions": [
        ("ruleset_version", "ruleset_version INTEGER NOT NULL DEFAULT 2"),
    ],
}


# ── 特殊迁移：将 screenplays.session_id 改为 nullable ────
# SQLite 不支持 ALTER COLUMN，所以只能用"复制→删旧→改名"三步走。
# 这个函数是幂等的：如果 session_id 已经 nullable 或者表不存在，直接返回。
def _make_screenplay_session_id_nullable_sync(conn) -> None:
    """v0.2.8: make screenplays.session_id nullable via table rebuild.
    SQLite does not support ALTER COLUMN, so we copy→drop→rename.
    Idempotent: no-op if session_id is already nullable or missing."""
    # PRAGMA table_info 返回表的列信息：(cid, name, type, notnull, dflt_value, pk)
    cols = conn.exec_driver_sql("PRAGMA table_info(screenplays)").fetchall()
    if not cols:
        return  # table doesn't exist yet; create_all will handle it correctly
    # 找到 session_id 列；r[3] 是 notnull 标志，0 = 已经允许 NULL
    session_id_col = next((r for r in cols if r[1] == "session_id"), None)
    if session_id_col is None or session_id_col[3] == 0:
        return  # already nullable

    # 重新构造建表 DDL（去掉 session_id 的 NOT NULL 约束）
    col_defs = []
    for _cid, name, coltype, notnull, dflt_value, pk in cols:
        parts = [f"{name} {coltype}"]
        if pk:
            parts.append("PRIMARY KEY")
        elif name != "session_id" and notnull:
            # 保留其他列的 NOT NULL 约束，只去掉 session_id 的
            parts.append("NOT NULL")
        if dflt_value is not None:
            parts.append(f"DEFAULT {dflt_value}")
        col_defs.append(" ".join(parts))

    col_names = ", ".join(r[1] for r in cols)
    # 步骤1：用新 schema 建临时表
    conn.exec_driver_sql(
        f"CREATE TABLE _screenplays_tmp ({', '.join(col_defs)})"
    )
    # 步骤2：把旧数据复制进去
    conn.exec_driver_sql(
        f"INSERT INTO _screenplays_tmp ({col_names}) SELECT {col_names} FROM screenplays"
    )
    # 步骤3：删旧表，重命名临时表
    conn.exec_driver_sql("DROP TABLE screenplays")
    conn.exec_driver_sql("ALTER TABLE _screenplays_tmp RENAME TO screenplays")


# ── 通用列添加迁移 ────────────────────────────────────────
# 这是所有 _VNNN_MIGRATIONS 的执行引擎。
# 之所以用 _sync 后缀，是因为 SQLAlchemy 的 run_sync() 要求传入同步函数。
# run_sync() 会在异步上下文里临时切回同步模式来执行 DDL 语句。
def _add_missing_columns_sync(conn, table: str, columns: list[tuple[str, str]]) -> None:
    """SQLite-friendly column-add migration. Idempotent: skips columns that
    already exist. Called from a sync run_sync() context inside init_db()."""
    # PRAGMA table_info 获取该表已有的所有列名
    rows = conn.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()
    existing = {r[1] for r in rows}  # 把列名提取成集合，方便 O(1) 查找
    for name, ddl in columns:
        if name not in existing:
            # 列不存在才执行 ALTER TABLE ADD COLUMN，避免重复执行报错
            conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {ddl}")


# ── 旧数据回填默认值 ──────────────────────────────────────
# 在 base_stats_json 列加入之前建立的角色行，该字段为空 '{}'。
# 给它们补上最小可玩的默认值，同时同步 char_states 里的实时状态。
_DEFAULT_BASE_STATS = (
    '{"hp": 15, "sanity": 15, "体魄": 5, "敏捷": 5, "智识": 5, "意志": 5}'
)


def _backfill_legacy_base_stats_sync(conn) -> None:
    """One-shot backfill: characters created before the base_stats prompt
    exist have base_stats_json='{}'. Give them a minimal playable default
    and sync any matching char_states rows so the UI shows real values."""
    # Check table exists (safe guard for fresh DBs)
    # sqlite_master 是 SQLite 的系统表，记录所有表/视图/索引的定义
    tables = {r[0] for r in conn.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    if "characters" not in tables:
        return  # 全新数据库，create_all 会建表，不需要回填

    # 把 base_stats_json = '{}' 的旧角色行更新为最小默认值
    conn.exec_driver_sql(
        "UPDATE characters SET base_stats_json = ? WHERE base_stats_json = '{}'",
        (_DEFAULT_BASE_STATS,),
    )

    # 同步 char_states（实时状态表）里同样为空的行
    if "char_states" in tables:
        conn.exec_driver_sql(
            "UPDATE char_states SET stats_json = ? WHERE stats_json = '{}'",
            (_DEFAULT_BASE_STATS,),
        )


# ── 数据库初始化入口 ──────────────────────────────────────
# 应用启动时调用一次，完成：
#   1. 建表（如果不存在）
#   2. 按版本顺序执行所有列迁移
#   3. 回填历史数据
# async with engine.begin() as conn 会开启一个自动提交的"连接级事务"，
# DDL 语句（CREATE TABLE / ALTER TABLE）在 SQLite 里是隐式自动提交的。
async def init_db(engine: AsyncEngine) -> None:
    # 延迟导入 models 模块，确保所有 ORM 类都被注册到 Base.metadata 里，
    # 这样 create_all() 才能知道要建哪些表。
    # noqa: F401 告诉 lint 工具"这个看似无用的 import 是故意的"。
    from dzmm.db import models  # noqa: F401
    async with engine.begin() as conn:
        # create_all: 对比 Base.metadata 里的表定义和数据库里实际存在的表，
        # 只建"还没有的表"，已有的表不动（checkfirst=True 是默认行为）。
        await conn.run_sync(Base.metadata.create_all)

        # 以下按版本顺序逐一执行列迁移。
        # run_sync() 的作用：在异步事件循环里临时调用同步函数，
        # 传入的函数签名是 func(sync_conn, *args)。
        # Lightweight column-add migrations for v0.7 features layered on
        # databases originally created at v0.6 or earlier. New columns
        # have safe defaults so existing data is preserved.
        for table, cols in _V07_MIGRATIONS.items():
            await conn.run_sync(_add_missing_columns_sync, table, cols)
        for table, cols in _V09_MIGRATIONS.items():
            await conn.run_sync(_add_missing_columns_sync, table, cols)
        for table, cols in _V10_MIGRATIONS.items():
            await conn.run_sync(_add_missing_columns_sync, table, cols)
        for table, cols in _V11_MIGRATIONS.items():
            await conn.run_sync(_add_missing_columns_sync, table, cols)
        for table, cols in _V025_MIGRATIONS.items():
            await conn.run_sync(_add_missing_columns_sync, table, cols)
        for table, cols in _V026_MIGRATIONS.items():
            await conn.run_sync(_add_missing_columns_sync, table, cols)
        for table, cols in _V027_MIGRATIONS.items():
            await conn.run_sync(_add_missing_columns_sync, table, cols)
        # v0.28 的特殊迁移：SQLite 不支持 ALTER COLUMN，需要重建表
        await conn.run_sync(_make_screenplay_session_id_nullable_sync)
        for table, cols in _V028_MIGRATIONS.items():
            await conn.run_sync(_add_missing_columns_sync, table, cols)
        for table, cols in _V029_MIGRATIONS.items():
            await conn.run_sync(_add_missing_columns_sync, table, cols)
        for table, cols in _V030_MIGRATIONS.items():
            await conn.run_sync(_add_missing_columns_sync, table, cols)
        for table, cols in _V031_MIGRATIONS.items():
            await conn.run_sync(_add_missing_columns_sync, table, cols)
        for table, cols in _V032_MIGRATIONS.items():
            await conn.run_sync(_add_missing_columns_sync, table, cols)
        for table, cols in _V033_MIGRATIONS.items():
            await conn.run_sync(_add_missing_columns_sync, table, cols)
        for table, cols in _V034_MIGRATIONS.items():
            await conn.run_sync(_add_missing_columns_sync, table, cols)
        for table, cols in _V035_MIGRATIONS.items():
            await conn.run_sync(_add_missing_columns_sync, table, cols)
        for table, cols in _V036_MIGRATIONS.items():
            await conn.run_sync(_add_missing_columns_sync, table, cols)
        # _V040 只有新表，由上面 create_all 处理，此处无需再迁移列
        for table, cols in _V041_MIGRATIONS.items():
            await conn.run_sync(_add_missing_columns_sync, table, cols)
        for table, cols in _V042_MIGRATIONS.items():
            await conn.run_sync(_add_missing_columns_sync, table, cols)
        for table, cols in _V043_MIGRATIONS.items():
            await conn.run_sync(_add_missing_columns_sync, table, cols)
        for table, cols in _V044_MIGRATIONS.items():
            await conn.run_sync(_add_missing_columns_sync, table, cols)
        for table, cols in _V050_MIGRATIONS.items():
            await conn.run_sync(_add_missing_columns_sync, table, cols)
        # 最后做数据回填：给旧角色补上默认属性值
        await conn.run_sync(_backfill_legacy_base_stats_sync)
