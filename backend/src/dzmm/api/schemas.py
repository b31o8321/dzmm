from pydantic import BaseModel


class WorldIn(BaseModel):
    name: str
    content_md: str
    style: str = "realistic"
    rules_mode: str = "light"


class WorldOut(WorldIn):
    id: int


class CharacterIn(BaseModel):
    world_id: int
    name: str
    # Per design: enum "male" | "female"; empty = legacy/unset.
    gender: str = ""
    profile_md: str
    base_stats_json: str = "{}"


class CharacterOut(CharacterIn):
    id: int
    portrait_path: str = ""
    xp: int = 0
    level: int = 1


class ModelConfigIn(BaseModel):
    name: str
    type: str
    base_url: str
    model_name: str
    api_key: str | None = None
    timeout: float = 60.0
    max_concurrent: int = 0  # 0 = 不限制；>0 = 进程内并发上限（智谱 free 设 1）


class ModelConfigOut(BaseModel):
    id: int
    name: str
    type: str
    base_url: str
    model_name: str
    api_key_ref: str | None
    timeout: float
    max_concurrent: int = 0
    is_default: bool = False


class SessionIn(BaseModel):
    name: str
    screenplay_id: int | None = None   # new: standalone screenplay → auto-create character
    world_id: int | None = None         # legacy / direct
    character_id: int | None = None     # legacy / direct
    gm_model_config_id: int
    summarizer_model_config_id: int


class SessionOut(BaseModel):
    id: int
    name: str
    screenplay_id: int | None = None
    world_id: int
    character_id: int
    gm_model_config_id: int
    summarizer_model_config_id: int
    turn_count: int


class TurnRequest(BaseModel):
    action: str


class MessageOut(BaseModel):
    id: int
    role: str
    content: str
    turn: int
    tokens_in: int
    tokens_out: int
    events: list[dict] = []


class HiddenEventOut(BaseModel):
    id: int
    subject: str
    kind: str
    severity: int
    description: str
    consequence: str
    introduced_turn: int
    status: str


class NpcOut(BaseModel):
    """Shape returned by GET /sessions/{id}/npcs.
    All fields are returned verbatim; `revealed` is the per-field mask the
    frontend uses to render unrevealed fields as '???' / blanks. v0.11."""
    id: int
    name: str
    gender: str = ""
    description: str = ""
    favor: int = 0
    state: str = ""
    last_seen_turn: int = 0
    purpose: str = ""
    archetype: str = ""
    affinity: dict = {}
    emotion: dict = {}
    pinned: bool = False
    notes: list = []
    revealed: dict[str, bool] = {"name": True}
    tts_voice: str = ""


class ScreenplayStandaloneIn(BaseModel):
    title: str
    genre: str = ""
    pc_name: str = ""
    pc_gender: str = ""
    pc_profile_md: str = ""
    pc_base_stats_json: str = "{}"
    custom_prompt: str = ""
    outline_md: str = ""
    chapters_json: str = "[]"
    main_characters_json: str = "[]"
    ending_md: str = ""
    opening_hook: str = ""
    pc_tts_voice: str = ""


class ScreenplayStandaloneOut(ScreenplayStandaloneIn):
    id: int
    world_id: int
    session_id: int | None = None
    version: int = 1
    current_chapter: int = 1
    completed_events_json: str = "[]"
    status: str = "active"
    created_at: str
