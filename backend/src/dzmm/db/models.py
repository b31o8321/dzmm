# ============================================================
# 数据库模型（ORM 实体）
# ============================================================
# 【Java 对比】这里相当于 JPA/Hibernate 的 @Entity 类。
#   SQLAlchemy 是 Python 最流行的 ORM，语法比 JPA 更简洁。
#
# 关键概念：
#   Mapped[T]      → 告诉 Python（和 IDE）这个字段在运行时是 T 类型
#   mapped_column  → 对应 @Column 注解
#   ForeignKey     → 对应 @ManyToOne / @JoinColumn 里的外键声明
#   relationship() → 对应 @ManyToOne / @OneToMany，懒加载关联对象
#   Base           → 对应 JPA 的 @MappedSuperclass 基类，提供元数据注册
# ============================================================

from datetime import datetime, UTC
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from dzmm.db.base import Base


# ── 世界设定 ──────────────────────────────────────────────
# 一个"世界"是所有游戏内容的顶层容器。
# 可以存在多个世界（如"赛博朋克 2077"/"克苏鲁 1920s"），
# 每个世界有独立的规则、角色和游戏会话。
class World(Base):
    # __tablename__ 指定数据库中的表名（相当于 @Table(name="worlds")）
    __tablename__ = "worlds"

    # primary_key=True → 自增主键（SQLite/Postgres 都支持）
    # Mapped[int] 告诉类型检查器这个字段是整数，不会是 None
    id: Mapped[int] = mapped_column(primary_key=True)

    # String(120) → 数据库里是 VARCHAR(120)（最多 120 个字符的字符串）
    # Text → 无限长文本（数据库里是 TEXT / CLOB 类型）
    name: Mapped[str] = mapped_column(String(120))
    content_md: Mapped[str] = mapped_column(Text)           # 世界设定 Markdown 全文

    # default= 是 Python 侧的默认值：
    #   - INSERT 新行时如果不传这个字段，SQLAlchemy 会用这个默认值填充
    #   - 注意这是"Python 默认值"，不是数据库 DEFAULT 约束
    rules_json: Mapped[str] = mapped_column(Text, default='{"mode":"light"}')
    style: Mapped[str] = mapped_column(String(40), default="realistic")

    # lambda 让每次 INSERT 都重新调用 datetime.now()，
    # 而不是在模块加载时只计算一次（那样所有行会有相同的时间戳）。
    # replace(tzinfo=None) 去掉时区信息，存入数据库的是"朴素时间"（naive datetime）。
    # 【Java 对比】相当于 @PrePersist 里手动设置时间戳。
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None)
    )


# ── 角色（PC，Player Character） ─────────────────────────
# 一个玩家角色（PC）归属于某个世界。
# base_stats_json 存储初始属性，游戏中变化的属性存在 CharState 里。
# 这样的分离让我们可以"重置存档"而不丢失角色模板。
class Character(Base):
    __tablename__ = "characters"
    id: Mapped[int] = mapped_column(primary_key=True)

    # ForeignKey("worlds.id") 声明这列是指向 worlds 表 id 列的外键。
    # 这只是外键声明，不会自动加载 World 对象（那是 relationship() 的工作）。
    # 【Java 对比】相当于 @ManyToOne + @JoinColumn(name="world_id") 里的 @JoinColumn 部分。
    world_id: Mapped[int] = mapped_column(ForeignKey("worlds.id"))
    name: Mapped[str] = mapped_column(String(120))
    # gender: "male" | "female" — enum-like, kept simple per design intent.
    # Empty string = legacy data created before the column existed.
    # 性别字段：空字符串 = 历史旧数据（该列加入之前建立的角色）
    gender: Mapped[str] = mapped_column(String(10), default="")
    profile_md: Mapped[str] = mapped_column(Text)           # 角色背景 Markdown
    base_stats_json: Mapped[str] = mapped_column(Text)      # 初始属性 JSON，如 {"hp":20}

    portrait_path: Mapped[str] = mapped_column(String(255), default="")  # 头像文件路径
    xp: Mapped[int] = mapped_column(default=0)   # 累计经验值
    level: Mapped[int] = mapped_column(default=1) # 角色等级
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None)
    )

    # ── v0.15 mechanical engine columns ──────────────────────────────────
    # D&D-style attributes (range 3-18 in play; 1-30 allowed by schema).
    # modifier = (val - 10) // 2
    strength: Mapped[int] = mapped_column(default=10)
    dexterity: Mapped[int] = mapped_column(default=10)
    constitution: Mapped[int] = mapped_column(default=10)
    intelligence: Mapped[int] = mapped_column(default=10)
    wisdom: Mapped[int] = mapped_column(default=10)
    charisma: Mapped[int] = mapped_column(default=10)

    # Max vitals — current vitals live in CharState
    max_hp: Mapped[int] = mapped_column(default=30)
    max_sanity: Mapped[int] = mapped_column(default=50)
    max_stamina: Mapped[int] = mapped_column(default=30)

    # Skills: dict[skill_name, level 0-100] stored as JSON
    skills_json: Mapped[str] = mapped_column(Text, default="{}")
    # inventory_json: v0.15 structured format (list[Item] as JSON).
    # Note: CharState.inventory_json was the legacy field; Character.inventory_json
    # is the new canonical store. Both coexist during Batch 1 → Batch 2 transition.
    inventory_json: Mapped[str] = mapped_column(Text, default="[]")
    # equipment_json: currently equipped items dict {slot: item_name}
    equipment_json: Mapped[str] = mapped_column(Text, default="{}")
    # v0.53: one-shot level-up announcement. Set by engine.character.level_up();
    # consumed (drained to '') by _build_key_facts on the next GM turn.
    # JSON: {"old_level": N, "new_level": N+K, "attribute_raised": str, "skill_raised": str}
    # Empty string = no pending announcement.
    level_up_pending_json: Mapped[str] = mapped_column(Text, default="")

    # relationship() 声明 ORM 关联对象。
    # 访问 character.world 时，SQLAlchemy 会自动执行 SELECT * FROM worlds WHERE id = ?
    # 默认是"懒加载"（lazy load）：只有第一次访问 .world 时才查询数据库。
    # 【Java 对比】相当于 @ManyToOne(fetch=FetchType.LAZY)。
    # 注意：异步模式下懒加载会报错，需要提前 await session.refresh(obj, ["world"])
    #       或者使用 selectinload() 在查询时一起加载。
    world: Mapped[World] = relationship()


