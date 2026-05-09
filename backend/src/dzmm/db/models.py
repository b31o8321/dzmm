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
class World(Base):
    # __tablename__ 指定数据库中的表名（相当于 @Table(name="worlds")）
    __tablename__ = "worlds"

    # primary_key=True → 自增主键（SQLite/Postgres 都支持）
    id: Mapped[int] = mapped_column(primary_key=True)

    # String(120) → VARCHAR(120)；Text → 无限长文本（相当于 TEXT/CLOB）
    name: Mapped[str] = mapped_column(String(120))
    content_md: Mapped[str] = mapped_column(Text)           # 世界设定 Markdown 全文

    # default= 是 Python 侧的默认值（INSERT 时由 SQLAlchemy 填充，不是数据库默认值）
    rules_json: Mapped[str] = mapped_column(Text, default='{"mode":"light"}')
    style: Mapped[str] = mapped_column(String(40), default="realistic")

    # lambda 让每次 INSERT 都调用一次 datetime.now()，而不是模块加载时求一次值。
    # 【Java 对比】相当于 @PrePersist 里手动设置时间戳。
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None)
    )


# ── 角色（PC） ────────────────────────────────────────────
class Character(Base):
    __tablename__ = "characters"
    id: Mapped[int] = mapped_column(primary_key=True)

    # ForeignKey("worlds.id") → 声明外键列，但不自动加载关联对象
    world_id: Mapped[int] = mapped_column(ForeignKey("worlds.id"))
    name: Mapped[str] = mapped_column(String(120))
    # gender: "male" | "female" — enum-like, kept simple per design intent.
    # Empty string = legacy data created before the column existed.
    gender: Mapped[str] = mapped_column(String(10), default="")
    profile_md: Mapped[str] = mapped_column(Text)           # 角色背景 Markdown
    base_stats_json: Mapped[str] = mapped_column(Text)      # 初始属性 JSON，如 {"hp":20}

    portrait_path: Mapped[str] = mapped_column(String(255), default="")
    xp: Mapped[int] = mapped_column(default=0)
    level: Mapped[int] = mapped_column(default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None)
    )

    # relationship() 声明 ORM 关联，访问 character.world 时 SQLAlchemy 自动查询。
    # 【Java 对比】相当于 @ManyToOne + @JoinColumn，默认懒加载。
    world: Mapped[World] = relationship()


# ── LLM 模型配置 ──────────────────────────────────────────
# 存储 Ollama / OpenAI 兼容接口的连接信息，每个对话可以独立选模型。
class ModelConfig(Base):
    __tablename__ = "model_configs"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))           # 用户起的别名
    type: Mapped[str] = mapped_column(String(40))            # "ollama" | "openai"
    base_url: Mapped[str] = mapped_column(String(255))       # API 基础 URL
    model_name: Mapped[str] = mapped_column(String(120))     # 模型标识符

    # Mapped[str | None] → 允许 NULL 的列。Python 3.10+ 的联合类型语法。
    # 【Java 对比】相当于 @Column(nullable=true)，但写在类型里而非注解里。
    api_key_ref: Mapped[str | None] = mapped_column(String(120), nullable=True)
    timeout: Mapped[float] = mapped_column(default=60.0)
    params_json: Mapped[str] = mapped_column(Text, default='{}')  # 额外参数，如 top_k
    # v0.9.1: 0 = 不限制；>0 = 进程内同 cfg 并发上限。智谱 glm-4-flash 免费层
    # 全局并发=1 → 必须 max_concurrent=1，否则只要有 2 个请求同时在飞就全 429。
    max_concurrent: Mapped[int] = mapped_column(default=0)

    # v0.10: 用户显式指定的"默认模型"。Wizard / 一次性 LLM 调用（没 session
    # 上下文，没法挑 gm_model_config_id 时）会用它。同时只有一行 is_default=True，
    # 在 set_default endpoint 里强制保证。
    is_default: Mapped[bool] = mapped_column(default=False)


