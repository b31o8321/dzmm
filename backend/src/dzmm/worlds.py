from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from jsonschema import ValidationError
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .contracts import contract_validator
from .narrative import NarrativeRuleError, available_choices, initial_state, validate_definition
from .persistence import (
    compose_requests,
    heroes,
    model_profiles,
    run_create_requests,
    runs,
    story_beats,
    turns,
    world_versions,
    worlds,
)
from .run_presentation import build_run_presentation
from .story_beats import build_opening_story_beat


class HeroInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    profile: dict[str, Any] = Field(default_factory=dict)
    combat: dict[str, Any] | None = None


class ComposeWorldInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(min_length=1, max_length=80)
    world_definition: dict[str, Any]
    hero: HeroInput
    model_profile_id: str | None = None


class ComposeWorldResult(BaseModel):
    world_id: str
    world_version_id: str
    hero_id: str
    run_id: str
    model_profile_id: str | None
    state: dict[str, Any]
    created: bool


class CreateRunInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(min_length=1, max_length=80)
    world_version_id: str | None = Field(default=None, max_length=36)
    hero: HeroInput
    model_profile_id: str | None = None


class CreateRunResult(BaseModel):
    world_id: str
    world_version_id: str
    hero_id: str
    run_id: str
    model_profile_id: str | None
    state: dict[str, Any]
    opening: dict[str, Any]
    created: bool


class RunSnapshot(BaseModel):
    run_id: str
    world_id: str
    status: str
    world_version_id: str
    hero_id: str
    state: dict[str, Any]
    presentation: dict[str, Any]
    available_choices: list[dict[str, str]]
    story_beats: list[dict[str, Any]]
    turns: list[dict[str, Any]]


class RunModelProfileInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=0)
    model_profile_id: str = Field(min_length=1, max_length=36)


class DomainValidationError(ValueError):
    pass


class IdempotencyConflictError(ValueError):
    pass


class RunModelProfileConflictError(ValueError):
    pass


