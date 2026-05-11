# ============================================================
# schemas.py — API 数据结构定义（Pydantic 模型）
#
# 「为什么要有这个文件？」
#   FastAPI 使用 Pydantic 在请求/响应时自动校验数据类型。
#   这里定义的每个 class 都是一张「合同」：
#     - *In  结尾的类 = 客户端发给服务器的请求体格式（输入）
#     - *Out 结尾的类 = 服务器返回给客户端的响应体格式（输出）
#   好处：如果客户端少传了字段、传了错误类型，FastAPI 会
#   自动返回 422 错误，不需要手写校验逻辑。
# ============================================================

# BaseModel 是 Pydantic 的基础类，继承它就能获得自动校验能力
from pydantic import BaseModel


# ──────────────────────────────────────────────
# 世界（World）
# ──────────────────────────────────────────────

# WorldIn：创建/更新世界时，客户端需要发送的字段
# 这个类没有 id，因为 id 由数据库自动生成，不需要客户端提供
class WorldIn(BaseModel):
    name: str         # 世界名称，必填
    content_md: str   # 世界书正文（Markdown 格式），必填
    style: str = "realistic"  # 故事风格，默认"写实"；= 号后面是默认值
    rules_mode: str = "light" # 规则强度：light（轻规则）或 heavy（重规则）


# WorldOut：服务器返回给客户端的世界数据
# 继承 WorldIn，表示包含 WorldIn 的所有字段，再额外加上 id
class WorldOut(WorldIn):
    id: int  # 数据库主键，由服务器生成，客户端只读


# ──────────────────────────────────────────────
# 角色（Character）
# ──────────────────────────────────────────────

# CharacterIn：创建/更新角色时的请求体
class CharacterIn(BaseModel):
    world_id: int     # 该角色属于哪个世界（外键），必填
    name: str         # 角色名，必填
    # Per design: enum "male" | "female"; empty = legacy/unset.
    gender: str = ""  # 性别：male / female，空字符串表示未设定（历史遗留数据）
    profile_md: str   # 角色背景故事（Markdown），必填
    base_stats_json: str = "{}"  # 角色基础属性，存为 JSON 字符串，默认空对象


# CharacterOut：服务器返回的角色数据
# 继承 CharacterIn，再加上服务器端计算/存储的字段
class CharacterOut(CharacterIn):
    id: int                   # 数据库主键
    portrait_path: str = ""   # 头像图片路径（服务器本地路径）
    xp: int = 0               # 经验值，默认 0
    level: int = 1            # 等级，从 1 开始


# ──────────────────────────────────────────────
# AI 模型配置（ModelConfig）
# ──────────────────────────────────────────────

# ModelConfigIn：新增/更新模型配置时的请求体
# 「模型配置」= 告诉系统用哪个 AI 接口、哪个模型名、怎么连
class ModelConfigIn(BaseModel):
    name: str          # 配置的自定义名称，如「本地 Qwen」
    type: str          # 接口类型：ollama / openai / zhipu 等
    base_url: str      # API 服务地址，如 http://localhost:11434
    model_name: str    # 实际调用的模型名，如 qwen2.5:7b
    api_key: str | None = None  # API 密钥（可选，本地 Ollama 不需要）
    timeout: float = 60.0       # 请求超时秒数
    max_concurrent: int = 0     # 0 = 不限制；>0 = 进程内并发上限（智谱 free 设 1）


# ModelConfigOut：服务器返回的模型配置数据
# 注意：没有继承 ModelConfigIn，因为返回的字段与输入不完全一样
# 特别地，api_key 敏感，不原样返回，改成只返回 api_key_ref（引用名）
class ModelConfigOut(BaseModel):
    id: int
    name: str
    type: str
    base_url: str
    model_name: str
    api_key_ref: str | None   # API 密钥的引用 ID（真实密钥存在系统密钥链，不暴露）
    timeout: float
    max_concurrent: int = 0
    is_default: bool = False  # 是否为默认模型


# ──────────────────────────────────────────────
# 跑团存档（Session）
# ──────────────────────────────────────────────

# SessionIn：创建跑团存档时的请求体
# Session 是「一次跑团」的核心记录，关联世界、角色、AI 模型
class SessionIn(BaseModel):
    name: str                              # 存档名称
    screenplay_id: int | None = None       # 剧本 ID（新模式：从剧本直接创建，自动建角色）
    world_id: int | None = None            # 世界 ID（旧模式：直接指定）
    character_id: int | None = None        # 角色 ID（旧模式：直接指定）
    framework_id: int | None = None        # v0.11 开放世界框架 ID
    gm_model_config_id: int               # GM（叙事 AI）使用的模型配置 ID，必填
    summarizer_model_config_id: int       # 摘要器（记忆压缩 AI）使用的模型配置 ID，必填


# SessionOut：服务器返回的跑团存档数据
class SessionOut(BaseModel):
    id: int
    name: str
    screenplay_id: int | None = None
    framework_id: int | None = None
    world_id: int           # 最终关联的世界 ID（不管是从剧本还是直接创建）
    character_id: int       # 最终关联的角色 ID
    gm_model_config_id: int
    summarizer_model_config_id: int
    turn_count: int         # 当前已进行的回合数


