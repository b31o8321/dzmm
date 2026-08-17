from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .persistence import (
    compose_requests,
    heroes,
    mobile_devices,
    model_profiles,
    pairing_requests,
    runs,
    turns,
    world_versions,
    worlds,
)
from .worlds import validate_world_definition


class PurgeManifest(BaseModel):
    world_id: str
    world_name: str
    tables: dict[str, int]
    file_paths: list[str]
    derived_indexes: list[str]
    confirmation_token: str


class PurgeConfirmation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmation_token: str = Field(min_length=64, max_length=64)
    world_name: str = Field(min_length=1, max_length=120)


class WorldVersionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_world_version_id: str = Field(min_length=1, max_length=36)
    definition: dict[str, Any]


class WorldSummary(BaseModel):
    id: str
    name: str
    status: str
    latest_world_version_id: str
    latest_version_number: int
    world_version_count: int
    run_count: int
    lorebook_entry_count: int
    character_card_count: int


class WorldDetail(WorldSummary):
    definition: dict[str, Any]


class WorldNotFoundError(ValueError):
    pass


class PurgeConfirmationError(ValueError):
    pass


class WorldVersionConflictError(ValueError):
    pass


class WorldLifecycle:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def archive(self, world_id: str) -> str:
        async with self._session_factory() as session, session.begin():
            result = await session.execute(select(worlds.c.status).where(worlds.c.id == world_id))
            status = result.scalar_one_or_none()
            if status is None:
                raise WorldNotFoundError("world not found")
            if status == "archived":
                return status
            await session.execute(worlds.update().where(worlds.c.id == world_id).values(status="archived"))
            return "archived"

    async def restore(self, world_id: str) -> str:
        async with self._session_factory() as session, session.begin():
            result = await session.execute(select(worlds.c.status).where(worlds.c.id == world_id))
            status = result.scalar_one_or_none()
            if status is None:
                raise WorldNotFoundError("world not found")
            if status == "active":
                return status
            await session.execute(worlds.update().where(worlds.c.id == world_id).values(status="active"))
            return "active"

    async def list_worlds(self) -> list[WorldSummary]:
        async with self._session_factory() as session:
            world_ids = await session.execute(select(worlds.c.id).order_by(worlds.c.created_at.desc()))
            return [await self._summary(session, world_id) for world_id in world_ids.scalars()]

    async def get_world(self, world_id: str) -> WorldDetail:
        async with self._session_factory() as session:
            summary, definition = await self._summary_and_definition(session, world_id)
            return WorldDetail(**summary.model_dump(), definition=definition)

    async def create_version(
        self, world_id: str, payload: WorldVersionInput
    ) -> WorldDetail:
        validate_world_definition(payload.definition)
        async with self._session_factory() as session, session.begin():
            latest = await self._latest_version(session, world_id)
            if latest is None:
                raise WorldNotFoundError("world not found")
            if latest["status"] != "active":
                raise WorldVersionConflictError("archived world cannot create a new version")
            if latest["id"] != payload.base_world_version_id:
                raise WorldVersionConflictError("world version is stale; reload before saving")
            await session.execute(
                insert(world_versions).values(
                    id=str(uuid4()),
                    world_id=world_id,
                    version_number=latest["version_number"] + 1,
                    definition=payload.definition,
                    created_at=datetime.now(UTC).replace(tzinfo=None),
                )
            )
            await session.execute(
                worlds.update().where(worlds.c.id == world_id).values(name=payload.definition["name"])
            )
            summary, definition = await self._summary_and_definition(session, world_id)
            return WorldDetail(**summary.model_dump(), definition=definition)

    async def manifest(self, world_id: str) -> PurgeManifest:
        async with self._session_factory() as session:
            return await self._manifest(session, world_id)

    async def purge(self, world_id: str, confirmation: PurgeConfirmation) -> PurgeManifest:
        async with self._session_factory() as session, session.begin():
            manifest = await self._manifest(session, world_id)
            if manifest.confirmation_token != confirmation.confirmation_token:
                raise PurgeConfirmationError("purge confirmation token is stale or invalid")
            if manifest.world_name != confirmation.world_name:
                raise PurgeConfirmationError("purge confirmation world name does not match")
            version_ids = select(world_versions.c.id).where(world_versions.c.world_id == world_id)
            hero_result = await session.execute(
                select(runs.c.hero_id).where(runs.c.world_version_id.in_(version_ids))
            )
            hero_ids = list(hero_result.scalars())
            await session.execute(delete(runs).where(runs.c.world_version_id.in_(version_ids)))
            if hero_ids:
                await session.execute(delete(heroes).where(heroes.c.id.in_(hero_ids)))
            await session.execute(delete(worlds).where(worlds.c.id == world_id))
            return manifest

    async def _manifest(self, session: AsyncSession, world_id: str) -> PurgeManifest:
        world = await session.execute(select(worlds.c.name).where(worlds.c.id == world_id))
        world_name = world.scalar_one_or_none()
        if world_name is None:
            raise WorldNotFoundError("world not found")
        version_ids = select(world_versions.c.id).where(world_versions.c.world_id == world_id)
        run_ids = select(runs.c.id).where(runs.c.world_version_id.in_(version_ids))
        counts = {
            "worlds": 1,
            "world_versions": await _count(session, world_versions.c.id, world_versions.c.world_id == world_id),
            "runs": await _count(session, runs.c.id, runs.c.world_version_id.in_(version_ids)),
            "turns": await _count(session, turns.c.id, turns.c.run_id.in_(run_ids)),
            "heroes": await _count(session, runs.c.hero_id, runs.c.world_version_id.in_(version_ids)),
            "compose_requests": await _count(
                session,
                compose_requests.c.request_id,
                compose_requests.c.world_id == world_id,
            ),
        }
        token = hashlib.sha256(
            json.dumps(
                {"world_id": world_id, "world_name": world_name, "tables": counts},
                sort_keys=True,
            ).encode()
        ).hexdigest()
        return PurgeManifest(
            world_id=world_id,
            world_name=world_name,
            tables=counts,
            file_paths=[],
            derived_indexes=[],
            confirmation_token=token,
        )

    async def _summary_and_definition(
        self, session: AsyncSession, world_id: str
    ) -> tuple[WorldSummary, dict[str, Any]]:
        summary = await self._summary(session, world_id)
        latest = await self._latest_version(session, world_id)
        assert latest is not None
        return summary, latest["definition"]

    async def _summary(self, session: AsyncSession, world_id: str) -> WorldSummary:
        latest = await self._latest_version(session, world_id)
        if latest is None:
            raise WorldNotFoundError("world not found")
        version_count = await _count(
            session, world_versions.c.id, world_versions.c.world_id == world_id
        )
        version_ids = select(world_versions.c.id).where(world_versions.c.world_id == world_id)
        run_count = await _count(session, runs.c.id, runs.c.world_version_id.in_(version_ids))
        definition = latest["definition"]
        return WorldSummary(
            id=world_id,
            name=latest["name"],
            status=latest["status"],
            latest_world_version_id=latest["id"],
            latest_version_number=latest["version_number"],
            world_version_count=version_count,
            run_count=run_count,
            lorebook_entry_count=len(definition["lorebook"]["entries"]),
            character_card_count=len(definition["character_cards"]),
        )

    async def _latest_version(self, session: AsyncSession, world_id: str):
        result = await session.execute(
            select(
                worlds.c.name,
                worlds.c.status,
                world_versions.c.id,
                world_versions.c.version_number,
                world_versions.c.definition,
            )
            .join(world_versions, world_versions.c.world_id == worlds.c.id)
            .where(worlds.c.id == world_id)
            .order_by(world_versions.c.version_number.desc())
            .limit(1)
        )
        return result.mappings().one_or_none()


