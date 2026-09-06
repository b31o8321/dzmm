from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from jsonschema import ValidationError
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .contracts import contract_validator
from .lore import LorebookSelection, select_lorebook
from .persistence import world_versions, worlds
from .sillytavern import ImportedContent, import_sillytavern, import_sillytavern_png


class SillyTavernImportInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: dict[str, Any] | None = None
    png_base64: str | None = Field(default=None, min_length=1, max_length=24 * 1024 * 1024)

    @model_validator(mode="after")
    def require_exactly_one_source(self) -> SillyTavernImportInput:
        if (self.content is None) == (self.png_base64 is None):
            raise ValueError("provide exactly one of content or png_base64")
        return self


class LorebookSelectionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    player_input: str = Field(min_length=1, max_length=4000)
    character_budget: int = Field(default=4000, ge=1, le=20000)


class LorebookSelectionResult(BaseModel):
    entries: list[dict[str, Any]]
    included_ids: list[str]
    excluded_ids: list[str]
    used_characters: int


class LorebookPromotionInput(BaseModel):
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
        if payload.content is not None:
            return import_sillytavern(payload.content)
        assert payload.png_base64 is not None
        return import_sillytavern_png(payload.png_base64)

    async def select_lorebook(
        self, world_version_id: str, payload: LorebookSelectionInput
    ) -> LorebookSelectionResult:
        async with self._session_factory() as session:
            result = await session.execute(
                select(world_versions.c.definition).where(world_versions.c.id == world_version_id)
            )
            definition = result.scalar_one_or_none()
        if definition is None:
            raise ContentNotFoundError("world version not found")
        return _selection_result(select_lorebook(definition, payload.player_input, payload.character_budget))

    async def promote_lorebook_entry(
        self, world_id: str, entry_id: str, payload: LorebookPromotionInput
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
            if not any(entry["id"] == entry_id for entry in definition["lorebook"]["entries"]):
                raise ContentNotFoundError("lorebook entry not found")
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

    async def export_character_card(
        self, world_version_id: str, character_card_id: str
    ) -> dict[str, Any]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(world_versions.c.definition).where(world_versions.c.id == world_version_id)
            )
            definition = result.scalar_one_or_none()
        if definition is None:
            raise ContentNotFoundError("world version not found")
        card = next(
            (item for item in definition["character_cards"] if item["id"] == character_card_id),
            None,
        )
        if card is None:
            raise ContentNotFoundError("character card not found")
        payload = card.get("source_payload")
        if isinstance(payload, dict):
            return deepcopy(payload)
        if card.get("format") == "native":
            return _native_character_card_to_v3(card)
        raise TypeError("character card has no source payload to export")

    async def export_lorebook(self, world_version_id: str) -> dict[str, Any]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(world_versions.c.definition).where(world_versions.c.id == world_version_id)
            )
            definition = result.scalar_one_or_none()
        if definition is None:
            raise ContentNotFoundError("world version not found")
        return {
            "entries": {
                str(index): _world_info_entry(entry)
                for index, entry in enumerate(definition["lorebook"]["entries"])
            }
        }


def _selection_result(selection: LorebookSelection) -> LorebookSelectionResult:
    return LorebookSelectionResult(
        entries=selection.entries,
        included_ids=selection.included_ids,
        excluded_ids=selection.excluded_ids,
        used_characters=selection.used_characters,
    )


def _world_info_entry(entry: dict[str, Any]) -> dict[str, Any]:
    source = entry.get("source")
    if isinstance(source, dict) and isinstance(source.get("sillytavern"), dict):
        return deepcopy(source["sillytavern"])
    return {
        "id": entry["id"],
        "comment": entry["title"],
        "content": entry["body"],
        "keys": entry.get("keywords", []),
        "constant": entry["activation"] == "always",
        "insertion_order": entry["priority"],
    }


def _native_character_card_to_v3(card: dict[str, Any]) -> dict[str, Any]:
    mapped = card.get("mapped") if isinstance(card.get("mapped"), dict) else {}
    name = card.get("name")
    if not isinstance(name, str) or not name:
        raise TypeError("native character card has no name")
    data: dict[str, Any] = {
        "name": name,
        "description": _mapped_text(mapped, "description"),
        "personality": _mapped_text(mapped, "personality"),
        "scenario": _mapped_text(mapped, "scenario"),
        "first_mes": _mapped_text(mapped, "first_mes"),
        "mes_example": _mapped_text(mapped, "mes_example"),
        "character_book": {"entries": []},
    }
    for key in (
        "creator_notes",
        "creator",
        "character_version",
        "system_prompt",
        "post_history_instructions",
    ):
        if _mapped_text(mapped, key):
            data[key] = mapped[key]
    if isinstance(mapped.get("alternate_greetings"), list) and mapped["alternate_greetings"]:
        data["alternate_greetings"] = mapped["alternate_greetings"]
    if isinstance(mapped.get("tags"), list) and mapped["tags"]:
        data["tags"] = mapped["tags"]
    return {
        "spec": "chara_card_v3",
        "spec_version": "3.0",
        "data": data,
    }


def _mapped_text(mapped: dict[str, Any], key: str) -> str:
    value = mapped.get(key)
    return value if isinstance(value, str) else ""