# ── LLM 模型配置 ──────────────────────────────────────────
# 存储 Ollama / OpenAI 兼容接口的连接信息。
# 每个游戏会话可以独立选择 GM 模型（叙事引擎）和摘要模型，
# 方便同时跑多个模型做对比实验。
class ModelConfig(Base):
    __tablename__ = "model_configs"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))           # 用户起的别名，如"本地 Llama3"
    type: Mapped[str] = mapped_column(String(40))            # "ollama" | "openai"
    base_url: Mapped[str] = mapped_column(String(255))       # API 基础 URL，如 http://localhost:11434
    model_name: Mapped[str] = mapped_column(String(120))     # 模型标识符，如 "llama3:8b"

    # Mapped[str | None] → 允许 NULL 的列。
    # Python 3.10+ 的联合类型语法：str | None 等价于 Optional[str]。
    # 【Java 对比】相当于 @Column(nullable=true)，但这里写在类型里而非注解属性里。
    api_key_ref: Mapped[str | None] = mapped_column(String(120), nullable=True)  # API Key 引用名，None 表示不需要 key
    timeout: Mapped[float] = mapped_column(default=60.0)     # 单次请求超时秒数
    params_json: Mapped[str] = mapped_column(Text, default='{}')  # 额外参数 JSON，如 {"top_k": 40}

    # v0.9.1: 0 = 不限制；>0 = 进程内同 cfg 并发上限。智谱 glm-4-flash 免费层
    # 全局并发=1 → 必须 max_concurrent=1，否则只要有 2 个请求同时在飞就全 429。
    max_concurrent: Mapped[int] = mapped_column(default=0)

    # v0.10: 用户显式指定的"默认模型"。Wizard / 一次性 LLM 调用（没 session
    # 上下文，没法挑 gm_model_config_id 时）会用它。同时只有一行 is_default=True，
    # 在 set_default endpoint 里强制保证。
    is_default: Mapped[bool] = mapped_column(default=False)  # 是否为全局默认模型


# ── 局域网远程访问 ──────────────────────────────────────
class RemoteServerState(Base):
    """Persistent identity of this dzmm host.

    A singleton row survives IP changes and remote-mode restarts. Android
    clients use server_id, never the current IP, as the host identity.
    """

    __tablename__ = "remote_server_state"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    server_id: Mapped[str] = mapped_column(String(36), unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None)
    )


class PairedDevice(Base):
    """A paired Android device. Only the token hash is persisted."""

    __tablename__ = "paired_devices"

    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    paired_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None)
    )
    last_seen: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class TurnRun(Base):
    """Idempotent, reconnectable execution record for one player action."""

    __tablename__ = "turn_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("sessions.id"), index=True
    )
    request_id: Mapped[str] = mapped_column(String(120))
    action: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="running", index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None)
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None)
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    assistant_message_id: Mapped[int | None] = mapped_column(
        ForeignKey("messages.id"), nullable=True
    )

    __table_args__ = (
        UniqueConstraint(
            "session_id", "request_id", name="uq_turn_run_session_request"
        ),
    )


# ── 游戏会话 ──────────────────────────────────────────────
# 一局游戏（一个存档）。
# 关联：世界（背景设定）、角色（PC）、剧本大纲（可选）、两个 LLM（GM + 摘要器）。
# 所有游戏中产生的 NPC、消息、地点等，都通过 session_id 归属到这里。
class Session(Base):
    __tablename__ = "sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))           # 存档名称（用户可见）

    # 多个外键列指向不同的表
    world_id: Mapped[int] = mapped_column(ForeignKey("worlds.id"))
    character_id: Mapped[int] = mapped_column(ForeignKey("characters.id"))
    screenplay_id: Mapped[int | None] = mapped_column(ForeignKey("screenplays.id"), nullable=True)  # 可选：绑定剧本大纲
    # v0.11 — open-world framework reference (nullable: old sessions don't use it)
    # 可选：关联开放世界框架（v0.11 新增，旧存档为 None）
    framework_id: Mapped[int | None] = mapped_column(
        ForeignKey("world_frameworks.id"), nullable=True, default=None
    )

    # 同一张表可以有多个外键列指向同一目标表（这里两个都指向 model_configs）：
    # gm_model_config_id       — 用于 GM 叙事（需要创造力强的大模型）
    # summarizer_model_config_id — 用于摘要压缩（可以用小模型节省成本）
    gm_model_config_id: Mapped[int] = mapped_column(ForeignKey("model_configs.id"))
    summarizer_model_config_id: Mapped[int] = mapped_column(ForeignKey("model_configs.id"))

    turn_count: Mapped[int] = mapped_column(default=0)       # 已完成的回合总数
    schema_version: Mapped[int] = mapped_column(default=1)   # 存档的 schema 版本（迁移用）

    # 复杂结构（列表、字典）存为 JSON 字符串。
    # 原因：SQLite 没有原生 JSON 列类型；PostgreSQL 有，但为了兼容性统一用 TEXT。
    # 业务代码负责在读写时做 json.loads() / json.dumps()。
    recall_pending_json: Mapped[str] = mapped_column(Text, default="[]")  # 待触发的"回忆"事件队列
    pc_mood_json: Mapped[str] = mapped_column(Text, default="{}")         # PC 当前心情状态
    settings_json: Mapped[str] = mapped_column(Text, default="{}")        # 用户开关，如是否开启 director_pass

    doom_score: Mapped[int] = mapped_column(Integer, default=0)           # 厄运值 0-100，影响事件触发概率
    scene_turn_count: Mapped[int] = mapped_column(Integer, default=0)     # 当前场景已停留的回合数
    # v0.15 — ruleset version: 1=legacy LLM-driven, 2=Python-driven (default for new sessions)
    ruleset_version: Mapped[int] = mapped_column(Integer, default=2)
    world_time_json: Mapped[str] = mapped_column(Text, default='{"day": 1, "period": "morning", "weather": "clear"}')  # 世界内时间

    # v0.10 — 上一回合 _apply_location_enter 检测到的"无 edge 跨场景"警告，
    # 下回合 _build_key_facts drain 一次注入 prompt 强制 GM 补 emit。
    # 即：玩家去了一个跟当前地点没有"边"连接的地方，可能是 GM 漏发了拓扑 emit。
    topology_warning_json: Mapped[str] = mapped_column(Text, default="[]")

    # v0.51 (v0.15 Batch 2) — Python-engine mechanics resolution log.
    # Each turn's dice/skill/item resolutions are appended here so the next
    # turn's _build_key_facts can surface them as "上回合机械结算".
    # Shape: list[{"turn", "kind": "dice"|"skill"|"item"|"attack"|"initiative", "input": {}, "result": {}}]
    pending_resolutions_json: Mapped[str] = mapped_column(Text, default="[]")

    # v0.52 (v0.15 Batch 3) — current combat initiative order, persisted across turns.
    # Shape: list[{"kind": "pc"|"npc", "id": int, "name": str, "initiative_total": int}]
    combat_order_json: Mapped[str] = mapped_column(Text, default="[]")

    # v0.54 — legacy mechanic tag rejection warnings.
    # Records cases where the GM used banned/deprecated tags (e.g. <state_change hp="-N"/>
    # for combat damage, or the legacy <dice> tag).  _build_key_facts drains entries
    # from the PREVIOUS turn and injects them as a ⚠️ block so the GM is forced to
    # migrate to the correct v0.15 tags.
    # Shape: list[{"turn", "kind", "tag", "attempted"?, "reason"}]
    mechanic_warnings_json: Mapped[str] = mapped_column(Text, default="[]")

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None)
    )
    last_played: Mapped[datetime] = mapped_column(    # 最近游玩时间，用于存档列表排序
        DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None)
    )


