from __future__ import annotations

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    UniqueConstraint,
)

metadata = MetaData()

worlds = Table(
    "worlds",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("name", String(120), nullable=False),
    Column("status", String(20), nullable=False),
    Column("created_at", DateTime(), nullable=False),
)

world_versions = Table(
    "world_versions",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("world_id", String(36), ForeignKey("worlds.id", ondelete="CASCADE"), nullable=False),
    Column("version_number", Integer(), nullable=False),
    Column("definition", JSON(), nullable=False),
    Column("created_at", DateTime(), nullable=False),
    UniqueConstraint("world_id", "version_number", name="uq_world_versions_number"),
)

heroes = Table(
    "heroes",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("name", String(120), nullable=False),
    Column("profile", JSON(), nullable=False),
    Column("created_at", DateTime(), nullable=False),
)

runs = Table(
    "runs",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("world_version_id", String(36), ForeignKey("world_versions.id", ondelete="RESTRICT"), nullable=False),
    Column("hero_id", String(36), ForeignKey("heroes.id", ondelete="RESTRICT"), nullable=False),
    Column("model_profile_id", String(36), nullable=True),
    Column("status", String(20), nullable=False),
    Column("state", JSON(), nullable=False),
    Column("state_revision", Integer(), nullable=False),
    Column("created_at", DateTime(), nullable=False),
    Column("updated_at", DateTime(), nullable=False),
)

turns = Table(
    "turns",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("run_id", String(36), ForeignKey("runs.id", ondelete="CASCADE"), nullable=False),
    Column("request_id", String(80), nullable=False),
    Column("sequence", Integer(), nullable=False),
    Column("player_input", String(), nullable=False),
    Column("narrative", String(), nullable=False),
    Column("commands", JSON(), nullable=False),
    Column("outcomes", JSON(), nullable=False),
    Column("before_revision", Integer(), nullable=False),
    Column("after_revision", Integer(), nullable=False),
    Column("after_state", JSON(), nullable=False),
    Column("created_at", DateTime(), nullable=False),
    UniqueConstraint("run_id", "request_id", name="uq_turns_run_request"),
    UniqueConstraint("run_id", "sequence", name="uq_turns_run_sequence"),
)

compose_requests = Table(
    "compose_requests",
    metadata,
    Column("request_id", String(80), primary_key=True),
    Column("fingerprint", String(64), nullable=False),
    Column("world_id", String(36), ForeignKey("worlds.id", ondelete="CASCADE"), nullable=False),
    Column("run_id", String(36), ForeignKey("runs.id", ondelete="CASCADE"), nullable=False),
    Column("created_at", DateTime(), nullable=False),
)

model_profiles = Table(
    "model_profiles",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("name", String(120), nullable=False, unique=True),
    Column("provider_type", String(30), nullable=False),
    Column("base_url", String(500), nullable=False),
    Column("model_name", String(200), nullable=False),
    Column("created_at", DateTime(), nullable=False),
)