# ──────────────────────────────────────────────
# 回合操作（Turn）
# ──────────────────────────────────────────────

# TurnRequest：玩家发出行动时的请求体
# 每个「回合」= 玩家输入一个行动 → GM AI 响应
class TurnRequest(BaseModel):
    action: str  # 玩家输入的行动描述，如「我打开那扇门」


# ──────────────────────────────────────────────
# 消息记录（Message）
# ──────────────────────────────────────────────

# MessageOut：服务器返回的单条对话消息
class MessageOut(BaseModel):
    id: int
    role: str          # 消息来源：user（玩家）/ assistant（GM AI）/ system
    content: str       # 消息正文
    turn: int          # 所属回合编号
    tokens_in: int     # 本次请求消耗的输入 token 数（用于统计费用）
    tokens_out: int    # 本次响应产生的输出 token 数
    events: list[dict] = []  # 本回合触发的游戏事件列表（战斗、检定等）


# ──────────────────────────────────────────────
# 隐藏事件（HiddenEvent）
# ──────────────────────────────────────────────

# HiddenEventOut：GM 在幕后埋下的「定时炸弹」事件
# 这些事件玩家不可见，只有 GM AI 和 GM 界面能看到
class HiddenEventOut(BaseModel):
    id: int
    subject: str           # 事件主体（哪个 NPC 或势力）
    kind: str              # 事件类型（如 conspiracy / ambush）
    severity: int          # 严重程度（1-5）
    description: str       # 事件描述
    consequence: str       # 若触发后的后果
    introduced_turn: int   # 在第几回合埋入
    status: str            # 当前状态：pending / triggered / cancelled


# ──────────────────────────────────────────────
# NPC
# ──────────────────────────────────────────────

# NpcOut：服务器返回的 NPC 数据
# NPC = Non-Player Character，非玩家角色（由 GM AI 扮演）
class NpcOut(BaseModel):
    """Shape returned by GET /sessions/{id}/npcs.
    All fields are returned verbatim; `revealed` is the per-field mask the
    frontend uses to render unrevealed fields as '???' / blanks. v0.11."""
    id: int
    name: str
    gender: str = ""
    description: str = ""     # NPC 外貌/性格描述
    favor: int = 0            # 对玩家的好感度（正=友好，负=敌对）
    state: str = ""           # 当前状态（alive / dead / missing 等）
    last_seen_turn: int = 0   # 最后一次与玩家接触的回合
    purpose: str = ""         # NPC 在剧情中的目的
    archetype: str = ""       # 原型标签（ally / villain / neutral 等）
    affinity: dict = {}       # 与其他 NPC 的关系图（NPC ID → 亲密度）
    emotion: dict = {}        # 当前情绪状态（joy / fear / anger 等）
    pinned: bool = False      # 是否被 GM 钉选（常出现的重要 NPC）
    notes: list = []          # GM 备注列表
    revealed: dict[str, bool] = {"name": True}  # 字段可见性掩码，前端据此显示 ???
    tts_voice: str = ""       # TTS（文字转语音）使用的声音 ID


# ──────────────────────────────────────────────
# 剧本（Screenplay）
# ──────────────────────────────────────────────

# ScreenplayStandaloneIn：创建独立剧本时的请求体
# 「独立剧本」= 不依赖预先创建的世界/角色，系统自动生成
class ScreenplayStandaloneIn(BaseModel):
    title: str                              # 剧本标题
    genre: str = ""                         # 类型标签（悬疑 / 奇幻 / 都市 等）
    pc_name: str = ""                       # 玩家角色名（PC = Player Character）
    pc_gender: str = ""                     # 玩家角色性别
    pc_profile_md: str = ""                 # 玩家角色背景（Markdown）
    pc_base_stats_json: str = "{}"          # 玩家角色初始属性
    custom_prompt: str = ""                 # 用户自定义的世界观/规则补充提示词
    outline_md: str = ""                    # 剧本大纲（AI 生成后填入）
    chapters_json: str = "[]"              # 章节列表（JSON 数组）
    main_characters_json: str = "[]"       # 主要角色列表（JSON 数组）
    ending_md: str = ""                     # 结局描述
    opening_hook: str = ""                  # 开场钩子（第一幕引子）
    pc_tts_voice: str = ""                  # 玩家角色 TTS 声音 ID


# ScreenplayStandaloneOut：服务器返回的独立剧本数据
# 继承 ScreenplayStandaloneIn，额外加上服务器端字段
class ScreenplayStandaloneOut(ScreenplayStandaloneIn):
    id: int
    world_id: int                           # 系统为该剧本自动创建的世界 ID
    session_id: int | None = None           # 关联的跑团存档 ID（未开始跑则为空）
    version: int = 1                        # 版本号（PC 重大决策后大纲重写时递增）
    current_chapter: int = 1               # 当前进行到第几章
    completed_events_json: str = "[]"      # 已完成的关键事件列表（JSON）
    status: str = "active"                 # 状态：active / completed / abandoned
    created_at: str                        # 创建时间（ISO 8601 字符串）