# ── 对话消息 ──────────────────────────────────────────────
# 每一回合产生两条 Message：
#   role="user"      → 玩家的行动描述
#   role="assistant" → GM 的叙事回复（含 XML 标签，如 <event>、<npc_update>）
# 消息是整个游戏体验的核心数据，大部分其他表的数据都是从消息里解析出来的。
class Message(Base):
    __tablename__ = "messages"
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"))  # 所属存档

    # role 遵循 OpenAI Chat Completions API 约定：
    #   "system"    → 系统提示（GM 人格设定，每次都是消息列表的第一条）
    #   "user"      → 玩家输入
    #   "assistant" → LLM 输出
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)               # 原始 LLM 输出（含 XML 标签）
    turn: Mapped[int] = mapped_column(default=0)             # 所属回合序号（user 和 assistant 共享同一 turn 号）

    tokens_in: Mapped[int] = mapped_column(default=0)        # 该请求的输入 token 数（计费用）
    tokens_out: Mapped[int] = mapped_column(default=0)       # 该请求的输出 token 数
    summarized: Mapped[bool] = mapped_column(default=False)  # True = 已被摘要器"消化"，可以从上下文窗口里移除

    events_json: Mapped[str] = mapped_column(Text, default="[]")  # 本回合解析出的结构化事件列表
    parts_json: Mapped[str] = mapped_column(Text, default="[]")   # 前端对话气泡的分段渲染数据
    diagnostics_json: Mapped[str] = mapped_column(Text, default="[]")  # 解析/协议等回合级诊断
    prompt_json: Mapped[str] = mapped_column(Text, default="")    # debug: 发送给 LLM 的完整 prompt（仅 debug_mode 时填充）
    # v0.10.5: turn-effect rollback. Snapshot of mutable state at turn START
    # serialized as JSON, used by delete_last_turn to revert all effects
    # this turn's GM/NPC outputs caused (stats, NPC favor/emotion, locations,
    # plot progress, hidden events, factions, etc.). Empty = legacy turn.
    # 回合开始时的状态快照，支持"撤销上一回合"。空字符串 = 旧存档（无快照）。
    snapshot_json: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None)
    )


# ── 剧情摘要 ──────────────────────────────────────────────
# LLM 的上下文窗口（能记住多少对话历史）是有限的（通常 8K-128K token）。
# 摘要器定期把旧消息压缩成一段摘要文本，替代原始对话发给 LLM，
# 这样游戏可以无限进行而不会超出 token 限制。
# 每个 Session 只有一条摘要行（用 session_id 作主键）。
class StorySummary(Base):
    __tablename__ = "story_summaries"
    # 直接用外键列作为主键 → 强制一对一关系（一个 session 只有一条摘要）
    # 【Java 对比】相当于 @OneToOne 的"从表"用 @MapsId 把外键当主键。
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"), primary_key=True)
    summary_text: Mapped[str] = mapped_column(Text, default="")              # 当前摘要全文
    last_summarized_msg_id: Mapped[int] = mapped_column(default=0)           # 已摘要到哪条消息的 id
    summary_tokens: Mapped[int] = mapped_column(default=0)                   # 摘要本身的 token 数
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None)
    )


# ── 角色实时状态 ──────────────────────────────────────────
# 设计思路：
#   Character.base_stats_json = 角色模板（角色创建时定义，不随游戏变化）
#   CharState.stats_json      = 游戏中的当前值（随战斗/剧情动态变化）
# 这种分离让多个存档可以共享同一个角色模板，但各自维护独立的游戏状态。
class CharState(Base):
    __tablename__ = "char_states"
    # session_id 作为主键 → 一对一关系（一局游戏只有一套角色当前状态）
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"), primary_key=True)
    stats_json: Mapped[str] = mapped_column(Text, default="{}")      # 当前属性值（hp/sanity/体魄/…）
    inventory_json: Mapped[str] = mapped_column(Text, default="[]")  # 当前物品栏列表（legacy; v0.15 migrates to Character.inventory_json）
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None)
    )

    # v0.15 — dedicated stamina column (current value; max stored on Character)
    stamina: Mapped[int] = mapped_column(default=30)


