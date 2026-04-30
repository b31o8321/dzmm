from datetime import datetime, UTC
from sqlalchemy import ForeignKey, String, Text, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship

from dzmm.db.base import Base


class World(Base):
    __tablename__ = "worlds"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    content_md: Mapped[str] = mapped_column(Text)
    rules_json: Mapped[str] = mapped_column(Text, default='{"mode":"light"}')
    style: Mapped[str] = mapped_column(String(40), default="realistic")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None))


class Character(Base):
    __tablename__ = "characters"
    id: Mapped[int] = mapped_column(primary_key=True)
    world_id: Mapped[int] = mapped_column(ForeignKey("worlds.id"))
    name: Mapped[str] = mapped_column(String(120))
    profile_md: Mapped[str] = mapped_column(Text)
    base_stats_json: Mapped[str] = mapped_column(Text)
    portrait_path: Mapped[str] = mapped_column(String(255), default="")
    xp: Mapped[int] = mapped_column(default=0)
    level: Mapped[int] = mapped_column(default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None))

    world: Mapped[World] = relationship()


class ModelConfig(Base):
    __tablename__ = "model_configs"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    type: Mapped[str] = mapped_column(String(40))
    base_url: Mapped[str] = mapped_column(String(255))
    model_name: Mapped[str] = mapped_column(String(120))
    api_key_ref: Mapped[str | None] = mapped_column(String(120), nullable=True)
    timeout: Mapped[float] = mapped_column(default=60.0)
    params_json: Mapped[str] = mapped_column(Text, default='{}')


class Session(Base):
    __tablename__ = "sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    world_id: Mapped[int] = mapped_column(ForeignKey("worlds.id"))
    character_id: Mapped[int] = mapped_column(ForeignKey("characters.id"))
    gm_model_config_id: Mapped[int] = mapped_column(ForeignKey("model_configs.id"))
    summarizer_model_config_id: Mapped[int] = mapped_column(ForeignKey("model_configs.id"))
    turn_count: Mapped[int] = mapped_column(default=0)
    schema_version: Mapped[int] = mapped_column(default=1)
    recall_pending_json: Mapped[str] = mapped_column(Text, default="[]")
    pc_mood_json: Mapped[str] = mapped_column(Text, default="{}")  # v0.9
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None))
    last_played: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None))


class Message(Base):
    __tablename__ = "messages"
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"))
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    turn: Mapped[int] = mapped_column(default=0)
    tokens_in: Mapped[int] = mapped_column(default=0)
    tokens_out: Mapped[int] = mapped_column(default=0)
    summarized: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None))


class StorySummary(Base):
    __tablename__ = "story_summaries"
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"), primary_key=True)
    summary_text: Mapped[str] = mapped_column(Text, default="")
    last_summarized_msg_id: Mapped[int] = mapped_column(default=0)
    summary_tokens: Mapped[int] = mapped_column(default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None))


class CharState(Base):
    __tablename__ = "char_states"
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"), primary_key=True)
    stats_json: Mapped[str] = mapped_column(Text, default="{}")
    inventory_json: Mapped[str] = mapped_column(Text, default="[]")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None))


class NPC(Base):
    __tablename__ = "npcs"
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"))
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    favor: Mapped[int] = mapped_column(default=0)
    state: Mapped[str] = mapped_column(String(60), default="未知")
    last_seen_turn: Mapped[int] = mapped_column(default=0)
    notes_json: Mapped[str] = mapped_column(Text, default="[]")
    purpose: Mapped[str] = mapped_column(Text, default="")
    archetype: Mapped[str] = mapped_column(String(120), default="")
    affinity_json: Mapped[str] = mapped_column(Text, default="{}")
    pinned: Mapped[bool] = mapped_column(default=False)
    emotion_json: Mapped[str] = mapped_column(Text, default="{}")  # v0.9


class PlotThread(Base):
    __tablename__ = "plot_threads"
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"))
    type: Mapped[str] = mapped_column(String(40))  # quest | hook | mystery | major_event
    description: Mapped[str] = mapped_column(Text)
    introduced_turn: Mapped[int] = mapped_column(default=0)
    importance: Mapped[int] = mapped_column(default=2)  # 1=minor, 2=normal, 3=major
    status: Mapped[str] = mapped_column(String(20), default="active")  # active|resolved|abandoned
    resolution: Mapped[str] = mapped_column(Text, default="")


class Timeline(Base):
    """Long-term key events extracted during recursive summary compression.
    Not injected into prompts (would defeat the compression); used for
    explicit user retrieval ("when did I first meet X?")."""
    __tablename__ = "timeline"
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"))
    turn: Mapped[int] = mapped_column(default=0)
    event_text: Mapped[str] = mapped_column(Text)
    importance: Mapped[int] = mapped_column(default=2)  # 1-3
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None))


class Era(Base):
    """Story 'chapter' / 'arc' marker. GM emits <era_begin> to signal a
    significant narrative phase shift — used to group Timeline events in the
    Chronicle view."""
    __tablename__ = "eras"
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"))
    name: Mapped[str] = mapped_column(String(120))
    started_turn: Mapped[int] = mapped_column(default=0)
    description: Mapped[str] = mapped_column(Text, default="")


class NpcRelation(Base):
    """关系记录两个 NPC 之间的关系。By name not FK to avoid cascade complexity
    when GM mentions an NPC before formally creating them via <npc_update>."""
    __tablename__ = "npc_relations"
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"))
    npc_a: Mapped[str] = mapped_column(String(120))
    npc_b: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(60))  # 父女/恋人/对手/同事/师徒/盟友/仇敌/秘密/...
    description: Mapped[str] = mapped_column(Text, default="")
    introduced_turn: Mapped[int] = mapped_column(default=0)


class PCGoal(Base):
    """Player-character goals. GM auto-registers via <pc_goal type='add'>;
    closes via <pc_goal type='complete' id='...'/>. Active goals injected
    into key_facts so GM stays aware of what PC is pursuing."""
    __tablename__ = "pc_goals"
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"))
    description: Mapped[str] = mapped_column(Text)
    priority: Mapped[str] = mapped_column(String(20), default="normal")  # high|normal|low
    status: Mapped[str] = mapped_column(String(20), default="active")  # active|completed|abandoned
    introduced_turn: Mapped[int] = mapped_column(default=0)
    completed_turn: Mapped[int | None] = mapped_column(nullable=True)
    completion_note: Mapped[str] = mapped_column(Text, default="")
