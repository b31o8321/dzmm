from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from secrets import randbelow
from typing import Any
from uuid import uuid4

from jsonschema import ValidationError
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .contracts import contract_validator
from .model_profiles import ModelNarrator, ModelProfile
from .persistence import model_profiles, runs, turns, world_versions, worlds


class TurnInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(min_length=1, max_length=80)
    expected_revision: int = Field(ge=0)
    player_input: str = Field(min_length=1, max_length=4000)
    commands: list[dict[str, Any]] = Field(min_length=1, max_length=16)


class TurnResult(BaseModel):
    turn_id: str
    sequence: int
    narrative: str
    commands: list[dict[str, Any]]
    outcomes: list[dict[str, Any]]
    before_revision: int
    after_revision: int
    state: dict[str, Any]
    created: bool


class RunNotFoundError(ValueError):
    pass


class RevisionConflictError(ValueError):
    pass


class TurnIdempotencyConflictError(ValueError):
    pass


class TurnCoordinator:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        narrator: ModelNarrator | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._narrator = narrator or ModelNarrator()

    async def play(self, run_id: str, payload: TurnInput) -> TurnResult:
        async with self._session_factory() as session, session.begin():
            existing = await session.execute(
                select(turns).where(
                    turns.c.run_id == run_id,
                    turns.c.request_id == payload.request_id,
                )
            )
            existing_row = existing.mappings().one_or_none()
            if existing_row:
                if (
                    existing_row["player_input"] != payload.player_input
                    or existing_row["commands"] != payload.commands
                ):
                    raise TurnIdempotencyConflictError(
                        "request_id was already used for different turn input"
                    )
                return _turn_result(existing_row, created=False)

            result = await session.execute(
                select(
                    runs.c.state,
                    runs.c.state_revision,
                    world_versions.c.definition,
                    model_profiles.c.id.label("model_id"),
                    model_profiles.c.name.label("model_name_label"),
                    model_profiles.c.provider_type,
                    model_profiles.c.base_url,
                    model_profiles.c.model_name,
                    worlds.c.status.label("world_status"),
                )
                .join(world_versions, world_versions.c.id == runs.c.world_version_id)
                .join(worlds, worlds.c.id == world_versions.c.world_id)
                .outerjoin(model_profiles, model_profiles.c.id == runs.c.model_profile_id)
                .where(runs.c.id == run_id)
            )
            run = result.mappings().one_or_none()
            if run is None:
                raise RunNotFoundError("run not found")
            if run["world_status"] != "active":
                raise RevisionConflictError("archived world cannot receive new turns")
            if payload.expected_revision != run["state_revision"]:
                raise RevisionConflictError(
                    f"expected revision {payload.expected_revision}, current revision is {run['state_revision']}"
                )

            state = deepcopy(run["state"])
            outcomes = _apply_commands(state, run["definition"], payload.commands)
            before_revision = run["state_revision"]
            after_revision = before_revision + 1
            state["revision"] = after_revision
            try:
                contract_validator("run_state.schema.json").validate(state)
            except ValidationError as error:
                raise RevisionConflictError(f"engine created invalid RunState: {error.message}") from error

            profile = _profile_from_row(run)
            narrative = await self._narrate(profile, run["definition"], state, payload.player_input, outcomes)

            changed = await session.execute(
                update(runs)
                .where(runs.c.id == run_id, runs.c.state_revision == before_revision)
                .values(
                    state=state,
                    state_revision=after_revision,
                    updated_at=datetime.now(UTC).replace(tzinfo=None),
                )
            )
            if changed.rowcount != 1:
                raise RevisionConflictError("run changed while the turn was being applied")

            sequence = (
                await session.execute(
                    select(func.coalesce(func.max(turns.c.sequence), 0)).where(turns.c.run_id == run_id)
                )
            ).scalar_one() + 1
            turn_id = str(uuid4())
            await session.execute(
                insert(turns).values(
                    id=turn_id,
                    run_id=run_id,
                    request_id=payload.request_id,
                    sequence=sequence,
                    player_input=payload.player_input,
                    narrative=narrative,
                    commands=payload.commands,
                    outcomes=outcomes,
                    before_revision=before_revision,
                    after_revision=after_revision,
                    after_state=state,
                    created_at=datetime.now(UTC).replace(tzinfo=None),
                )
            )
            return TurnResult(
                turn_id=turn_id,
                sequence=sequence,
                narrative=narrative,
                commands=payload.commands,
                outcomes=outcomes,
                before_revision=before_revision,
                after_revision=after_revision,
                state=state,
                created=True,
            )

    async def _narrate(
        self,
        profile: ModelProfile | None,
        definition: dict[str, Any],
        state: dict[str, Any],
        player_input: str,
        outcomes: list[dict[str, Any]],
    ) -> str:
        if profile is None:
            return _deterministic_narrative(state, player_input)
        return await self._narrator.narrate(profile, definition, state, player_input, outcomes)