# ── NPC ──────────────────────────────────────────────────
# GM 通过 <npc_update> XML 标签自动登记/更新 NPC。
# 每个 NPC 归属于一个 Session（不同存档的同名 NPC 是独立的）。
# favor（好感度）和 emotion_json 是 NPC 的核心"记忆"，
# 影响 GM 如何描述该 NPC 的态度和行为。
class NPC(Base):
    __tablename__ = "npcs"
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"))
    name: Mapped[str] = mapped_column(String(120))
    # gender: "male" | "female" — strict enum for new content; "" means
    # legacy data (created before the column existed).
    gender: Mapped[str] = mapped_column(String(10), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    favor: Mapped[int] = mapped_column(default=0)            # 好感度：正=友好，负=敌对，范围通常 -100..100
    state: Mapped[str] = mapped_column(String(60), default="未知")  # 当前状态，如"重伤"、"失踪"
    last_seen_turn: Mapped[int] = mapped_column(default=0)   # 最近一次出现的回合号
    notes_json: Mapped[str] = mapped_column(Text, default="[]")  # GM 笔记（结构化事件列表）
    purpose: Mapped[str] = mapped_column(Text, default="")   # 该 NPC 在剧情中的作用（GM 参考）
    archetype: Mapped[str] = mapped_column(String(120), default="")  # 原型，如"导师"、"反派"、"盟友"
    affinity_json: Mapped[str] = mapped_column(Text, default="{}")   # 对其他 NPC/阵营的亲疏关系
    pinned: Mapped[bool] = mapped_column(default=False)      # True = 在侧边栏顶部固定显示
    emotion_json: Mapped[str] = mapped_column(Text, default="{}")    # 当前情绪状态，如 {"恐惧": 3, "愤怒": 1}
    revealed_json: Mapped[str] = mapped_column(Text, default='{"name": true}')  # 哪些字段已对玩家揭示（隐藏 NPC 的真实信息）
    current_location: Mapped[str | None] = mapped_column(String(120), nullable=True, default=None)  # 当前所在地点名（可为空）
    last_initiative_turn: Mapped[int] = mapped_column(default=0)     # NPC 上次主动出现的回合（防止刷屏）
    tts_voice: Mapped[str] = mapped_column(String(120), default="")  # TTS 配音声线 ID
    faction_id: Mapped[int | None] = mapped_column(ForeignKey("factions.id"), nullable=True)  # 所属势力（可为空）

    # v0.15 — serialised StatBlock (sparse OK; missing keys default to 10/30/50)
    stat_block_json: Mapped[str] = mapped_column(Text, default="{}")
    # v0.53 — 1-sentence verbal tic injected into npc_actor system prompt
    speech_pattern: Mapped[str] = mapped_column(Text, default="")


# ── 剧情线索 ──────────────────────────────────────────────
# GM 通过 <plot_thread> 标签登记、推进和结束剧情线索。
# 活跃线索会被注入每回合的 key_facts，确保 GM 不会"忘记"未完成的任务。
class PlotThread(Base):
    __tablename__ = "plot_threads"
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"))
    type: Mapped[str] = mapped_column(String(40))            # quest（任务）| hook（引子）| mystery（谜题）| major_event（大事件）
    description: Mapped[str] = mapped_column(Text)
    introduced_turn: Mapped[int] = mapped_column(default=0)  # 首次出现的回合
    importance: Mapped[int] = mapped_column(default=2)       # 重要性：1=支线 2=普通 3=主线
    status: Mapped[str] = mapped_column(String(20), default="active")  # active（进行中）| resolved（完成）| abandoned（放弃）
    resolution: Mapped[str] = mapped_column(Text, default="")          # 结局描述（仅 resolved 时填写）


# ── NPC 关系网 ────────────────────────────────────────────
# 描述两个 NPC 之间的关系（父女/恋人/对手/上下级……）。
# 用名字而非外键（FK）关联，原因：
#   GM 可能在叙事里提到某个 NPC 的关系，但该 NPC 还没在 npcs 表里建档。
#   用名字字段可以避免"必须先在 DB 里有记录才能建关系"的约束。
class NpcRelation(Base):
    """用名字（而非外键）关联两个 NPC，避免 GM 提到 NPC 时必须先在 DB 建档。"""
    __tablename__ = "npc_relations"
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"))
    npc_a: Mapped[str] = mapped_column(String(120))          # NPC A 的名字（不是 FK，直接存字符串）
    npc_b: Mapped[str] = mapped_column(String(120))          # NPC B 的名字
    kind: Mapped[str] = mapped_column(String(60))            # 关系类型：父女/恋人/对手/同盟/…
    description: Mapped[str] = mapped_column(Text, default="")
    introduced_turn: Mapped[int] = mapped_column(default=0)


# ── 玩家目标 ──────────────────────────────────────────────
# GM 通过 <pc_goal> 标签自动登记玩家目标，完成时更新 status。
# 活跃目标每回合注入 key_facts，确保 GM 持续围绕目标推进叙事。
class PCGoal(Base):
    """GM 通过 <pc_goal> 标签自动登记/完成目标；活跃目标会注入每回合的 key_facts。"""
    __tablename__ = "pc_goals"
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"))
    description: Mapped[str] = mapped_column(Text)
    priority: Mapped[str] = mapped_column(String(20), default="normal")  # high（紧急）| normal（普通）| low（长期）
    status: Mapped[str] = mapped_column(String(20), default="active")    # active | completed | abandoned
    introduced_turn: Mapped[int] = mapped_column(default=0)
    completed_turn: Mapped[int | None] = mapped_column(nullable=True)    # None = 尚未完成
    completion_note: Mapped[str] = mapped_column(Text, default="")       # 完成时的备注


# ── 剧本大纲 ──────────────────────────────────────────────
# 开局时由 LLM 生成（包含章节/主线事件/NPC 模板/结局）。
# GM 每回合都能"看到"进度（当前章节、已完成事件），确保故事不会原地踏步。
# 玩家做出重大决策时，可以触发大纲重写（保存在 ScreenplayRevision 里）。
# 一个剧本可以关联多个存档（世界级剧本），也可以是某个存档专属的。
class Screenplay(Base):
    __tablename__ = "screenplays"
    id: Mapped[int] = mapped_column(primary_key=True)

    # nullable=True → session_id 可以为空，表示这是"世界级"共享剧本（v0.2.8 新增）
    # 世界级剧本可以被多个存档引用；会话级剧本只属于一个存档。
    session_id: Mapped[int | None] = mapped_column(ForeignKey("sessions.id"), nullable=True)
    world_id: Mapped[int | None] = mapped_column(ForeignKey("worlds.id"), nullable=True)  # 归属世界（可选）
    title: Mapped[str] = mapped_column(String(120), default="")      # 剧本标题
    pc_name: Mapped[str] = mapped_column(String(120), default="")    # 剧本预设的 PC 名字
    pc_gender: Mapped[str] = mapped_column(String(10), default="")   # 剧本预设的 PC 性别
    pc_profile_md: Mapped[str] = mapped_column(Text, default="")     # 剧本预设的 PC 背景 Markdown
    pc_base_stats_json: Mapped[str] = mapped_column(Text, default="{}")  # 剧本预设的 PC 初始属性
    version: Mapped[int] = mapped_column(default=1)                  # 剧本版本号（每次重写 +1）
    genre: Mapped[str] = mapped_column(String(60), default="")       # 类型：克苏鲁/奇幻/赛博朋克/…
    custom_prompt: Mapped[str] = mapped_column(Text, default="")     # 用户给 LLM 的额外创作指令
    outline_md: Mapped[str] = mapped_column(Text, default="")        # 大纲全文（Markdown）
    chapters_json: Mapped[str] = mapped_column(Text, default="[]")   # 章节数组，每章包含事件/目标
    main_characters_json: Mapped[str] = mapped_column(Text, default="[]")  # 主要 NPC 列表（供 GM 参考）
    ending_md: Mapped[str] = mapped_column(Text, default="")         # 预设结局描述
    opening_hook: Mapped[str] = mapped_column(Text, default="")      # 开篇引子（游戏开始时展示给玩家）
    current_chapter: Mapped[int] = mapped_column(default=1)          # 当前进行到第几章
    completed_events_json: Mapped[str] = mapped_column(Text, default="[]")  # 已完成的章节事件 id 列表

    # 自引用外键：续集剧本指向原作剧本（形成树形结构）
    # 游戏结局后，可以基于原作生成"续集剧本"，续集里有"上一局发生了什么"的上下文。
    parent_screenplay_id: Mapped[int | None] = mapped_column(ForeignKey("screenplays.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="active")    # active（进行中）| concluded（已完结）
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None)
    )
    pc_tts_voice: Mapped[str] = mapped_column(String(120), default="")  # PC 的 TTS 配音声线
    concluded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # 完结时间
    npcs_json: Mapped[str] = mapped_column(Text, default="[]")  # NPC 模板列表 (V043 新增)


# ── 剧本改写历史 ──────────────────────────────────────────
# 每次玩家做出重大决策触发大纲重写时，追加一条记录（append-only log）。
# 只追加、不修改，保证历史可追溯，也方便 UI 展示"剧情是怎么演变的"。
class ScreenplayRevision(Base):
    __tablename__ = "screenplay_revisions"
    id: Mapped[int] = mapped_column(primary_key=True)
    screenplay_id: Mapped[int] = mapped_column(ForeignKey("screenplays.id"))  # 归属剧本
    revision_num: Mapped[int] = mapped_column(default=1)              # 第几次改写
    trigger_turn: Mapped[int] = mapped_column(default=0)             # 哪个回合触发了改写
    trigger_description: Mapped[str] = mapped_column(Text, default="")  # 触发原因描述
    before_chapters_json: Mapped[str] = mapped_column(Text, default="[]")  # 改写前的章节 JSON
    after_chapters_json: Mapped[str] = mapped_column(Text, default="[]")   # 改写后的章节 JSON
    diff_summary: Mapped[str] = mapped_column(Text, default="")      # 差异摘要（LLM 生成）
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None)
    )


