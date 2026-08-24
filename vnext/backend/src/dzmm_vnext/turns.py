from __future__ import annotations

from collections.abc import AsyncIterator
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from jsonschema import ValidationError
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .contracts import contract_validator
from .core.command_engine import apply_commands as apply_core_commands
from .lore import select_lorebook
from .model_profiles import ModelNarrator, ModelProfile, NarrationError, _clean_narrative
from .narrative import (
    NarrativeRuleError,
    advance_world_events,
    apply_gm_actions,
    planned_choice_commands,
    record_narrative_context,
    schedule_npc_initiative,
    settle_pending_interactions,
    settle_world_events,
)
from .narrative_output import extract_gm_actions
from .operation_control import OperationRegistry
from .persistence import model_profiles, runs, story_beats, turns, world_versions, worlds
from .story_beats import build_deterministic_narrative, build_turn_story_beat


class TurnInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(min_length=1, max_length=80)
    expected_revision: int = Field(ge=0)
    player_input: str = Field(min_length=1, max_length=4000)
    commands: list[dict[str, Any]] = Field(min_length=1, max_length=16)


class TurnRollbackInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(min_length=1, max_length=80)
    expected_revision: int = Field(ge=0)
    target_turn_id: str = Field(min_length=1, max_length=36)


class ChoiceTurnInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(min_length=1, max_length=80)
    expected_revision: int = Field(ge=0)
    player_input: str = Field(min_length=1, max_length=4000)
    choice_id: str = Field(min_length=1, max_length=64)