class WorldComposer:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def compose(self, payload: ComposeWorldInput) -> ComposeWorldResult:
        self._validate_definition(payload.world_definition)
        fingerprint = _fingerprint(payload)

        async with self._session_factory() as session, session.begin():
            existing = await session.execute(
                select(compose_requests).where(compose_requests.c.request_id == payload.request_id)
            )
            row = existing.mappings().one_or_none()
            if row:
                if row["fingerprint"] != fingerprint:
                    raise IdempotencyConflictError(
                        "request_id was already used for different world input"
                    )
                return await self._result_for_existing(session, row["world_id"], row["run_id"])

            if payload.model_profile_id:
                profile = await session.execute(
                    select(model_profiles.c.id).where(
                        model_profiles.c.id == payload.model_profile_id
                    )
                )
                if profile.scalar_one_or_none() is None:
                    raise DomainValidationError("model_profile_id does not exist")

            now = datetime.now(UTC).replace(tzinfo=None)
            world_id, world_version_id = (str(uuid4()) for _ in range(2))

            await session.execute(
                insert(worlds).values(
                    id=world_id,
                    name=payload.world_definition["name"],
                    status="active",
                    created_at=now,
                )
            )
            await session.execute(
                insert(world_versions).values(
                    id=world_version_id,
                    world_id=world_id,
                    version_number=1,
                    definition=payload.world_definition,
                    created_at=now,
                )
            )
            hero_id, run_id, state, _opening = await self._insert_run(
                session,
                world_version_id=world_version_id,
                definition=payload.world_definition,
                hero=payload.hero,
                model_profile_id=payload.model_profile_id,
                now=now,
            )
            await session.execute(
                insert(compose_requests).values(
                    request_id=payload.request_id,
                    fingerprint=fingerprint,
                    world_id=world_id,
                    run_id=run_id,
                    created_at=now,
                )
            )
            return ComposeWorldResult(
                world_id=world_id,
                world_version_id=world_version_id,
                hero_id=hero_id,
                run_id=run_id,
                model_profile_id=payload.model_profile_id,
                state=state,
                created=True,
            )

    async def create_run(self, world_id: str, payload: CreateRunInput) -> CreateRunResult:
        fingerprint = _run_fingerprint(world_id, payload)
        async with self._session_factory() as session, session.begin():
            existing = await session.execute(
                select(run_create_requests).where(
                    run_create_requests.c.request_id == payload.request_id
                )
            )
            request = existing.mappings().one_or_none()
            if request:
                if request["fingerprint"] != fingerprint:
                    raise IdempotencyConflictError(
                        "request_id was already used for different run input"
                    )
                return await self._create_run_result(
                    session, request["world_id"], request["run_id"], created=False
                )

            version_query = (
                select(
                    worlds.c.status,
                    world_versions.c.id,
                    world_versions.c.definition,
                )
                .join(world_versions, world_versions.c.world_id == worlds.c.id)
                .where(worlds.c.id == world_id)
            )
            if payload.world_version_id:
                version_query = version_query.where(world_versions.c.id == payload.world_version_id)
            version = (
                (
                    await session.execute(
                        version_query.order_by(world_versions.c.version_number.desc()).limit(1)
                    )
                )
                .mappings()
                .one_or_none()
            )
            if version is None:
                raise DomainValidationError("world or world version does not exist")
            if version["status"] != "active":
                raise DomainValidationError("archived world cannot start a new run")
            await self._validate_model_profile(session, payload.model_profile_id)

            now = datetime.now(UTC).replace(tzinfo=None)
            hero_id, run_id, state, opening = await self._insert_run(
                session,
                world_version_id=version["id"],
                definition=version["definition"],
                hero=payload.hero,
                model_profile_id=payload.model_profile_id,
                now=now,
            )
            await session.execute(
                insert(run_create_requests).values(
                    request_id=payload.request_id,
                    fingerprint=fingerprint,
                    world_id=world_id,
                    run_id=run_id,
                    created_at=now,
                )
            )
            return CreateRunResult(
                world_id=world_id,
                world_version_id=version["id"],
                hero_id=hero_id,
                run_id=run_id,
                model_profile_id=payload.model_profile_id,
                state=state,
                opening=opening,
                created=True,
            )

    async def _validate_model_profile(
        self, session: AsyncSession, model_profile_id: str | None
    ) -> None:
        if not model_profile_id:
            return
        profile = await session.execute(
            select(model_profiles.c.id).where(model_profiles.c.id == model_profile_id)
        )
        if profile.scalar_one_or_none() is None:
            raise DomainValidationError("model_profile_id does not exist")

    async def _insert_run(
        self,
        session: AsyncSession,
        *,
        world_version_id: str,
        definition: dict[str, Any],
        hero: HeroInput,
        model_profile_id: str | None,
        now: datetime,
    ) -> tuple[str, str, dict[str, Any], dict[str, Any]]:
        hero_id, run_id = (str(uuid4()) for _ in range(2))
        state = _initial_state(definition, hero_id, hero)
        try:
            contract_validator("run_state.schema.json").validate(state)
        except ValidationError as error:
            raise DomainValidationError(f"invalid initial RunState: {error.message}") from error
        opening = build_opening_story_beat(
            definition, {"id": hero_id, "name": hero.name, "profile": hero.profile}
        )
        await session.execute(
            insert(heroes).values(
                id=hero_id,
                name=hero.name,
                profile=hero.profile,
                created_at=now,
            )
        )
        await session.execute(
            insert(runs).values(
                id=run_id,
                world_version_id=world_version_id,
                hero_id=hero_id,
                model_profile_id=model_profile_id,
                status="active",
                state=state,
                state_revision=0,
                created_at=now,
                updated_at=now,
            )
        )
        await session.execute(
            insert(story_beats).values(
                id=str(uuid4()),
                run_id=run_id,
                kind="opening",
                sequence=0,
                content=opening,
                created_at=now,
            )
        )
        return hero_id, run_id, state, opening

    def _validate_definition(self, definition: dict[str, Any]) -> None:
        validate_world_definition(definition)

    async def _result_for_existing(
        self, session: AsyncSession, world_id: str, run_id: str
    ) -> ComposeWorldResult:
        result = await session.execute(
            select(
                runs.c.world_version_id, runs.c.hero_id, runs.c.model_profile_id, runs.c.state
            ).where(runs.c.id == run_id)
        )
        row = result.mappings().one()
        return ComposeWorldResult(
            world_id=world_id,
            world_version_id=row["world_version_id"],
            hero_id=row["hero_id"],
            run_id=run_id,
            model_profile_id=row["model_profile_id"],
            state=row["state"],
            created=False,
        )

    async def load_run(self, run_id: str) -> RunSnapshot | None:
        async with self._session_factory() as session:
            result = await session.execute(
                select(
                    runs.c.id,
                    runs.c.world_version_id,
                    runs.c.hero_id,
                    runs.c.state,
                    runs.c.status,
                    world_versions.c.world_id,
                    world_versions.c.definition,
                )
                .join(world_versions, world_versions.c.id == runs.c.world_version_id)
                .where(runs.c.id == run_id)
            )
            run = result.mappings().one_or_none()
            if run is None:
                return None
            turn_rows = await session.execute(
                select(
                    turns.c.id,
                    turns.c.kind,
                    turns.c.rollback_target_id,
                    turns.c.sequence,
                    turns.c.player_input,
                    turns.c.narrative,
                    turns.c.commands,
                    turns.c.outcomes,
                    turns.c.before_revision,
                    turns.c.after_revision,
                )
                .where(turns.c.run_id == run_id)
                .order_by(turns.c.sequence)
            )
            beat_rows = await session.execute(
                select(
                    story_beats.c.id,
                    story_beats.c.kind,
                    story_beats.c.sequence,
                    story_beats.c.content,
                )
                .where(story_beats.c.run_id == run_id)
                .order_by(story_beats.c.sequence)
            )
            return RunSnapshot(
                run_id=run["id"],
                world_id=run["world_id"],
                status=run["status"],
                world_version_id=run["world_version_id"],
                hero_id=run["hero_id"],
                state=run["state"],
                presentation=build_run_presentation(run["definition"]),
                available_choices=available_choices(run["state"], run["definition"]),
                story_beats=[
                    {"id": row["id"], "sequence": row["sequence"], **row["content"]}
                    for row in beat_rows.mappings()
                ],
                turns=[dict(row) for row in turn_rows.mappings()],
            )

    async def _create_run_result(
        self, session: AsyncSession, world_id: str, run_id: str, *, created: bool
    ) -> CreateRunResult:
        result = await session.execute(
            select(
                runs.c.world_version_id,
                runs.c.hero_id,
                runs.c.model_profile_id,
                runs.c.state,
                story_beats.c.content,
            )
            .join(story_beats, story_beats.c.run_id == runs.c.id)
            .where(runs.c.id == run_id, story_beats.c.kind == "opening")
        )
        row = result.mappings().one()
        return CreateRunResult(
            world_id=world_id,
            world_version_id=row["world_version_id"],
            hero_id=row["hero_id"],
            run_id=run_id,
            model_profile_id=row["model_profile_id"],
            state=row["state"],
            opening=row["content"],
            created=created,
        )

    async def run_model_profile_id(self, run_id: str) -> str | None:
        async with self._session_factory() as session:
            result = await session.execute(
                select(runs.c.model_profile_id).where(
                    runs.c.id == run_id, runs.c.status == "active"
                )
            )
            row = result.mappings().one_or_none()
        if row is None:
            raise RunModelProfileConflictError("active run not found")
        return row["model_profile_id"]

    async def set_run_model_profile(self, run_id: str, payload: RunModelProfileInput) -> str:
        async with self._session_factory() as session, session.begin():
            run = await session.execute(
                select(runs.c.state_revision).where(runs.c.id == run_id, runs.c.status == "active")
            )
            revision = run.scalar_one_or_none()
            if revision is None:
                raise RunModelProfileConflictError("active run not found")
            if revision != payload.expected_revision:
                raise RunModelProfileConflictError(
                    "run state changed; reload before selecting a model"
                )
            profile = await session.execute(
                select(model_profiles.c.id).where(model_profiles.c.id == payload.model_profile_id)
            )
            if profile.scalar_one_or_none() is None:
                raise DomainValidationError("model_profile_id does not exist")
            changed = await session.execute(
                update(runs)
                .where(runs.c.id == run_id, runs.c.state_revision == payload.expected_revision)
                .values(
                    model_profile_id=payload.model_profile_id,
                    updated_at=datetime.now(UTC).replace(tzinfo=None),
                )
            )
            if changed.rowcount != 1:
                raise RunModelProfileConflictError(
                    "run state changed; reload before selecting a model"
                )
        return payload.model_profile_id


def _initial_state(definition: dict[str, Any], hero_id: str, hero: HeroInput) -> dict[str, Any]:
    hero_state = {"id": hero_id, "name": hero.name, "profile": hero.profile}
    if hero.combat is not None:
        hero_state["combat"] = hero.combat
    return initial_state(definition, hero_state)


def _fingerprint(payload: ComposeWorldInput) -> str:
    canonical = json.dumps(payload.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _run_fingerprint(world_id: str, payload: CreateRunInput) -> str:
    canonical = json.dumps(
        {"world_id": world_id, **payload.model_dump(mode="json")},
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def validate_world_definition(definition: dict[str, Any]) -> None:
    try:
        contract_validator("world_definition.schema.json").validate(definition)
    except ValidationError as error:
        raise DomainValidationError(f"invalid WorldDefinition: {error.message}") from error
    try:
        validate_definition(definition)
    except NarrativeRuleError as error:
        raise DomainValidationError(f"invalid narrative ruleset: {error}") from error
    if len(definition["locations"]) < 2:
        raise DomainValidationError("a playable vNext world needs at least two locations")