# ── 资源库 ────────────────────────────────────────────────
# 存储图片、音频、字体等资源文件的元数据。
# 支持三种来源：
#   local   → 用户上传到 app_dir 下的本地文件
#   http    → 远程 URL（如 CDN 图片）
#   builtin → 应用内置资源（打包在安装包里）
# 实际的文件内容不存在数据库里（太大），只存路径/URL。
class Asset(Base):
    __tablename__ = "assets"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(20))           # image（图片）| audio（音频）| font（字体）
    source: Mapped[str] = mapped_column(String(20), default="local")  # local | http | builtin
    file_path: Mapped[str] = mapped_column(Text, default="")          # 绝对路径（source=local/builtin 时使用）
    url: Mapped[str] = mapped_column(Text, default="")                # 完整 URL（source=http 时使用）
    mime: Mapped[str] = mapped_column(String(60), default="")         # MIME 类型，如 image/jpeg
    width: Mapped[int] = mapped_column(default=0)           # 图片宽度（非图片资源为 0）
    height: Mapped[int] = mapped_column(default=0)          # 图片高度
    duration_ms: Mapped[int] = mapped_column(default=0)     # 音频时长毫秒（非音频为 0）
    tag_json: Mapped[str] = mapped_column(Text, default="{}")         # 标签字典，用于筛选
    title: Mapped[str] = mapped_column(String(200), default="")       # 资源标题（用户可见）
    uploaded_by: Mapped[str] = mapped_column(String(20), default="user")  # 上传来源："user" 或 "system"
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None)
    )


# ── 资源链接（多对多） ────────────────────────────────────
# 将资源（Asset）挂载到游戏内的各类对象（世界/角色/NPC/剧本/……）。
# 同一个资源可以被多个对象使用（如一张图片同时作为世界封面和章节插图）。
# 通过 owner_type + owner_id 实现"通用多态外键"——
# 避免为每种对象类型各建一张关联表。
class AssetLink(Base):
    __tablename__ = "asset_links"
    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id"))
    # owner_type 是目标表名的简称；owner_id 是目标行的 id
    # 例：owner_type="npc", owner_id=42 → 表示 npcs 表里 id=42 的 NPC
    # 这种模式叫"多态关联"，代价是不能用数据库 FK 约束保证一致性
    owner_type: Mapped[str] = mapped_column(String(20))     # world | character | npc | screenplay | chapter | location | session
    owner_id: Mapped[int] = mapped_column()                 # 目标对象的 id
    slot: Mapped[str] = mapped_column(String(40))           # 挂载位置：cover（封面）| avatar（头像）| bgm（背景音乐）| ambient（环境音）| scene（场景图）
    extra_json: Mapped[str] = mapped_column(Text, default="{}")  # 额外配置，如音量、循环设置
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None)
    )


# ── 玩家反馈 ──────────────────────────────────────────────
# 玩家在游戏中提交的 bug 报告、功能建议或好评。
# 关联到具体的回合和消息，方便开发者复现问题。
class Feedback(Base):
    __tablename__ = "feedbacks"
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"))
    turn: Mapped[int] = mapped_column(default=0)                    # 反馈发生时的回合号
    message_id: Mapped[int | None] = mapped_column(ForeignKey("messages.id"), nullable=True)  # 关联的具体消息（可选）
    kind: Mapped[str] = mapped_column(String(20), default="other")  # bug | suggestion（建议）| praise（好评）| other
    content: Mapped[str] = mapped_column(Text)                      # 反馈内容
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None)
    )


# ── 地点 ──────────────────────────────────────────────────
# GM 发出 <location_enter> 标签时自动登记新地点，或更新 is_current 标记。
# 地点表是运行时生成的（由 GM 叙事驱动），不是预先定义好的。
# 这和 WorldLocation（预定义的开放世界地点模板）不同。
class Location(Base):
    __tablename__ = "locations"
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"))
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")          # GM 的描述文字
    first_visited_turn: Mapped[int] = mapped_column(default=0)          # 首次到达的回合
    last_visited_turn: Mapped[int] = mapped_column(default=0)           # 最近到达的回合
    is_current: Mapped[bool] = mapped_column(default=False)             # True = 玩家当前所在地（全局只有一个为 True）
    items_json: Mapped[str] = mapped_column(Text, default="[]")         # 场景内的道具列表