def _apply_commands(
    state: dict[str, Any], definition: dict[str, Any], commands: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    known_locations = {location["id"] for location in definition["locations"]}
    known_entities = {
        entity["id"]
        for group in ("locations", "factions", "npcs")
        for entity in definition[group]
    }
    known_events = {event["id"] for event in definition["events"]}
    outcomes: list[dict[str, Any]] = []
    for command in commands:
        _validate_command(command)
        command_type = command["type"]
        payload = command.get("payload", {})
        if command_type == "narrate":
            outcomes.append({"type": "narrate", "accepted": True})
        elif command_type == "offer_choices":
            choices = payload.get("choices")
            if not isinstance(choices, list) or not all(isinstance(choice, str) for choice in choices):
                raise RevisionConflictError("offer_choices requires a list of string choices")
            outcomes.append({"type": "offer_choices", "choices": choices})
        elif command_type == "roll_dice":
            sides = payload.get("sides")
            if not isinstance(sides, int) or not 2 <= sides <= 100:
                raise RevisionConflictError("roll_dice requires sides from 2 to 100")
            outcomes.append({"type": "roll_dice", "sides": sides, "result": randbelow(sides) + 1})
        elif command_type == "move":
            location_id = payload.get("location_id")
            if location_id not in known_locations:
                raise RevisionConflictError("move references an unknown location")
            state["location_id"] = location_id
            outcomes.append({"type": "move", "location_id": location_id})
        elif command_type == "set_entity_state":
            entity_id = payload.get("entity_id")
            if entity_id not in known_entities:
                raise RevisionConflictError("set_entity_state references an unknown entity")
            value = payload.get("value")
            state["entities"][entity_id] = value
            outcomes.append({"type": "set_entity_state", "entity_id": entity_id})
        elif command_type == "set_event_state":
            event_id = payload.get("event_id")
            if event_id not in known_events:
                raise RevisionConflictError("set_event_state references an unknown event")
            value = payload.get("value")
            state["events"][event_id] = value
            outcomes.append({"type": "set_event_state", "event_id": event_id})
        elif command_type == "inventory_change":
            item_id, delta = payload.get("item_id"), payload.get("delta")
            if not isinstance(item_id, str) or not item_id or not isinstance(delta, int) or delta == 0:
                raise RevisionConflictError("inventory_change requires item_id and non-zero integer delta")
            _change_inventory(state["inventory"], item_id, delta)
            outcomes.append({"type": "inventory_change", "item_id": item_id, "delta": delta})
    return outcomes


def _validate_command(command: dict[str, Any]) -> None:
    try:
        contract_validator("turn_command.schema.json").validate(command)
    except ValidationError as error:
        raise RevisionConflictError(f"invalid TurnCommand: {error.message}") from error


def _change_inventory(inventory: list[dict[str, Any]], item_id: str, delta: int) -> None:
    current = next((item for item in inventory if item.get("id") == item_id), None)
    quantity = (current.get("quantity", 0) if current else 0) + delta
    if quantity < 0:
        raise RevisionConflictError("inventory cannot become negative")
    if current is None and quantity:
        inventory.append({"id": item_id, "quantity": quantity})
    elif current is not None and quantity:
        current["quantity"] = quantity
    elif current is not None:
        inventory.remove(current)


def _deterministic_narrative(state: dict[str, Any], player_input: str) -> str:
    return f"{state['hero']['name']} acts at {state['location_id']}: {player_input}"


def _profile_from_row(row: Any) -> ModelProfile | None:
    if row["model_id"] is None:
        return None
    return ModelProfile(
        id=row["model_id"],
        name=row["model_name_label"],
        provider_type=row["provider_type"],
        base_url=row["base_url"],
        model_name=row["model_name"],
    )


def _turn_result(row: Any, *, created: bool) -> TurnResult:
    return TurnResult(
        turn_id=row["id"],
        sequence=row["sequence"],
        narrative=row["narrative"],
        commands=row["commands"],
        outcomes=row["outcomes"],
        before_revision=row["before_revision"],
        after_revision=row["after_revision"],
        state=row["after_state"],
        created=created,
    )