async def integrity_scan(session_factory: async_sessionmaker[AsyncSession]) -> dict[str, int]:
    async with session_factory() as session:
        checks = {
            "world_versions_without_world": select(func.count())
            .select_from(world_versions.outerjoin(worlds))
            .where(worlds.c.id.is_(None)),
            "runs_without_world_version": select(func.count())
            .select_from(runs.outerjoin(world_versions))
            .where(world_versions.c.id.is_(None)),
            "runs_without_hero": select(func.count())
            .select_from(runs.outerjoin(heroes))
            .where(heroes.c.id.is_(None)),
            "turns_without_run": select(func.count())
            .select_from(turns.outerjoin(runs))
            .where(runs.c.id.is_(None)),
            "compose_requests_without_world": select(func.count())
            .select_from(compose_requests.outerjoin(worlds))
            .where(worlds.c.id.is_(None)),
            "compose_requests_without_run": select(func.count())
            .select_from(compose_requests.outerjoin(runs))
            .where(runs.c.id.is_(None)),
        }
        return {name: (await session.execute(statement)).scalar_one() for name, statement in checks.items()}


async def diagnostic_snapshot(session_factory: async_sessionmaker[AsyncSession]) -> dict[str, object]:
    """Return aggregate-only support data without exposing player content or configuration."""
    async with session_factory() as session:
        counts = {
            "worlds": await _table_count(session, worlds),
            "world_versions": await _table_count(session, world_versions),
            "heroes": await _table_count(session, heroes),
            "runs": await _table_count(session, runs),
            "turns": await _table_count(session, turns),
            "model_profiles": await _table_count(session, model_profiles),
            "mobile_devices": await _table_count(session, mobile_devices),
            "pairing_requests": await _table_count(session, pairing_requests),
        }
    orphans = await integrity_scan(session_factory)
    return {"aggregate_counts": counts, "integrity": {"clean": not any(orphans.values()), "orphans": orphans}}


async def _count(session: AsyncSession, column: Any, where: Any) -> int:
    return (await session.execute(select(func.count(column)).where(where))).scalar_one()


async def _table_count(session: AsyncSession, table: Any) -> int:
    return (await session.execute(select(func.count()).select_from(table))).scalar_one()
