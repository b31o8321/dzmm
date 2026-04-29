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
    profile_md: str
    base_stats_json: str = "{}"


class CharacterOut(CharacterIn):
    id: int
    portrait_path: str = ""


class ModelConfigIn(BaseModel):
    name: str
    type: str
    base_url: str
    model_name: str
    api_key: str | None = None
    timeout: float = 60.0


class ModelConfigOut(BaseModel):
    id: int
    name: str
    type: str
    base_url: str
    model_name: str
    api_key_ref: str | None
    timeout: float


class SessionIn(BaseModel):
    name: str
    world_id: int
    character_id: int
    gm_model_config_id: int
    summarizer_model_config_id: int


class SessionOut(SessionIn):
    id: int
    turn_count: int


class TurnRequest(BaseModel):
    action: str