class TurnResult(BaseModel):
    turn_id: str
    kind: str
    rollback_target_id: str | None
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
        self._operations = OperationRegistry()

    def begin_operation(self, request_id: str) -> bool:
        return self._operations.begin(request_id)

    def cancel_operation(self, request_id: str) -> bool:
        return self._operations.cancel(request_id)

    def finish_operation(self, request_id: str) -> None:
        self._operations.finish(request_id)

    def _require_apply_permission(self, request_id: str) -> None:
        if not self._operations.enter_applying(request_id):
            raise RevisionConflictError("operation cancelled; original Run state was not changed")

    async def play(
        self, run_id: str, payload: TurnInput, *, planned_choice: bool = False
    ) -> TurnResult:
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
                    model_profiles.c.api_key_ref,
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
            if run["state"].get("ending"):
                raise RevisionConflictError(
                    "run has ended; start a new Run or rollback to an earlier turn"
                )
            if not planned_choice and _requires_choice_planner(run["definition"], payload.commands):
                raise RevisionConflictError(
                    "narrative rulesets accept state changes only through the choices endpoint"
                )

            state = deepcopy(run["state"])
            outcomes = _apply_commands(state, run["definition"], payload.commands)
            before_revision = run["state_revision"]
            after_revision = before_revision + 1
            state["revision"] = after_revision
            outcomes.extend(advance_world_events(state, run["definition"]))
            try:
                contract_validator("run_state.schema.json").validate(state)
            except ValidationError as error:
                raise RevisionConflictError(
                    f"engine created invalid RunState: {error.message}"
                ) from error

            profile = _profile_from_row(run)
            lore = select_lorebook(run["definition"], payload.player_input, character_budget=4000)
            narrative, gm_actions = await self._narrate(
                profile,
                run["definition"],
                state,
                payload.player_input,
                outcomes,
                lore.entries,
                variation_seed=run_id,
            )
            outcomes.extend(apply_gm_actions(state, gm_actions))
            settle_world_events(state, run["definition"], outcomes)
            settle_pending_interactions(state, outcomes)
            record_narrative_context(
                state, run["definition"], run_id, payload.player_input, narrative, outcomes
            )
            initiative = schedule_npc_initiative(state, run["definition"], run_id)
            if initiative:
                outcomes.append(initiative)
            try:
                contract_validator("run_state.schema.json").validate(state)
            except ValidationError as error:
                raise RevisionConflictError(
                    f"engine created invalid RunState: {error.message}"
                ) from error

            self._require_apply_permission(payload.request_id)
            changed = await session.execute(
                update(runs)
                .where(runs.c.id == run_id, runs.c.state_revision == before_revision)
                .values(
                    state=state,
                    state_revision=after_revision,
                    status="completed" if state.get("ending") else "active",
                    updated_at=datetime.now(UTC).replace(tzinfo=None),
                )
            )
            if changed.rowcount != 1:
                raise RevisionConflictError("run changed while the turn was being applied")

            sequence = (
                await session.execute(
                    select(func.coalesce(func.max(turns.c.sequence), 0)).where(
                        turns.c.run_id == run_id
                    )
                )
            ).scalar_one() + 1
            turn_id = str(uuid4())
            await session.execute(
                insert(turns).values(
                    id=turn_id,
                    run_id=run_id,
                    request_id=payload.request_id,
                    kind="turn",
                    rollback_target_id=None,
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
            await self._insert_story_beat(
                session, run_id, sequence, run["definition"], state, narrative, outcomes
            )
            return TurnResult(
                turn_id=turn_id,
                kind="turn",
                rollback_target_id=None,
                sequence=sequence,
                narrative=narrative,
                commands=payload.commands,
                outcomes=outcomes,
                before_revision=before_revision,
                after_revision=after_revision,
                state=state,
                created=True,
            )

    async def play_choice(self, run_id: str, payload: ChoiceTurnInput) -> TurnResult:
        async with self._session_factory() as session:
            existing = await session.execute(
                select(turns).where(
                    turns.c.run_id == run_id,
                    turns.c.request_id == payload.request_id,
                )
            )
            existing_row = existing.mappings().one_or_none()
            if existing_row:
                commands = existing_row["commands"]
                if (
                    existing_row["player_input"] != payload.player_input
                    or not commands
                    or commands[0]
                    != {
                        "type": "choose_story_choice",
                        "payload": {"choice_id": payload.choice_id},
                    }
                ):
                    raise TurnIdempotencyConflictError(
                        "request_id was already used for different choice input"
                    )
                return _turn_result(existing_row, created=False)
            result = await session.execute(
                select(runs.c.state, runs.c.state_revision, world_versions.c.definition)
                .join(world_versions, world_versions.c.id == runs.c.world_version_id)
                .where(runs.c.id == run_id)
            )
            run = result.mappings().one_or_none()
        if run is None:
            raise RunNotFoundError("run not found")
        if payload.expected_revision != run["state_revision"]:
            raise RevisionConflictError(
                f"expected revision {payload.expected_revision}, current revision is {run['state_revision']}"
            )
        try:
            commands = planned_choice_commands(run["state"], run["definition"], payload.choice_id)
        except NarrativeRuleError as error:
            raise RevisionConflictError(str(error)) from error
        return await self.play(
            run_id,
            TurnInput(
                request_id=payload.request_id,
                expected_revision=payload.expected_revision,
                player_input=payload.player_input,
                commands=commands,
            ),
            planned_choice=True,
        )

    async def stream(
        self,
        run_id: str,
        payload: TurnInput,
        *,
        planned_choice: bool = False,
        choice_id: str | None = None,
    ) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        """Stream narration before committing the validated turn exactly once."""
        async with self._session_factory() as session:
            existing = await session.execute(
                select(turns).where(
                    turns.c.run_id == run_id, turns.c.request_id == payload.request_id
                )
            )
            existing_row = existing.mappings().one_or_none()
            if existing_row:
                if existing_row["player_input"] != payload.player_input or (
                    planned_choice
                    and not _choice_command_matches(existing_row["commands"], choice_id)
                ) or (
                    not planned_choice and existing_row["commands"] != payload.commands
                ):
                    yield (
                        "turn_failed",
                        {
                            "category": "idempotency",
                            "detail": "request_id was already used for different turn input",
                        },
                    )
                    return
                turn = _turn_result(existing_row, created=False)
                yield "turn_started", {"revision": turn.before_revision}
                yield "narrative_delta", {"text": turn.narrative}
                for outcome in turn.outcomes:
                    yield "command_applied", outcome
                yield (
                    "turn_completed",
                    {
                        "turn_id": turn.turn_id,
                        "revision": turn.after_revision,
                        "created": False,
                    },
                )
                return
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
                    model_profiles.c.api_key_ref,
                    worlds.c.status.label("world_status"),
                )
                .join(world_versions, world_versions.c.id == runs.c.world_version_id)
                .join(worlds, worlds.c.id == world_versions.c.world_id)
                .outerjoin(model_profiles, model_profiles.c.id == runs.c.model_profile_id)
                .where(runs.c.id == run_id)
            )
            run = result.mappings().one_or_none()
        if run is None:
            yield "turn_failed", {"category": "run", "detail": "run not found"}
            return
        if run["state"].get("ending"):
            yield (
                "turn_failed",
                {
                    "category": "state",
                    "detail": "run has ended; start a new Run or rollback to an earlier turn",
                },
            )
            return
        if run["world_status"] != "active":
            yield (
                "turn_failed",
                {"category": "state", "detail": "archived world cannot receive new turns"},
            )
            return
        if payload.expected_revision != run["state_revision"]:
            yield (
                "turn_failed",
                {
                    "category": "state",
                    "detail": f"expected revision {payload.expected_revision}, current revision is {run['state_revision']}",
                },
            )
            return
        commands = payload.commands
        if planned_choice:
            if not choice_id:
                yield "turn_failed", {"category": "command", "detail": "choice id is required"}
                return
            try:
                commands = planned_choice_commands(run["state"], run["definition"], choice_id)
            except NarrativeRuleError as error:
                yield "turn_failed", {"category": "command", "detail": str(error)}
                return
        elif _requires_choice_planner(run["definition"], commands):
            yield (
                "turn_failed",
                {
                    "category": "command",
                    "detail": "narrative rulesets accept state changes only through the choices endpoint",
                },
            )
            return

        state = deepcopy(run["state"])
        try:
            outcomes = _apply_commands(state, run["definition"], commands)
        except RevisionConflictError as error:
            yield "turn_failed", {"category": "command", "detail": str(error)}
            return
        before_revision = run["state_revision"]
        after_revision = before_revision + 1
        state["revision"] = after_revision
        outcomes.extend(advance_world_events(state, run["definition"]))
        try:
            contract_validator("run_state.schema.json").validate(state)
        except ValidationError as error:
            yield "turn_failed", {"category": "state", "detail": str(error)}
            return

        yield "turn_started", {"revision": before_revision}
        profile = _profile_from_row(run)
        raw_narrative = ""
        emitted_narrative = ""
        try:
            if profile is None:
                raw_narrative = _deterministic_narrative(
                    run["definition"], state, payload.player_input
                )
                emitted_narrative = raw_narrative
                yield "narrative_delta", {"text": raw_narrative}
            else:
                lore = select_lorebook(
                    run["definition"], payload.player_input, character_budget=4000
                )
                try:
                    narrator_stream = self._narrator.stream(
                        profile,
                        run["definition"],
                        state,
                        payload.player_input,
                        outcomes,
                        lore.entries,
                        variation_seed=run_id,
                    )
                except TypeError as error:
                    # Keep the transport seam compatible with lightweight test and
                    # embedded narrators written before the variation context existed.
                    if "variation_seed" not in str(error):
                        raise
                    narrator_stream = self._narrator.stream(
                        profile,
                        run["definition"],
                        state,
                        payload.player_input,
                        outcomes,
                        lore.entries,
                    )
                async for piece in narrator_stream:
                    raw_narrative += piece
                    visible = _visible_stream_narrative(raw_narrative)
                    if visible.startswith(emitted_narrative):
                        delta = visible[len(emitted_narrative) :]
                        emitted_narrative = visible
                        if delta:
                            yield "narrative_delta", {"text": delta}
            visible_narrative, gm_actions = extract_gm_actions(raw_narrative)
            narrative = _clean_narrative(visible_narrative)
            if (
                not narrative
                or raw_narrative.lstrip().startswith("<think>")
                and "</think>" not in raw_narrative
            ):
                raise NarrationError("model returned no valid narrative content")
            outcomes.extend(apply_gm_actions(state, gm_actions))
            settle_world_events(state, run["definition"], outcomes)
            settle_pending_interactions(state, outcomes)
            record_narrative_context(
                state, run["definition"], run_id, payload.player_input, narrative, outcomes
            )
            initiative = schedule_npc_initiative(state, run["definition"], run_id)
            if initiative:
                outcomes.append(initiative)
            try:
                contract_validator("run_state.schema.json").validate(state)
            except ValidationError as error:
                yield "turn_failed", {"category": "state", "detail": str(error)}
                return
        except NarrationError as error:
            yield "turn_failed", {"category": "model", "detail": str(error)}
            return

        try:
            commit_payload = payload.model_copy(update={"commands": commands})
            turn = await self._commit_stream_turn(
                run_id,
                commit_payload,
                run["definition"],
                state,
                outcomes,
                before_revision,
                after_revision,
                narrative,
            )
        except (RunNotFoundError, RevisionConflictError, TurnIdempotencyConflictError) as error:
            yield "turn_failed", {"category": "state", "detail": str(error)}
            return
        for outcome in turn.outcomes:
            yield "command_applied", outcome
        yield (
            "turn_completed",
            {
                "turn_id": turn.turn_id,
                "revision": turn.after_revision,
                "created": turn.created,
            },
        )

    async def _commit_stream_turn(
        self,
        run_id: str,
        payload: TurnInput,
        definition: dict[str, Any],
        state: dict[str, Any],
        outcomes: list[dict[str, Any]],
        before_revision: int,
        after_revision: int,
        narrative: str,
    ) -> TurnResult:
        async with self._session_factory() as session, session.begin():
            existing = await session.execute(
                select(turns).where(
                    turns.c.run_id == run_id, turns.c.request_id == payload.request_id
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
            current = await session.execute(
                select(runs.c.state_revision, worlds.c.status.label("world_status"))
                .join(world_versions, world_versions.c.id == runs.c.world_version_id)
                .join(worlds, worlds.c.id == world_versions.c.world_id)
                .where(runs.c.id == run_id)
            )
            row = current.mappings().one_or_none()
            if row is None:
                raise RunNotFoundError("run not found")
            if row["world_status"] != "active" or row["state_revision"] != before_revision:
                raise RevisionConflictError("run changed while narration was streaming")
            self._require_apply_permission(payload.request_id)
            changed = await session.execute(
                update(runs)
                .where(runs.c.id == run_id, runs.c.state_revision == before_revision)
                .values(
                    state=state,
                    state_revision=after_revision,
                    status="completed" if state.get("ending") else "active",
                    updated_at=datetime.now(UTC).replace(tzinfo=None),
                )
            )
            if changed.rowcount != 1:
                raise RevisionConflictError("run changed while narration was streaming")
            sequence = (
                await session.execute(
                    select(func.coalesce(func.max(turns.c.sequence), 0)).where(
                        turns.c.run_id == run_id
                    )
                )
            ).scalar_one() + 1
            turn_id = str(uuid4())
            await session.execute(
                insert(turns).values(
                    id=turn_id,
                    run_id=run_id,
                    request_id=payload.request_id,
                    kind="turn",
                    rollback_target_id=None,
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
            await self._insert_story_beat(
                session, run_id, sequence, definition, state, narrative, outcomes
            )
            return TurnResult(
                turn_id=turn_id,
                kind="turn",
                rollback_target_id=None,
                sequence=sequence,
                narrative=narrative,
                commands=payload.commands,
                outcomes=outcomes,
                before_revision=before_revision,
                after_revision=after_revision,
                state=state,
                created=True,
            )

    async def _insert_story_beat(
        self,
        session: AsyncSession,
        run_id: str,
        sequence: int,
        definition: dict[str, Any],
        state: dict[str, Any],
        narrative: str,
        outcomes: list[dict[str, Any]],
    ) -> None:
        beat = build_turn_story_beat(definition, state, narrative, outcomes)
        await session.execute(
            insert(story_beats).values(
                id=str(uuid4()),
                run_id=run_id,
                kind=beat["kind"],
                sequence=sequence,
                content=beat,
                created_at=datetime.now(UTC).replace(tzinfo=None),
            )
        )

    async def rollback(self, run_id: str, payload: TurnRollbackInput) -> TurnResult:
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
                    existing_row["kind"] != "rollback"
                    or existing_row["rollback_target_id"] != payload.target_turn_id
                ):
                    raise TurnIdempotencyConflictError(
                        "request_id was already used for different turn input"
                    )
                return _turn_result(existing_row, created=False)

            run_result = await session.execute(
                select(runs.c.state_revision, worlds.c.status.label("world_status"))
                .join(world_versions, world_versions.c.id == runs.c.world_version_id)
                .join(worlds, worlds.c.id == world_versions.c.world_id)
                .where(runs.c.id == run_id)
            )
            run = run_result.mappings().one_or_none()
            if run is None:
                raise RunNotFoundError("run not found")
            if run["world_status"] != "active":
                raise RevisionConflictError("archived world cannot receive new turns")
            if payload.expected_revision != run["state_revision"]:
                raise RevisionConflictError(
                    f"expected revision {payload.expected_revision}, current revision is {run['state_revision']}"
                )

            target_result = await session.execute(
                select(turns).where(
                    turns.c.id == payload.target_turn_id,
                    turns.c.run_id == run_id,
                )
            )
            target = target_result.mappings().one_or_none()
            if target is None:
                raise RevisionConflictError("rollback target is not part of this run")

            before_revision = run["state_revision"]
            after_revision = before_revision + 1
            state = deepcopy(target["after_state"])
            state["revision"] = after_revision
            try:
                contract_validator("run_state.schema.json").validate(state)
            except ValidationError as error:
                raise RevisionConflictError(
                    f"rollback created invalid RunState: {error.message}"
                ) from error

            changed = await session.execute(
                update(runs)
                .where(runs.c.id == run_id, runs.c.state_revision == before_revision)
                .values(
                    state=state,
                    state_revision=after_revision,
                    status="completed" if state.get("ending") else "active",
                    updated_at=datetime.now(UTC).replace(tzinfo=None),
                )
            )
            if changed.rowcount != 1:
                raise RevisionConflictError("run changed while the rollback was being applied")

            sequence = (
                await session.execute(
                    select(func.coalesce(func.max(turns.c.sequence), 0)).where(
                        turns.c.run_id == run_id
                    )
                )
            ).scalar_one() + 1
            turn_id = str(uuid4())
            outcomes = [{"type": "rollback", "target_turn_id": target["id"]}]
            narrative = f"已恢复到第 {target['sequence']} 回合之后的状态。"
            await session.execute(
                insert(turns).values(
                    id=turn_id,
                    run_id=run_id,
                    request_id=payload.request_id,
                    kind="rollback",
                    rollback_target_id=target["id"],
                    sequence=sequence,
                    player_input=f"回滚到第 {target['sequence']} 回合之后",
                    narrative=narrative,
                    commands=[],
                    outcomes=outcomes,
                    before_revision=before_revision,
                    after_revision=after_revision,
                    after_state=state,
                    created_at=datetime.now(UTC).replace(tzinfo=None),
                )
            )
            return TurnResult(
                turn_id=turn_id,
                kind="rollback",
                rollback_target_id=target["id"],
                sequence=sequence,
                narrative=narrative,
                commands=[],
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
        lore_entries: list[dict[str, Any]],
        *,
        variation_seed: str = "",
    ) -> tuple[str, list[dict[str, Any]]]:
        if profile is None:
            return _deterministic_narrative(definition, state, player_input), []
        narrate_with_actions = getattr(self._narrator, "narrate_with_actions", None)
        # Tests and lightweight hosts often replace the legacy narrate method;
        # honor that seam instead of bypassing it with the new action-aware path.
        if type(self._narrator).narrate is not ModelNarrator.narrate or "narrate" in getattr(
            self._narrator, "__dict__", {}
        ):
            narrate_with_actions = None
        if narrate_with_actions is not None:
            try:
                return await narrate_with_actions(
                    profile,
                    definition,
                    state,
                    player_input,
                    outcomes,
                    lore_entries,
                    variation_seed=variation_seed,
                )
            except TypeError as error:
                if "variation_seed" not in str(error):
                    raise
                return await narrate_with_actions(
                    profile,
                    definition,
                    state,
                    player_input,
                    outcomes,
                    lore_entries,
                )
        try:
            narrative = await self._narrator.narrate(
                profile,
                definition,
                state,
                player_input,
                outcomes,
                lore_entries,
                variation_seed=variation_seed,
            )
        except TypeError as error:
            if "variation_seed" not in str(error):
                raise
            narrative = await self._narrator.narrate(
                profile,
                definition,
                state,
                player_input,
                outcomes,
                lore_entries,
            )
        visible, actions = extract_gm_actions(narrative)
        return _clean_narrative(visible) or "", actions


def _requires_choice_planner(
    definition: dict[str, Any], commands: list[dict[str, Any]]
) -> bool:
    """Keep authored effects behind choices while allowing free GM-led actions."""

    if "choices" not in definition["ruleset"]["enabled_capabilities"]:
        return False
    return any(command.get("type") not in {"narrate", "move"} for command in commands)


def _validate_command(command: dict[str, Any]) -> None:
    try:
        contract_validator("turn_command.schema.json").validate(command)
    except ValidationError as error:
        raise RevisionConflictError(f"invalid TurnCommand: {error.message}") from error


def _apply_commands(
    state: dict[str, Any], definition: dict[str, Any], commands: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    return apply_core_commands(
        state,
        definition,
        commands,
        validate_command=_validate_command,
        error_type=RevisionConflictError,
    )


def _deterministic_narrative(
    definition: dict[str, Any], state: dict[str, Any], player_input: str
) -> str:
    return build_deterministic_narrative(definition, state, player_input)


def _visible_stream_narrative(raw: str) -> str:
    value = raw.lstrip()
    if value.startswith("<think>"):
        if "</think>" not in value:
            return ""
        value = value.split("</think>", maxsplit=1)[1].lstrip()
    if value.startswith("###") and "### TRPG Narrative:" not in value:
        return ""
    if "### TRPG Narrative:" in value:
        value = value.split("### TRPG Narrative:", maxsplit=1)[1]
    if "### JSON:" in value:
        value = value.split("### JSON:", maxsplit=1)[0]
    marker = value.find("<!--DZMM_ACTIONS")
    if marker >= 0:
        value = value[:marker]
    return value.lstrip("# ").strip()


def _choice_command_matches(commands: Any, choice_id: str | None) -> bool:
    if not isinstance(commands, list) or not choice_id:
        return False
    return any(
        isinstance(command, dict)
        and command.get("type") == "choose_story_choice"
        and isinstance(command.get("payload"), dict)
        and command["payload"].get("choice_id") == choice_id
        for command in commands
    )


def _profile_from_row(row: Any) -> ModelProfile | None:
    if row["model_id"] is None:
        return None
    return ModelProfile(
        id=row["model_id"],
        name=row["model_name_label"],
        provider_type=row["provider_type"],
        base_url=row["base_url"],
        model_name=row["model_name"],
        api_key_ref=row["api_key_ref"],
        has_api_key=row["api_key_ref"] is not None,
    )


def _turn_result(row: Any, *, created: bool) -> TurnResult:
    return TurnResult(
        turn_id=row["id"],
        kind=row["kind"],
        rollback_target_id=row["rollback_target_id"],
        sequence=row["sequence"],
        narrative=row["narrative"],
        commands=row["commands"],
        outcomes=row["outcomes"],
        before_revision=row["before_revision"],
        after_revision=row["after_revision"],
        state=row["after_state"],
        created=created,
    )
