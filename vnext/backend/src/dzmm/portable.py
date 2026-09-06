from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from jsonschema import ValidationError
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .contracts import contract_validator
from .persistence import heroes, runs, story_beats, turns, world_versions, worlds
from .worlds import ComposeWorldInput, HeroInput, WorldComposer


class PortableBundleError(ValueError):
    pass


class PortableImportInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(min_length=1, max_length=80)
    bundle: dict[str, Any]
    model_profile_id: str | None = None


class PortableRunCloneInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(min_length=1, max_length=80)
    bundle: dict[str, Any]


class PortableService:
    """Explicit, one-way portability boundary.

    Bundles never carry host tokens or model credentials. Import and clone
    always allocate new aggregate IDs; there is no automatic synchronization
    or shared Run identity across devices.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        composer: WorldComposer,
    ) -> None:
        self._session_factory = session_factory
        self._composer = composer

    async def export_world(self, world_id: str) -> dict[str, Any] | None:
        async with self._session_factory() as session:
            result = await session.execute(
                select(worlds, world_versions)
                .join(world_versions, world_versions.c.world_id == worlds.c.id)
                .where(worlds.c.id == world_id)
                .order_by(world_versions.c.version_number.desc())
                .limit(1)
            )
            row = result.mappings().one_or_none()
            if row is None:
                return None
            hero_rows = await session.execute(
                select(heroes.c.name, heroes.c.profile)
                .join(runs, runs.c.hero_id == heroes.c.id)
                .join(world_versions, world_versions.c.id == runs.c.world_version_id)
                .where(world_versions.c.world_id == world_id)
                .distinct()
            )
        return {
            "bundle_version": 1,
            "kind": "world",
            "source": {"world_id": world_id},
            "world": {"name": row["name"], "status": "active"},
            "world_version": {"definition": row["definition"]},
            "heroes": [dict(hero) for hero in hero_rows.mappings()],
            "portable_policy": {
                "new_ids_on_import": True,
                "model_profiles_included": False,
                "automatic_sync": False,
            },
        }

    async def import_world(self, payload: PortableImportInput) -> Any:
        bundle = _require_bundle(payload.bundle, "world")
        definition = _definition(bundle)
        hero_data = (bundle.get("heroes") or [{"name": "旅行者", "profile": {}}])[0]
        hero = HeroInput(
            name=str(hero_data.get("name") or "旅行者"),
            profile=dict(hero_data.get("profile") or {}),
        )
        return await self._composer.compose(
            ComposeWorldInput(
                request_id=payload.request_id,
                world_definition=definition,
                hero=hero,
                model_profile_id=payload.model_profile_id,
            )
        )

    async def export_run(self, run_id: str) -> dict[str, Any] | None:
        async with self._session_factory() as session:
            result = await session.execute(
                select(
                    runs.c.id,
                    runs.c.model_profile_id,
                    runs.c.state,
                    runs.c.state_revision,
                    world_versions.c.definition,
                    heroes.c.name,
                    heroes.c.profile,
                )
                .join(world_versions, world_versions.c.id == runs.c.world_version_id)
                .join(heroes, heroes.c.id == runs.c.hero_id)
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
                    turns.c.request_id,
                    turns.c.player_input,
                    turns.c.narrative,
                    turns.c.commands,
                    turns.c.outcomes,
                    turns.c.before_revision,
                    turns.c.after_revision,
                    turns.c.after_state,
                )
                .where(turns.c.run_id == run_id)
                .order_by(turns.c.sequence)
            )
            beat_rows = await session.execute(
                select(story_beats.c.kind, story_beats.c.sequence, story_beats.c.content)
                .where(story_beats.c.run_id == run_id)
                .order_by(story_beats.c.sequence)
            )
        return {
            "bundle_version": 1,
            "kind": "run",
            "source": {"run_id": run_id},
            "world_version": {"definition": run["definition"]},
            "hero": {"name": run["name"], "profile": run["profile"]},
            "run": {
                "state": run["state"],
                "state_revision": run.get("state_revision"),
                "story_beats": [dict(beat) for beat in beat_rows.mappings()],
                "turns": [dict(turn) for turn in turn_rows.mappings()],
            },
            "portable_policy": {
                "new_ids_on_clone": True,
                "model_profile_included": False,
                "automatic_sync": False,
            },
        }

    async def clone_run(self, payload: PortableRunCloneInput) -> Any:
        bundle = _require_bundle(payload.bundle, "run")
        definition = _definition(bundle)
        hero_data = bundle.get("hero") or {}
        hero = HeroInput(
            name=str(hero_data.get("name") or "旅行者"),
            profile=dict(hero_data.get("profile") or {}),
        )
        run_data = bundle.get("run") or {}
        state = run_data.get("state")
        if not isinstance(state, dict):
            raise PortableBundleError("run bundle is missing an object state")
        try:
            contract_validator("run_state.schema.json").validate(state)
        except ValidationError as error:
            raise PortableBundleError(f"invalid portable RunState: {error.message}") from error

        exported_turns = run_data.get("turns") or []
        exported_beats = run_data.get("story_beats") or []
        _validate_turns(exported_turns)
        _validate_story_beats(exported_beats)
        composed = await self._composer.compose(
            ComposeWorldInput(
                request_id=payload.request_id,
                world_definition=definition,
                hero=hero,
                model_profile_id=None,
            )
        )
        await self._restore_snapshot(composed.run_id, state, exported_beats, exported_turns)
        return composed.model_copy(update={"state": state})

    async def _restore_snapshot(
        self,
        run_id: str,
        state: dict[str, Any],
        exported_beats: list[Any],
        exported_turns: list[Any],
    ) -> None:
        now = datetime.now(UTC).replace(tzinfo=None)
        async with self._session_factory() as session, session.begin():
            run = await session.execute(select(runs.c.state_revision).where(runs.c.id == run_id))
            if run.scalar_one_or_none() is None:
                raise PortableBundleError("new cloned run disappeared")
            revision = int(state.get("revision", 0))
            await session.execute(
                update(runs)
                .where(runs.c.id == run_id)
                .values(state=state, state_revision=revision, updated_at=now)
            )
            if exported_beats:
                await session.execute(delete(story_beats).where(story_beats.c.run_id == run_id))
                for item in exported_beats:
                    await session.execute(
                        insert(story_beats).values(
                            id=str(uuid4()),
                            run_id=run_id,
                            kind=item["kind"],
                            sequence=item["sequence"],
                            content=item["content"],
                            created_at=now,
                        )
                    )
            id_map: dict[str, str] = {}
            for item in exported_turns:
                if not isinstance(item, dict):
                    continue
                id_map[str(item.get("id", uuid4()))] = str(uuid4())
            for item in exported_turns:
                if not isinstance(item, dict):
                    continue
                old_target = item.get("rollback_target_id")
                await session.execute(
                    insert(turns).values(
                        id=id_map.get(str(item.get("id")), str(uuid4())),
                        run_id=run_id,
                        request_id=str(item.get("request_id") or uuid4()),
                        kind=str(item.get("kind") or "narrative"),
                        rollback_target_id=id_map.get(str(old_target)) if old_target else None,
                        sequence=int(item.get("sequence") or 0),
                        player_input=str(item.get("player_input") or ""),
                        narrative=str(item.get("narrative") or ""),
                        commands=item.get("commands") or [],
                        outcomes=item.get("outcomes") or [],
                        before_revision=int(item.get("before_revision") or 0),
                        after_revision=int(item.get("after_revision") or 0),
                        after_state=item.get("after_state") or state,
                        created_at=now,
                    )
                )


def _require_bundle(bundle: dict[str, Any], kind: str) -> dict[str, Any]:
    if bundle.get("bundle_version") != 1 or bundle.get("kind") != kind:
        raise PortableBundleError(f"expected portable {kind} bundle version 1")
    return bundle


def _definition(bundle: dict[str, Any]) -> dict[str, Any]:
    version = bundle.get("world_version")
    definition = version.get("definition") if isinstance(version, dict) else None
    if not isinstance(definition, dict):
        raise PortableBundleError("portable bundle is missing world_version.definition")
    return definition


def _validate_turns(turns_payload: Any) -> None:
    if not isinstance(turns_payload, list):
        raise PortableBundleError("run bundle turns must be an array")
    request_ids: set[str] = set()
    sequences: set[int] = set()
    ids: set[str] = set()
    for item in turns_payload:
        if not isinstance(item, dict):
            raise PortableBundleError("each portable turn must be an object")
        turn_id = str(item.get("id") or "")
        request_id = str(item.get("request_id") or "")
        if not turn_id or turn_id in ids:
            raise PortableBundleError("portable turns contain a duplicate or missing id")
        if not request_id or request_id in request_ids:
            raise PortableBundleError("portable turns contain a duplicate or missing request_id")
        sequence = item.get("sequence")
        if not isinstance(sequence, int) or sequence < 0 or sequence in sequences:
            raise PortableBundleError("portable turns contain an invalid or duplicate sequence")
        ids.add(turn_id)
        request_ids.add(request_id)
        sequences.add(sequence)
    for item in turns_payload:
        target = item.get("rollback_target_id")
        if target is not None and str(target) not in ids:
            raise PortableBundleError("portable rollback target does not exist in the bundle")


def _validate_story_beats(beats_payload: Any) -> None:
    if not isinstance(beats_payload, list):
        raise PortableBundleError("run bundle story_beats must be an array")
    sequences: set[int] = set()
    for item in beats_payload:
        if not isinstance(item, dict) or not isinstance(item.get("content"), dict):
            raise PortableBundleError("each portable story beat must contain object content")
        sequence = item.get("sequence")
        if not isinstance(sequence, int) or sequence < 0 or sequence in sequences:
            raise PortableBundleError("portable story beats contain an invalid or duplicate sequence")
        if not str(item.get("kind") or "").strip():
            raise PortableBundleError("portable story beat kind is required")
        sequences.add(sequence)
