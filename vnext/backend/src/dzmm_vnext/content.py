from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from jsonschema import ValidationError
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .contracts import contract_validator
from .lore import LoreSelection, select_lore
from .persistence import world_versions, worlds
from .sillytavern import ImportedContent, import_sillytavern


class SillyTavernImportInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: dict[str, Any]


class LoreSelectionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    player_input: str = Field(min_length=1, max_length=4000)
    character_budget: int = Field(default=4000, ge=1, le=20000)


class LoreSelectionResult(BaseModel):
    entries: list[dict[str, Any]]
    included_ids: list[str]
    excluded_ids: list[str]
    used_characters: int


class LorePromotionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entity_kind: Literal["locations", "factions", "npcs", "events"]
    entity: dict[str, Any]


class WorldVersionResult(BaseModel):
    id: str
    world_id: str
    version_number: int
    definition: dict[str, Any]


class ContentNotFoundError(ValueError):
    pass


class ContentService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    def import_sillytavern(self, payload: SillyTavernImportInput) -> ImportedContent:
        return import_sillytavern(payload.content)

    async def select_lore(
        self, world_version_id: str, payload: LoreSelectionInput
    ) -> LoreSelectionResult:
        async with self._session_factory() as session:
            result = await session.execute(
                select(world_versions.c.definition).where(world_versions.c.id == world_version_id)
            )
            definition = result.scalar_one_or_none()
        if definition is None:
            raise ContentNotFoundError("world version not found")
        return _selection_result(select_lore(definition, payload.player_input, payload.character_budget))

    async def promote_lore(
        self, world_id: str, lore_id: str, payload: LorePromotionInput
    ) -> WorldVersionResult:
        async with self._session_factory() as session, session.begin():
            latest_result = await session.execute(
                select(
                    worlds.c.status,
                    world_versions.c.version_number,
                    world_versions.c.definition,
                )
                .join(world_versions, world_versions.c.world_id == worlds.c.id)
                .where(worlds.c.id == world_id)
                .order_by(world_versions.c.version_number.desc())
                .limit(1)
            )
            latest = latest_result.mappings().one_or_none()
            if latest is None:
                raise ContentNotFoundError("world not found")
            if latest["status"] != "active":
                raise ContentNotFoundError("archived world cannot create a new version")
            definition = deepcopy(latest["definition"])
            if not any(entry["id"] == lore_id for entry in definition["lore"]):
                raise ContentNotFoundError("lore entry not found")
            entity_id = payload.entity.get("id")
            if not isinstance(entity_id, str) or not entity_id:
                raise ValueError("promoted entity requires an id")
            if any(entity["id"] == entity_id for entity in definition[payload.entity_kind]):
                raise ValueError("promoted entity id already exists")
            definition[payload.entity_kind].append(payload.entity)
            try:
                contract_validator("world_definition.schema.json").validate(definition)
            except ValidationError as error:
                raise ValueError(f"promoted entity makes WorldDefinition invalid: {error.message}") from error

            version_number = latest["version_number"] + 1
            version_id = str(uuid4())
            await session.execute(
                insert(world_versions).values(
                    id=version_id,
                    world_id=world_id,
                    version_number=version_number,
                    definition=definition,
                    created_at=datetime.now(UTC).replace(tzinfo=None),
                )
            )
            return WorldVersionResult(
                id=version_id,
                world_id=world_id,
                version_number=version_number,
                definition=definition,
            )


def _selection_result(selection: LoreSelection) -> LoreSelectionResult:
    return LoreSelectionResult(
        entries=selection.entries,
        included_ids=selection.included_ids,
        excluded_ids=selection.excluded_ids,
        used_characters=selection.used_characters,
    )