# ── 游戏会话 ──────────────────────────────────────────────
# 一局游戏。关联世界、角色和两个 LLM（GM 叙事引擎 + 摘要引擎）。
class Session(Base):
    __tablename__ = "sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))

    world_id: Mapped[int] = mapped_column(ForeignKey("worlds.id"))
    character_id: Mapped[int] = mapped_column(ForeignKey("characters.id"))
    screenplay_id: Mapped[int | None] = mapped_column(ForeignKey("screenplays.id"), nullable=True)

    # 同一张表可以有多个外键指向同一目标表（两个 LLM 配置）
    gm_model_config_id: Mapped[int] = mapped_column(ForeignKey("model_configs.id"))
    summarizer_model_config_id: Mapped[int] = mapped_column(ForeignKey("model_configs.id"))

    turn_count: Mapped[int] = mapped_column(default=0)       # 已完成的回合数
    schema_version: Mapped[int] = mapped_column(default=1)   # 数据库 schema 版本号，用于迁移

    # 复杂结构存为 JSON 字符串（SQLite 没有原生 JSON 列类型）
    recall_pending_json: Mapped[str] = mapped_column(Text, default="[]")  # 待回忆的事件列表
    pc_mood_json: Mapped[str] = mapped_column(Text, default="{}")
    settings_json: Mapped[str] = mapped_column(Text, default="{}")        # 用户开关，如 director_pass

    doom_score: Mapped[int] = mapped_column(Integer, default=0)           # 厄运值 0-100
    scene_turn_count: Mapped[int] = mapped_column(Integer, default=0)     # 当前场景已停留回合数
    world_time_json: Mapped[str] = mapped_column(Text, default='{"day": 1, "period": "morning", "weather": "clear"}')

    # v0.10 — 上一回合 _apply_location_enter 检测到的"无 edge 跨场景"警告，
    # 下回合 _build_key_facts drain 一次注入 prompt 强制 GM 补 emit。
    topology_warning_json: Mapped[str] = mapped_column(Text, default="[]")

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None)
    )
    last_played: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None)
    )


# ── 对话消息 ──────────────────────────────────────────────
# 每一回合产生两条 Message：role="user"（玩家行动）+ role="assistant"（GM 回复）
class Message(Base):
    __tablename__ = "messages"
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"))

    # role 遵循 OpenAI 约定："system" / "user" / "assistant"
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)               # 原始 LLM 输出（含 XML 标签）
    turn: Mapped[int] = mapped_column(default=0)             # 所属回合序号

    tokens_in: Mapped[int] = mapped_column(default=0)        # 输入 token 数（计费用）
    tokens_out: Mapped[int] = mapped_column(default=0)       # 输出 token 数
    summarized: Mapped[bool] = mapped_column(default=False)  # 是否已被摘要器压缩过

    events_json: Mapped[str] = mapped_column(Text, default="[]")  # 本回合的结构化事件列表
    parts_json: Mapped[str] = mapped_column(Text, default="[]")   # 说话气泡分段数据
    prompt_json: Mapped[str] = mapped_column(Text, default="")    # debug: 发送给 LLM 的完整 prompt（仅 debug_mode 时填充）
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None)
    )


# ── 剧情摘要 ──────────────────────────────────────────────
# 每个 Session 只有一条摘要行（主键是 session_id，而非自增 id）。
# 摘要器每隔若干回合把旧消息压缩进来，以防 LLM 上下文窗口溢出。
class StorySummary(Base):
    __tablename__ = "story_summaries"
    # 直接用外键作主键 → 一对一关系（session : summary = 1:1）
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"), primary_key=True)
    summary_text: Mapped[str] = mapped_column(Text, default="")
    last_summarized_msg_id: Mapped[int] = mapped_column(default=0)
    summary_tokens: Mapped[int] = mapped_column(default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None)
    )


# ── 角色实时状态 ──────────────────────────────────────────
# base_stats_json 是初始值；CharState 是每局游戏中随时变化的当前值。
class CharState(Base):
    __tablename__ = "char_states"
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"), primary_key=True)
    stats_json: Mapped[str] = mapped_column(Text, default="{}")      # 当前属性值
    inventory_json: Mapped[str] = mapped_column(Text, default="[]")  # 当前物品栏
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None)
    )