# ── 场景拓扑边（v0.10） ────────────────────────────────────
# 记录地点之间的"拓扑关系"（哪些地方相邻/相连/包含）。
# 用有向图（有向边）表示，from_loc_id → to_loc_id。
# 拓扑信息用于：
#   1. 前端渲染场景地图
#   2. 检测"无 edge 跨场景"（玩家突然到了一个没有连接的地方）
class LocationEdge(Base):
    """v0.10 — 场景拓扑边。

    relation 取值（语义固定）：
      contains   — A 包含 B（修道院 contains 实验室）
      adjacent   — A 与 B 物理相邻（同层、可走过去）
      connects   — A 通过某途径连到 B
      blocked    — 已知存在的连接但当前不可走

    边是有向的；contains 一般只 emit 父→子方向。
    """
    __tablename__ = "location_edges"
    id: Mapped[int] = mapped_column(primary_key=True)
    # index=True 在这列上建数据库索引，加速 WHERE session_id = ? 查询
    session_id: Mapped[int] = mapped_column(
        ForeignKey("sessions.id"), index=True
    )
    from_loc_id: Mapped[int] = mapped_column(ForeignKey("locations.id"))  # 起点地点 id
    to_loc_id: Mapped[int] = mapped_column(ForeignKey("locations.id"))    # 终点地点 id
    relation: Mapped[str] = mapped_column(String(20))                     # contains | adjacent | connects | blocked
    description: Mapped[str] = mapped_column(Text, default="")           # 关系描述，如"一条暗道"
    introduced_turn: Mapped[int] = mapped_column(default=0)              # 首次发现该连接的回合

    # UniqueConstraint 声明联合唯一约束：
    # 同一 session 里，同一对地点之间，同一种 relation 只能有一条边。
    # 防止 GM 重复 emit 同一段拓扑信息导致重复插入。
    __table_args__ = (
        UniqueConstraint(
            "session_id", "from_loc_id", "to_loc_id", "relation",
            name="uq_location_edge",  # 约束名（数据库层面的名字）
        ),
    )


# ── 隐藏事件（GM 专用） ───────────────────────────────────
# 玩家看不到但 GM 必须记住的"定时炸弹"：
#   - 受伤后的流血效果（几回合后加重）
#   - 毒素（定期扣属性）
#   - 秘密（某个 NPC 知道的事）
#   - 截止日期（如"明天日落前必须完成任务"）
# 每回合这些事件自动注入到 GM 的 key_facts 里，
# 让 GM 在合适时机触发后果，增加真实感和紧张感。
class HiddenEvent(Base):
    __tablename__ = "hidden_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"))
    subject: Mapped[str] = mapped_column(String(120), default="")   # 作用对象，如"PC"、"侦探张三"
    kind: Mapped[str] = mapped_column(String(60))                   # 类型：injury（受伤）| poison（中毒）| deadline（截止日）| …
    severity: Mapped[int] = mapped_column(default=2)                # 严重程度：1=轻微 2=中等 3=严重
    description: Mapped[str] = mapped_column(Text, default="")      # 详细描述（GM 可见）
    consequence: Mapped[str] = mapped_column(Text, default="")      # 未处理的后果（GM 参考）
    introduced_turn: Mapped[int] = mapped_column(default=0)         # 首次出现的回合
    trigger_turn: Mapped[int | None] = mapped_column(nullable=True) # 预计触发回合（仅参考，可以为 None）
    status: Mapped[str] = mapped_column(String(20), default="active")  # active（进行中）| resolved（已解决）| triggered（已触发）
    resolution: Mapped[str] = mapped_column(Text, default="")          # 解决方式描述
    resolved_turn: Mapped[int | None] = mapped_column(nullable=True)   # 解决时的回合号


# ── 势力 ──────────────────────────────────────────────────
# 游戏内的组织/派系（如"皇家骑士团"、"地下犯罪帮会"）。
# PC 的声誉（pc_reputation）影响该势力 NPC 的态度。
# hostile_to_json / allied_to_json 描述势力间的关系，
# 影响 GM 在叙事中如何处理两个势力的 NPC 相遇。
class Faction(Base):
    __tablename__ = "factions"
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"))
    name: Mapped[str] = mapped_column(String(120))
    ideology: Mapped[str] = mapped_column(Text, default="")     # 一句话立场描述
    description: Mapped[str] = mapped_column(Text, default="")  # 30-80 字背景介绍
    leader_npc_id: Mapped[int | None] = mapped_column(ForeignKey("npcs.id"), nullable=True)  # 领袖 NPC（可选）
    pc_reputation: Mapped[int] = mapped_column(default=0)       # PC 在该势力的声誉 -100..100
    hostile_to_json: Mapped[str] = mapped_column(Text, default="[]")  # 敌对势力名字列表（JSON）
    allied_to_json: Mapped[str] = mapped_column(Text, default="[]")   # 盟友势力名字列表（JSON）
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None)
    )


# ============================================================
# v0.10 — Stateful 多 Agent 的对话历史持久化
# ============================================================
# Director 每 5 回合 / 重大事件触发一次，看自己的"剧情决策"历史；
# 每个主要 NPC 一条独立 stream，看自己的"听到/说过"历史。
# Scene agent 复用 messages 表（输出本来就是玩家可见的 assistant 内容）。
#
# 设计思路：
#   - AgentStream 是一个"持久化对话线程"（类比 OpenAI Threads API）
#   - AgentMessage 是线程里的每一条消息（类比 OpenAI Messages API）
#   - 不同的 Agent（Director / NPC_A / NPC_B）各有独立的消息历史，
#     互不干扰，但都归属于同一个 Session。

class AgentStream(Base):
    __tablename__ = "agent_streams"
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("sessions.id"), index=True   # 常用于 WHERE session_id=? 过滤，加索引加速
    )
    # "gm_director"（剧情导演 Agent）| "npc"（NPC 自主 Agent）
    kind: Mapped[str] = mapped_column(String(20))
    # NPC 名字（kind="npc" 时填写）；gm_director 填空字符串。
    # 同一 session 里 (kind, ref) 组合唯一，见下方 UniqueConstraint。
    ref: Mapped[str] = mapped_column(String(120), default="")
    # 此 stream 上次实际跑 LLM 的 turn 号（Director 用来判断间隔：每 5 回合才跑一次）
    last_run_turn: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None)
    )

    # 联合唯一约束：同一 session 里，同一 kind 和 ref 只能有一条 stream。
    # 防止意外创建重复的 Director stream 或同名 NPC 的重复 stream。
    __table_args__ = (
        UniqueConstraint(
            "session_id", "kind", "ref", name="uq_agent_stream"
        ),
    )


