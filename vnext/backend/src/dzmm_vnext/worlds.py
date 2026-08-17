from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from jsonschema import ValidationError
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .contracts import contract_validator
from .narrative import NarrativeRuleError, available_choices, initial_state, validate_definition
from .persistence import (
    compose_requests,
    heroes,
    model_profiles,
    runs,
    turns,
    world_versions,
    worlds,
)


class HeroInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    profile: dict[str, Any] = Field(default_factory=dict)


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


class RunSnapshot(BaseModel):
    run_id: str
    world_version_id: str
    hero_id: str
    state: dict[str, Any]
    presentation: dict[str, Any]
    available_choices: list[dict[str, str]]
    turns: list[dict[str, Any]]


class DomainValidationError(ValueError):
    pass


class IdempotencyConflictError(ValueError):
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
                    raise IdempotencyConflictError("request_id was already used for different world input")
                return await self._result_for_existing(session, row["world_id"], row["run_id"])

            if payload.model_profile_id:
                profile = await session.execute(
                    select(model_profiles.c.id).where(model_profiles.c.id == payload.model_profile_id)
                )
                if profile.scalar_one_or_none() is None:
                    raise DomainValidationError("model_profile_id does not exist")

            now = datetime.now(UTC).replace(tzinfo=None)
            world_id, world_version_id, hero_id, run_id = (str(uuid4()) for _ in range(4))
            state = _initial_state(payload.world_definition, hero_id, payload.hero)
            try:
                contract_validator("run_state.schema.json").validate(state)
            except ValidationError as error:
                raise DomainValidationError(f"invalid initial RunState: {error.message}") from error

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
            await session.execute(
                insert(heroes).values(
                    id=hero_id,
                    name=payload.hero.name,
                    profile=payload.hero.profile,
                    created_at=now,
                )
            )
            await session.execute(
                insert(runs).values(
                    id=run_id,
                    world_version_id=world_version_id,
                    hero_id=hero_id,
                    model_profile_id=payload.model_profile_id,
                    status="active",
                    state=state,
                    state_revision=0,
                    created_at=now,
                    updated_at=now,
                )
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

    def _validate_definition(self, definition: dict[str, Any]) -> None:
        validate_world_definition(definition)

    async def _result_for_existing(
        self, session: AsyncSession, world_id: str, run_id: str
    ) -> ComposeWorldResult:
        result = await session.execute(
            select(runs.c.world_version_id, runs.c.hero_id, runs.c.model_profile_id, runs.c.state).where(
                runs.c.id == run_id
            )
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
            return RunSnapshot(
                run_id=run["id"],
                world_version_id=run["world_version_id"],
                hero_id=run["hero_id"],
                state=run["state"],
                presentation=_run_presentation(run["definition"]),
                available_choices=available_choices(run["state"], run["definition"]),
                turns=[dict(row) for row in turn_rows.mappings()],
            )


def _run_presentation(definition: dict[str, Any]) -> dict[str, Any]:
    cards = {item["id"]: item["name"] for item in definition["character_cards"]}
    relationship_names = {
        relationship["id"]: cards[relationship["character_card_id"]]
        for relationship in definition["story"]["relationships"]
    }
    return {
        "world_name": definition["name"],
        "locations": {item["id"]: item["name"] for item in definition["locations"]},
        "relationships": relationship_names,
        "chapters": {item["id"]: item["title"] for item in definition["story"]["chapters"]},
        "routes": {item["id"]: item["name"] for item in definition["story"]["routes"]},
    }


def _initial_state(
    definition: dict[str, Any], hero_id: str, hero: HeroInput
) -> dict[str, Any]:
    return initial_state(
        definition,
        {"id": hero_id, "name": hero.name, "profile": hero.profile},
    )


def _fingerprint(payload: ComposeWorldInput) -> str:
    canonical = json.dumps(payload.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
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
