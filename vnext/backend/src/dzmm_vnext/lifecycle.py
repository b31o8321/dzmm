from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .persistence import compose_requests, heroes, runs, turns, world_versions, worlds


class PurgeManifest(BaseModel):
    world_id: str
    tables: dict[str, int]
    file_paths: list[str]
    derived_indexes: list[str]
    confirmation_token: str


class PurgeConfirmation(BaseModel):
    confirmation_token: str = Field(min_length=64, max_length=64)


class WorldNotFoundError(ValueError):
    pass


class PurgeConfirmationError(ValueError):
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

    async def manifest(self, world_id: str) -> PurgeManifest:
        async with self._session_factory() as session:
            return await self._manifest(session, world_id)

    async def purge(self, world_id: str, confirmation_token: str) -> PurgeManifest:
        async with self._session_factory() as session, session.begin():
            manifest = await self._manifest(session, world_id)
            if manifest.confirmation_token != confirmation_token:
                raise PurgeConfirmationError("purge confirmation token is stale or invalid")
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
        exists = await session.execute(select(worlds.c.id).where(worlds.c.id == world_id))
        if exists.scalar_one_or_none() is None:
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
            json.dumps({"world_id": world_id, "tables": counts}, sort_keys=True).encode()
        ).hexdigest()
        return PurgeManifest(
            world_id=world_id,
            tables=counts,
            file_paths=[],
            derived_indexes=[],
            confirmation_token=token,
        )


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


async def _count(session: AsyncSession, column: Any, where: Any) -> int:
    return (await session.execute(select(func.count(column)).where(where))).scalar_one()