# ── NPC ──────────────────────────────────────────────────
class NPC(Base):
    __tablename__ = "npcs"
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"))
    name: Mapped[str] = mapped_column(String(120))
    # gender: "male" | "female" — strict enum for new content; "" means
    # legacy data (created before the column existed).
    gender: Mapped[str] = mapped_column(String(10), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    favor: Mapped[int] = mapped_column(default=0)            # 好感度（正=友好，负=敌对）
    state: Mapped[str] = mapped_column(String(60), default="未知")  # 当前状态描述
    last_seen_turn: Mapped[int] = mapped_column(default=0)
    notes_json: Mapped[str] = mapped_column(Text, default="[]")
    purpose: Mapped[str] = mapped_column(Text, default="")   # 该 NPC 在剧情中的作用
    archetype: Mapped[str] = mapped_column(String(120), default="")  # 原型，如"导师"
    affinity_json: Mapped[str] = mapped_column(Text, default="{}")
    pinned: Mapped[bool] = mapped_column(default=False)      # 是否钉在侧边栏顶部
    emotion_json: Mapped[str] = mapped_column(Text, default="{}")
    revealed_json: Mapped[str] = mapped_column(Text, default='{"name": true}')  # 哪些信息已对玩家揭示
    current_location: Mapped[str | None] = mapped_column(String(120), nullable=True, default=None)
    last_initiative_turn: Mapped[int] = mapped_column(default=0)  # NPC 上次主动出现的回合
    tts_voice: Mapped[str] = mapped_column(String(120), default="")
    faction_id: Mapped[int | None] = mapped_column(ForeignKey("factions.id"), nullable=True)


# ── 剧情线索 ──────────────────────────────────────────────
class PlotThread(Base):
    __tablename__ = "plot_threads"
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"))
    type: Mapped[str] = mapped_column(String(40))            # quest | hook | mystery | major_event
    description: Mapped[str] = mapped_column(Text)
    introduced_turn: Mapped[int] = mapped_column(default=0)
    importance: Mapped[int] = mapped_column(default=2)       # 1=次要 2=普通 3=主线
    status: Mapped[str] = mapped_column(String(20), default="active")  # active|resolved|abandoned
    resolution: Mapped[str] = mapped_column(Text, default="")


# ── NPC 关系网 ────────────────────────────────────────────
class NpcRelation(Base):
    """用名字（而非外键）关联两个 NPC，避免 GM 提到 NPC 时必须先在 DB 建档。"""
    __tablename__ = "npc_relations"
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"))
    npc_a: Mapped[str] = mapped_column(String(120))          # NPC 名字（不是 FK）
    npc_b: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(60))            # 父女/恋人/对手/…
    description: Mapped[str] = mapped_column(Text, default="")
    introduced_turn: Mapped[int] = mapped_column(default=0)


# ── 玩家目标 ──────────────────────────────────────────────
class PCGoal(Base):
    """GM 通过 <pc_goal> 标签自动登记/完成目标；活跃目标会注入每回合的 key_facts。"""
    __tablename__ = "pc_goals"
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"))
    description: Mapped[str] = mapped_column(Text)
    priority: Mapped[str] = mapped_column(String(20), default="normal")  # high|normal|low
    status: Mapped[str] = mapped_column(String(20), default="active")    # active|completed|abandoned
    introduced_turn: Mapped[int] = mapped_column(default=0)
    completed_turn: Mapped[int | None] = mapped_column(nullable=True)    # None 表示未完成
    completion_note: Mapped[str] = mapped_column(Text, default="")