class AgentMessage(Base):
    __tablename__ = "agent_messages"
    id: Mapped[int] = mapped_column(primary_key=True)
    stream_id: Mapped[int] = mapped_column(
        ForeignKey("agent_streams.id"), index=True  # 常用于 WHERE stream_id=? 查历史，加索引
    )
    turn: Mapped[int] = mapped_column(default=0, index=True)  # 所属游戏回合（也加索引，方便按回合查询）
    # "system"（系统提示）| "user"（喂给 Agent 的输入）| "assistant"（Agent 的输出）
    role: Mapped[str] = mapped_column(String(10))
    content: Mapped[str] = mapped_column(Text)               # 消息内容
    # True = 这条消息是旧消息的压缩摘要（替换了被移出上下文窗口的历史消息）
    is_summary: Mapped[bool] = mapped_column(default=False)
    tokens_in: Mapped[int] = mapped_column(default=0)        # 该请求消耗的输入 token 数
    tokens_out: Mapped[int] = mapped_column(default=0)       # 该请求消耗的输出 token 数
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None)
    )


# ── 开放世界框架（WorldFramework 层） ────────────────────
# ============================================================
# 下面的 WorldFramework 及相关表实现"开放世界"功能：
#
# 架构分层：
#   WorldFramework（只读模板）
#     ├── WorldLocation（预定义地点）
#     ├── WorldFaction（预定义势力）
#     ├── WorldNPCTemplate（预定义 NPC 模板）
#     ├── WorldEvent（预定义可触发事件）
#     └── Campaign（主线战役：多个阶段）
#
#   Session（运行时存档）
#     ├── SessionLocationState（覆盖地点状态：destroyed/damaged）
#     ├── SessionNpcState（覆盖 NPC 状态：位置/好感/存活）
#     ├── SessionEventState（记录事件是否已触发）
#     ├── SessionFactionState（覆盖势力张力/PC 声誉）
#     └── SessionCampaignState（记录战役阶段进度）
#
# 好处：同一个世界框架可以被多个存档共享，各存档有独立的运行时状态。
# ============================================================

class WorldFramework(Base):
    # 开放世界的顶层容器，相当于"世界地图模板"
    __tablename__ = "world_frameworks"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    genre: Mapped[str] = mapped_column(String(60), default="")       # 类型：fantasy/sci-fi/horror/…
    style: Mapped[str] = mapped_column(String(60), default="")       # 风格：gritty/whimsical/…
    description_md: Mapped[str] = mapped_column(Text, default="")    # 框架背景 Markdown
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None)
    )