# ── 剧本大纲 ──────────────────────────────────────────────
# 开局时由 LLM 生成，包含章节/主线事件/NPC/结局。
# GM 在每回合都能看到进度，确保故事不会原地踏步。
class Screenplay(Base):
    __tablename__ = "screenplays"
    id: Mapped[int] = mapped_column(primary_key=True)

    # nullable=True → session_id 可以为空，表示这是"世界级"共享剧本（v0.2.8）
    session_id: Mapped[int | None] = mapped_column(ForeignKey("sessions.id"), nullable=True)
    world_id: Mapped[int | None] = mapped_column(ForeignKey("worlds.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(120), default="")
    pc_name: Mapped[str] = mapped_column(String(120), default="")
    pc_gender: Mapped[str] = mapped_column(String(10), default="")
    pc_profile_md: Mapped[str] = mapped_column(Text, default="")
    pc_base_stats_json: Mapped[str] = mapped_column(Text, default="{}")
    version: Mapped[int] = mapped_column(default=1)
    genre: Mapped[str] = mapped_column(String(60), default="")
    custom_prompt: Mapped[str] = mapped_column(Text, default="")
    outline_md: Mapped[str] = mapped_column(Text, default="")
    chapters_json: Mapped[str] = mapped_column(Text, default="[]")       # 章节数组（JSON）
    main_characters_json: Mapped[str] = mapped_column(Text, default="[]")
    ending_md: Mapped[str] = mapped_column(Text, default="")
    opening_hook: Mapped[str] = mapped_column(Text, default="")          # 开篇引子（玩家可见）
    current_chapter: Mapped[int] = mapped_column(default=1)
    completed_events_json: Mapped[str] = mapped_column(Text, default="[]")

    # 自引用外键：续集指向原作（树形结构）
    parent_screenplay_id: Mapped[int | None] = mapped_column(ForeignKey("screenplays.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="active")    # active|concluded
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None)
    )
    pc_tts_voice: Mapped[str] = mapped_column(String(120), default="")
    concluded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


# ── 剧本改写历史 ──────────────────────────────────────────
# 每次 <plot_turn> 触发大纲重写时追加一条，只追加不修改（append-only log）。
class ScreenplayRevision(Base):
    __tablename__ = "screenplay_revisions"
    id: Mapped[int] = mapped_column(primary_key=True)
    screenplay_id: Mapped[int] = mapped_column(ForeignKey("screenplays.id"))
    revision_num: Mapped[int] = mapped_column(default=1)
    trigger_turn: Mapped[int] = mapped_column(default=0)
    trigger_description: Mapped[str] = mapped_column(Text, default="")
    before_chapters_json: Mapped[str] = mapped_column(Text, default="[]")
    after_chapters_json: Mapped[str] = mapped_column(Text, default="[]")
    diff_summary: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None)
    )


# ── 资源库 ────────────────────────────────────────────────
# 存储图片、音频、字体等资源文件的元数据。
# 支持本地文件、HTTP 链接、内置资源三种来源。
class Asset(Base):
    __tablename__ = "assets"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(20))           # image | audio | font
    source: Mapped[str] = mapped_column(String(20), default="local")  # local | http | builtin
    file_path: Mapped[str] = mapped_column(Text, default="")          # absolute path under app_dir or builtin/
    url: Mapped[str] = mapped_column(Text, default="")                # populated when source=http
    mime: Mapped[str] = mapped_column(String(60), default="")
    width: Mapped[int] = mapped_column(default=0)           # 0 for non-image
    height: Mapped[int] = mapped_column(default=0)
    duration_ms: Mapped[int] = mapped_column(default=0)     # 0 for non-audio
    tag_json: Mapped[str] = mapped_column(Text, default="{}")
    title: Mapped[str] = mapped_column(String(200), default="")
    uploaded_by: Mapped[str] = mapped_column(String(20), default="user")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None)
    )


# ── 资源链接（多对多） ────────────────────────────────────
# 将资源附加到游戏内各类对象（世界、角色、NPC、剧本等）。
class AssetLink(Base):
    __tablename__ = "asset_links"
    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id"))
    owner_type: Mapped[str] = mapped_column(String(20))     # world | character | npc | screenplay | chapter | location | session
    owner_id: Mapped[int] = mapped_column()
    slot: Mapped[str] = mapped_column(String(40))           # cover | avatar | bgm | ambient | scene
    extra_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None)
    )


# ── 玩家反馈 ──────────────────────────────────────────────
class Feedback(Base):
    __tablename__ = "feedbacks"
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"))
    turn: Mapped[int] = mapped_column(default=0)
    message_id: Mapped[int | None] = mapped_column(ForeignKey("messages.id"), nullable=True)
    kind: Mapped[str] = mapped_column(String(20), default="other")  # bug|suggestion|praise|other
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None)
    )


# ── 地点 ──────────────────────────────────────────────────
# GM 发出 <location_enter> 标签时自动登记，is_current 标记当前所在。
class Location(Base):
    __tablename__ = "locations"
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"))
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    first_visited_turn: Mapped[int] = mapped_column(default=0)
    last_visited_turn: Mapped[int] = mapped_column(default=0)
    is_current: Mapped[bool] = mapped_column(default=False)
    items_json: Mapped[str] = mapped_column(Text, default="[]")  # 场景内的物品列表