class WorldLocation(Base):
    # 开放世界里的预定义地点（城市/地牢/野外/地标）
    __tablename__ = "world_locations"
    id: Mapped[int] = mapped_column(primary_key=True)
    framework_id: Mapped[int] = mapped_column(ForeignKey("world_frameworks.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    description_md: Mapped[str] = mapped_column(Text, default="")
    # city（城市）| dungeon（地牢）| wilderness（野外）| landmark（地标）
    location_type: Mapped[str] = mapped_column(String(40), default="city")
    # 连接信息 JSON 列表，格式：
    # [{target_id, direction, distance, travel_turns}]
    # distance: 0=同地点, 1=相邻, 2=近处, 3+=远处
    connections_json: Mapped[str] = mapped_column(Text, default="[]")
    controlling_faction_id: Mapped[int | None] = mapped_column(
        ForeignKey("world_factions.id"), nullable=True  # 控制该地点的势力（可选）
    )
    # 地点的初始状态：normal（正常）| damaged（受损）| destroyed（摧毁）
    initial_state: Mapped[str] = mapped_column(String(20), default="normal")
    # 向导显式选择的玩家开局地点；旧框架无标记时运行时回退到首个地点。
    is_start: Mapped[bool] = mapped_column(default=False)


class WorldFaction(Base):
    # 开放世界里的预定义势力（王国/帮派/教团/……）
    __tablename__ = "world_factions"
    id: Mapped[int] = mapped_column(primary_key=True)
    framework_id: Mapped[int] = mapped_column(ForeignKey("world_frameworks.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    description_md: Mapped[str] = mapped_column(Text, default="")
    # JSON list of faction IDs（竞争对手/盟友势力的 id 列表）
    rival_factions_json: Mapped[str] = mapped_column(Text, default="[]")
    ally_factions_json: Mapped[str] = mapped_column(Text, default="[]")
    # 势力张力规则，格式：{"passive_gain_per_turn": N, "threshold_conflict": N}
    # passive_gain_per_turn = 每回合自动增加的张力值
    # threshold_conflict = 张力超过此值时触发冲突事件
    tension_rules_json: Mapped[str] = mapped_column(Text, default="{}")


class WorldNPCTemplate(Base):
    # NPC 模板：定义 NPC 的固定属性（名字/背景/阵营）
    # 游戏运行时会基于模板创建 SessionNpcState 来存储可变状态
    __tablename__ = "world_npc_templates"
    id: Mapped[int] = mapped_column(primary_key=True)
    framework_id: Mapped[int] = mapped_column(ForeignKey("world_frameworks.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    # "male" | "female" | "" (unset)
    gender: Mapped[str] = mapped_column(String(10), default="")
    role: Mapped[str] = mapped_column(String(120), default="")       # NPC 职能，如"商人"、"守卫队长"
    description_md: Mapped[str] = mapped_column(Text, default="")
    motivation: Mapped[str] = mapped_column(Text, default="")        # NPC 的动机/目标
    home_location_id: Mapped[int | None] = mapped_column(
        ForeignKey("world_locations.id"), nullable=True  # 默认所在地点
    )
    faction_id: Mapped[int | None] = mapped_column(
        ForeignKey("world_factions.id"), nullable=True   # 所属势力
    )
    avatar_asset_id: Mapped[int | None] = mapped_column(
        ForeignKey("assets.id"), nullable=True           # 头像资源
    )
    # NPC 主动联系 PC 的触发条件：
    # contact_favor_threshold = 好感度达到此值时考虑主动联系
    # contact_cooldown_turns  = 两次主动联系之间的最小间隔回合数
    contact_favor_threshold: Mapped[int] = mapped_column(default=70)
    contact_cooldown_turns: Mapped[int] = mapped_column(default=10)
    # v0.53 — 1-sentence verbal tic injected into npc_actor system prompt
    speech_pattern: Mapped[str] = mapped_column(Text, default="")


class WorldEvent(Base):
    # 可触发的世界事件（政变/自然灾害/势力冲突/……）
    # 每个事件有触发条件（trigger_conditions_json），GM 检测条件是否满足。
    __tablename__ = "world_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    framework_id: Mapped[int] = mapped_column(ForeignKey("world_frameworks.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    summary_md: Mapped[str] = mapped_column(Text, default="")
    # 事件影响范围：
    # "location"（影响某地点）| "faction"（影响某势力）| "global"（全局）
    scope_type: Mapped[str] = mapped_column(String(20), default="location")
    # 对应的 location_id 或 faction_id（字符串形式），global 时为 ""
    scope_ref: Mapped[str] = mapped_column(String(40), default="")
    # 重要性 1=次要 … 5=关键；影响 Director 优先级和谣言阈值（≥3 才生成谣言）
    importance: Mapped[int] = mapped_column(default=2)
    # 触发条件列表（AND 逻辑），JSON 格式详见规格文档 Section 1
    trigger_conditions_json: Mapped[str] = mapped_column(Text, default="[]")
    # 事件自己的可验证完成边界；为空的旧事件继续由 Director 语义判断。
    completion_criteria_md: Mapped[str] = mapped_column(Text, default="")
    is_repeatable: Mapped[bool] = mapped_column(default=False)  # 是否可重复触发
    cooldown_turns: Mapped[int] = mapped_column(default=0)      # 重复触发的冷却回合数


class Campaign(Base):
    # 主线战役：将多个事件组织成有先后顺序的"阶段"（Phase）。
    # 每个 WorldFramework 最多一个 Campaign（unique=True）。
    __tablename__ = "campaigns"
    id: Mapped[int] = mapped_column(primary_key=True)
    # one Campaign per WorldFramework (nullable: framework can have no campaign)
    framework_id: Mapped[int] = mapped_column(
        ForeignKey("world_frameworks.id"), unique=True  # unique=True 强制一对一
    )
    name: Mapped[str] = mapped_column(String(120))
    # 阶段列表 JSON，每个阶段格式：
    # {phase_id, name, description, prerequisite_phase_ids, key_event_ids, required_count}
    # prerequisite_phase_ids = 前置阶段（必须完成这些阶段才能解锁当前阶段）
    # key_event_ids + required_count = 需要触发多少个关键事件才算完成当前阶段
    phases_json: Mapped[str] = mapped_column(Text, default="[]")


# ── Session-level 世界状态覆盖层 ─────────────────────────
# 下面的表存储"某个存档里，世界模板的哪些状态被改变了"。
# WorldFramework 是不可变的只读模板；
# Session 通过 SessionXxxState 表存储运行时的覆盖值。
# 读取时：先看 SessionXxxState 有没有覆盖，没有就用模板默认值。

class SessionLocationState(Base):
    # 存档里对某个地点状态的覆盖（如"城堡被攻陷，现在是 destroyed"）
    __tablename__ = "session_location_states"
    # 联合主键：(session_id, location_id) 组合唯一，确保每个存档的每个地点只有一条覆盖记录
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"), primary_key=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("world_locations.id"), primary_key=True)
    # "normal"（正常）| "damaged"（受损）| "destroyed"（摧毁）
    status: Mapped[str] = mapped_column(String(20), default="normal")
    notes: Mapped[str] = mapped_column(Text, default="")    # GM 追加的备注


class SessionNpcState(Base):
    # 存档里对某个 NPC 运行时状态的覆盖（位置/好感度/是否存活/……）
    __tablename__ = "session_npc_states"
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"), primary_key=True)
    npc_template_id: Mapped[int] = mapped_column(
        ForeignKey("world_npc_templates.id"), primary_key=True  # 对应哪个 NPC 模板
    )
    current_location_id: Mapped[int | None] = mapped_column(
        ForeignKey("world_locations.id"), nullable=True  # 当前所在地点（可覆盖 home_location_id）
    )
    favor: Mapped[int] = mapped_column(default=0)           # PC 与该 NPC 的当前好感度
    is_companion: Mapped[bool] = mapped_column(default=False)  # True = 已加入队伍
    is_revealed: Mapped[bool] = mapped_column(default=False)   # True = 玩家已知道这个 NPC 的存在
    is_alive: Mapped[bool] = mapped_column(default=True)       # False = NPC 已死亡
    last_contact_turn: Mapped[int] = mapped_column(default=0)  # 上次主动联系 PC 的回合


class SessionEventState(Base):
    # 存档里对某个世界事件状态的追踪（是否已触发/完成）
    __tablename__ = "session_event_states"
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"), primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("world_events.id"), primary_key=True)
    # "pending"（待触发）| "triggered"（已触发）| "completed"（已完成）
    status: Mapped[str] = mapped_column(String(20), default="pending")
    triggered_turn: Mapped[int] = mapped_column(default=0)      # 触发时的回合号
    # GM 可以为这个存档覆盖事件的标准摘要描述（Optional）
    summary_override: Mapped[str | None] = mapped_column(Text, nullable=True)
    # track rumor delivery to avoid re-delivery（防止重复推送谣言给玩家）
    rumor_delivered: Mapped[bool] = mapped_column(default=False)
    rumor_delivered_turn: Mapped[int] = mapped_column(default=0)


class SessionFactionState(Base):
    # 存档里对某个势力运行时状态的覆盖（张力值/PC 声誉）
    __tablename__ = "session_faction_states"
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"), primary_key=True)
    faction_id: Mapped[int] = mapped_column(ForeignKey("world_factions.id"), primary_key=True)
    # tension（张力）随时间被动累积；达到阈值时触发冲突事件（见 tension_rules_json）
    tension: Mapped[int] = mapped_column(default=0)
    pc_reputation: Mapped[int] = mapped_column(default=0)  # PC 在该势力的声誉 -100..100
    is_active: Mapped[bool] = mapped_column(default=True)  # False = 该势力已灭亡/退出舞台


class SessionCampaignState(Base):
    # 存档里的战役进度（当前阶段 + 已触发的关键事件）
    __tablename__ = "session_campaign_states"
    # one row per session (session_id is PK)
    # session_id 单独作为主键（不是联合主键）→ 每个存档只有一条战役进度记录
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"), primary_key=True)
    current_phase_id: Mapped[int | None] = mapped_column(nullable=True)  # 当前战役阶段 id，None = 尚未开始
    # 当前阶段内已触发的关键事件 id 列表（JSON），用于判断是否满足阶段完成条件
    triggered_key_events_json: Mapped[str] = mapped_column(Text, default="[]")