# ── 场景拓扑边（v0.10） ────────────────────────────────────
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
    session_id: Mapped[int] = mapped_column(
        ForeignKey("sessions.id"), index=True
    )
    from_loc_id: Mapped[int] = mapped_column(ForeignKey("locations.id"))
    to_loc_id: Mapped[int] = mapped_column(ForeignKey("locations.id"))
    relation: Mapped[str] = mapped_column(String(20))
    description: Mapped[str] = mapped_column(Text, default="")
    introduced_turn: Mapped[int] = mapped_column(default=0)

    __table_args__ = (
        UniqueConstraint(
            "session_id", "from_loc_id", "to_loc_id", "relation",
            name="uq_location_edge",
        ),
    )


# ── 隐藏事件（GM 专用） ───────────────────────────────────
# 玩家看不到但 GM 必须记住的"定时炸弹"：流血、中毒、秘密、截止日期……
# 每回合自动注入 key_facts，让 GM 能在合适时机触发后果。
class HiddenEvent(Base):
    __tablename__ = "hidden_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"))
    subject: Mapped[str] = mapped_column(String(120), default="")   # 作用对象，如"PC"
    kind: Mapped[str] = mapped_column(String(60))                   # injury/poison/deadline/…
    severity: Mapped[int] = mapped_column(default=2)                # 1=轻微 2=中等 3=严重
    description: Mapped[str] = mapped_column(Text, default="")
    consequence: Mapped[str] = mapped_column(Text, default="")      # GM 参考：会如何演变
    introduced_turn: Mapped[int] = mapped_column(default=0)
    trigger_turn: Mapped[int | None] = mapped_column(nullable=True) # 预计触发回合（仅参考）
    status: Mapped[str] = mapped_column(String(20), default="active")  # active/resolved/triggered
    resolution: Mapped[str] = mapped_column(Text, default="")
    resolved_turn: Mapped[int | None] = mapped_column(nullable=True)


# ── 势力 ──────────────────────────────────────────────────
class Faction(Base):
    __tablename__ = "factions"
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"))
    name: Mapped[str] = mapped_column(String(120))
    ideology: Mapped[str] = mapped_column(Text, default="")     # one-line stance
    description: Mapped[str] = mapped_column(Text, default="")  # 30-80 字背景
    leader_npc_id: Mapped[int | None] = mapped_column(ForeignKey("npcs.id"), nullable=True)
    pc_reputation: Mapped[int] = mapped_column(default=0)       # -100..100
    hostile_to_json: Mapped[str] = mapped_column(Text, default="[]")  # JSON list of faction names
    allied_to_json: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None)
    )


# ============================================================
# v0.10 — Stateful 多 Agent 的对话历史持久化
# ============================================================
# Director 每 5 回合 / 重大事件触发一次，看自己的“剧情决策”历史；
# 每个主要 NPC 一条独立 stream，看自己的“听到/说过”历史。
# Scene agent 复用 messages 表（输出本来就是玩家可见的 assistant 内容）。

class AgentStream(Base):
    __tablename__ = "agent_streams"
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("sessions.id"), index=True
    )
    # "gm_director" | "npc"
    kind: Mapped[str] = mapped_column(String(20))
    # NPC 名字；gm_director 留空字符串。同一 session 不允许重复。
    ref: Mapped[str] = mapped_column(String(120), default="")
    # 此 stream 上次实际跑 LLM 的 turn 号（用来做 Director 的间隔判断）
    last_run_turn: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None)
    )

    __table_args__ = (
        UniqueConstraint(
            "session_id", "kind", "ref", name="uq_agent_stream"
        ),
    )


class AgentMessage(Base):
    __tablename__ = "agent_messages"
    id: Mapped[int] = mapped_column(primary_key=True)
    stream_id: Mapped[int] = mapped_column(
        ForeignKey("agent_streams.id"), index=True
    )
    turn: Mapped[int] = mapped_column(default=0, index=True)
    # "system" | "user" | "assistant"
    role: Mapped[str] = mapped_column(String(10))
    content: Mapped[str] = mapped_column(Text)
    # True 表示这条是压缩后的摘要（替代了被丢弃的旧消息）
    is_summary: Mapped[bool] = mapped_column(default=False)
    tokens_in: Mapped[int] = mapped_column(default=0)
    tokens_out: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None)
    )
