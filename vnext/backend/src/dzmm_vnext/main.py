from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from . import API_VERSION, APP_NAME
from .config import Settings
from .contracts import contract_manifest
from .core import (
    AIWorldDraftGenerationError,
    AIWorldDraftInput,
    AIWorldDraftReviewInput,
    AIWorldDraftService,
    ChoiceTurnInput,
    ComposeWorldInput,
    ContentNotFoundError,
    ContentService,
    CreateRunInput,
    DomainValidationError,
    IdempotencyConflictError,
    LorebookPromotionInput,
    LorebookSelectionInput,
    ModelProber,
    ModelProfileConflictError,
    ModelProfileInput,
    ModelProfileService,
    NarrationError,
    PortableBundleError,
    PortableImportInput,
    PortableRunCloneInput,
    PortableService,
    PurgeConfirmation,
    PurgeConfirmationError,
    RevisionConflictError,
    RunModelProfileConflictError,
    RunModelProfileInput,
    RunNotFoundError,
    SillyTavernImportInput,
    TurnCoordinator,
    TurnIdempotencyConflictError,
    TurnInput,
    TurnResult,
    TurnRollbackInput,
    WorldComposer,
    WorldLifecycle,
    WorldNotFoundError,
    WorldVersionConflictError,
    WorldVersionInput,
    diagnostic_snapshot,
    integrity_scan,
    validate_world_draft,
)
from .db import create_engine
from .world_templates import fog_harbor_template


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        resolved_settings.ensure_layout()
        app.state.settings = resolved_settings
        app.state.contracts = contract_manifest()
        app.state.engine = create_engine(resolved_settings)
        app.state.sessions = async_sessionmaker(app.state.engine, expire_on_commit=False)
        app.state.world_composer = WorldComposer(app.state.sessions)
        app.state.portable = PortableService(app.state.sessions, app.state.world_composer)
        app.state.turn_coordinator = TurnCoordinator(app.state.sessions)
        app.state.model_profiles = ModelProfileService(app.state.sessions)
        app.state.ai_world_drafts = AIWorldDraftService(app.state.model_profiles)
        app.state.model_prober = ModelProber()
        app.state.world_lifecycle = WorldLifecycle(app.state.sessions)
        app.state.content = ContentService(app.state.sessions)
        try:
            yield
        finally:
            await app.state.engine.dispose()

    app = FastAPI(title="DZMM Local Host", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=(
            r"^(http://(127\.0\.0\.1|localhost):\d+|"
            r"https?://tauri\.localhost|tauri://localhost)$"
        ),
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["content-type"],
    )

    @app.get("/health")
    async def health() -> dict[str, object]:
        async with app.state.engine.connect() as connection:
            foreign_keys = (await connection.execute(text("PRAGMA foreign_keys"))).scalar_one()
        return {
            "app": APP_NAME,
            "api_version": API_VERSION,
            "contract": app.state.contracts,
            "storage": "local",
            "host": "127.0.0.1",
            "foreign_keys": bool(foreign_keys),
        }

    @app.post("/api/v2/worlds:compose")
    async def compose_world(payload: ComposeWorldInput) -> JSONResponse:
        try:
            result = await app.state.world_composer.compose(payload)
        except DomainValidationError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except IdempotencyConflictError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return JSONResponse(
            status_code=201 if result.created else 200,
            content=result.model_dump(mode="json"),
        )

    @app.post("/api/v2/worlds/{world_id}/runs")
    async def create_run(world_id: str, payload: CreateRunInput) -> JSONResponse:
        try:
            result = await app.state.world_composer.create_run(world_id, payload)
        except DomainValidationError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except IdempotencyConflictError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return JSONResponse(
            status_code=201 if result.created else 200,
            content=result.model_dump(mode="json"),
        )

    @app.post("/api/v2/ai-world-drafts:generate")
    async def generate_ai_world_draft(payload: AIWorldDraftInput) -> dict[str, object]:
        try:
            return (await app.state.ai_world_drafts.generate(payload)).model_dump(mode="json")
        except AIWorldDraftGenerationError as error:
            raise HTTPException(status_code=502, detail=str(error)) from error

    @app.post("/api/v2/ai-world-drafts:validate")
    async def validate_ai_world_draft(payload: AIWorldDraftReviewInput) -> dict[str, object]:
        return validate_world_draft(payload.world_definition, payload.hero).model_dump(mode="json")

    @app.get("/api/v2/world-templates/fog-harbor")
    async def get_fog_harbor_template() -> dict[str, object]:
        return fog_harbor_template()

    @app.get("/api/v2/runs/{run_id}:export")
    async def export_run(run_id: str) -> dict[str, object]:
        bundle = await app.state.portable.export_run(run_id)
        if bundle is None:
            raise HTTPException(status_code=404, detail="run not found")
        return bundle

    @app.get("/api/v2/runs/{run_id}")
    async def get_run(run_id: str) -> dict[str, object]:
        snapshot = await app.state.world_composer.load_run(run_id)
        if snapshot is None:
            raise HTTPException(status_code=404, detail="run not found")
        return snapshot.model_dump(mode="json")

    @app.post("/api/v2/runs:clone")
    async def clone_run(payload: PortableRunCloneInput) -> JSONResponse:
        try:
            result = await app.state.portable.clone_run(payload)
        except (PortableBundleError, DomainValidationError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return JSONResponse(status_code=201, content=result.model_dump(mode="json"))

    @app.get("/api/v2/runs/{run_id}/model-profile")
    async def get_run_model_profile(run_id: str) -> dict[str, str | None]:
        try:
            model_profile_id = await app.state.world_composer.run_model_profile_id(run_id)
        except RunModelProfileConflictError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        return {"run_id": run_id, "model_profile_id": model_profile_id}

    @app.post("/api/v2/runs/{run_id}/model-profile")
    async def set_run_model_profile(run_id: str, payload: RunModelProfileInput) -> dict[str, str]:
        try:
            model_profile_id = await app.state.world_composer.set_run_model_profile(run_id, payload)
        except RunModelProfileConflictError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except DomainValidationError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return {"run_id": run_id, "model_profile_id": model_profile_id}

    @app.post("/api/v2/worlds/{world_id}:archive")
    async def archive_world(world_id: str) -> dict[str, str]:
        try:
            status = await app.state.world_lifecycle.archive(world_id)
        except WorldNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        return {"world_id": world_id, "status": status}

    @app.post("/api/v2/worlds/{world_id}:restore")
    async def restore_world(world_id: str) -> dict[str, str]:
        try:
            status = await app.state.world_lifecycle.restore(world_id)
        except WorldNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        return {"world_id": world_id, "status": status}

    @app.get("/api/v2/worlds")
    async def list_worlds() -> list[dict[str, object]]:
        return [
            world.model_dump(mode="json") for world in await app.state.world_lifecycle.list_worlds()
        ]

    @app.get("/api/v2/worlds/{world_id}:export")
    async def export_world(world_id: str) -> dict[str, object]:
        bundle = await app.state.portable.export_world(world_id)
        if bundle is None:
            raise HTTPException(status_code=404, detail="world not found")
        return bundle

    @app.post("/api/v2/worlds:import")
    async def import_world(payload: PortableImportInput) -> JSONResponse:
        try:
            result = await app.state.portable.import_world(payload)
        except (PortableBundleError, DomainValidationError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return JSONResponse(status_code=201, content=result.model_dump(mode="json"))

    @app.get("/api/v2/worlds/{world_id}")
    async def get_world(world_id: str) -> dict[str, object]:
        try:
            return (await app.state.world_lifecycle.get_world(world_id)).model_dump(mode="json")
        except WorldNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @app.post("/api/v2/worlds/{world_id}/versions")
    async def create_world_version(world_id: str, payload: WorldVersionInput) -> dict[str, object]:
        try:
            return (await app.state.world_lifecycle.create_version(world_id, payload)).model_dump(
                mode="json"
            )
        except WorldNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except WorldVersionConflictError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except DomainValidationError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.get("/api/v2/worlds/{world_id}/purge-manifest")
    async def world_purge_manifest(world_id: str) -> dict[str, object]:
        try:
            return (await app.state.world_lifecycle.manifest(world_id)).model_dump(mode="json")
        except WorldNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @app.delete("/api/v2/worlds/{world_id}")
    async def purge_world(world_id: str, payload: PurgeConfirmation) -> dict[str, object]:
        try:
            return (await app.state.world_lifecycle.purge(world_id, payload)).model_dump(
                mode="json"
            )
        except WorldNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except PurgeConfirmationError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.get("/api/v2/integrity")
    async def get_integrity() -> dict[str, object]:
        orphans = await integrity_scan(app.state.sessions)
        return {"orphans": orphans, "clean": not any(orphans.values())}

    @app.get("/api/v2/diagnostics")
    async def get_diagnostics() -> dict[str, object]:
        return {
            "app": APP_NAME,
            "api_version": API_VERSION,
            "contract": app.state.contracts,
            "storage": "local",
            "database": await diagnostic_snapshot(app.state.sessions),
        }

    @app.post("/api/v2/content/sillytavern:import")
    async def import_sillytavern(payload: SillyTavernImportInput) -> dict[str, object]:
        try:
            return app.state.content.import_sillytavern(payload).model_dump(mode="json")
        except (TypeError, ValueError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.post("/api/v2/world-versions/{world_version_id}/lorebook:select")
    async def select_world_lorebook(
        world_version_id: str, payload: LorebookSelectionInput
    ) -> dict[str, object]:
        try:
            return (await app.state.content.select_lorebook(world_version_id, payload)).model_dump(
                mode="json"
            )
        except ContentNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @app.post("/api/v2/worlds/{world_id}/lorebook/{entry_id}:promote")
    async def promote_world_lorebook_entry(
        world_id: str, entry_id: str, payload: LorebookPromotionInput
    ) -> dict[str, object]:
        try:
            return (
                await app.state.content.promote_lorebook_entry(world_id, entry_id, payload)
            ).model_dump(mode="json")
        except ContentNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.get("/api/v2/world-versions/{world_version_id}/character-cards/{character_card_id}:export")
    async def export_character_card(
        world_version_id: str, character_card_id: str
    ) -> dict[str, object]:
        try:
            return await app.state.content.export_character_card(
                world_version_id, character_card_id
            )
        except ContentNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except TypeError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.get("/api/v2/world-versions/{world_version_id}/lorebook:export")
    async def export_lorebook(world_version_id: str) -> dict[str, object]:
        try:
            return await app.state.content.export_lorebook(world_version_id)
        except ContentNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    async def play_turn(run_id: str, payload: TurnInput) -> TurnResult:
        if not app.state.turn_coordinator.begin_operation(payload.request_id):
            raise HTTPException(status_code=409, detail="operation is already running")
        try:
            return await app.state.turn_coordinator.play(run_id, payload)
        except RunNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except NarrationError as error:
            raise HTTPException(status_code=502, detail=str(error)) from error
        except (RevisionConflictError, TurnIdempotencyConflictError) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        finally:
            app.state.turn_coordinator.finish_operation(payload.request_id)

    async def play_rollback(run_id: str, payload: TurnRollbackInput) -> TurnResult:
        try:
            return await app.state.turn_coordinator.rollback(run_id, payload)
        except RunNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except (RevisionConflictError, TurnIdempotencyConflictError) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    async def play_choice(run_id: str, payload: ChoiceTurnInput) -> TurnResult:
        if not app.state.turn_coordinator.begin_operation(payload.request_id):
            raise HTTPException(status_code=409, detail="operation is already running")
        try:
            return await app.state.turn_coordinator.play_choice(run_id, payload)
        except RunNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except NarrationError as error:
            raise HTTPException(status_code=502, detail=str(error)) from error
        except (RevisionConflictError, TurnIdempotencyConflictError) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        finally:
            app.state.turn_coordinator.finish_operation(payload.request_id)

    @app.post("/api/v2/operations/{request_id}:cancel")
    async def cancel_operation(request_id: str) -> dict[str, object]:
        accepted = (
            app.state.turn_coordinator.cancel_operation(request_id)
            or app.state.ai_world_drafts.cancel_operation(request_id)
        )
        return {
            "request_id": request_id,
            "accepted": accepted,
            "detail": (
                "cancellation accepted; the original Run state will be preserved"
                if accepted
                else "operation is no longer cancellable"
            ),
        }

    @app.post("/api/v2/runs/{run_id}/turns")
    async def create_turn(run_id: str, payload: TurnInput) -> JSONResponse:
        result = await play_turn(run_id, payload)
        return JSONResponse(
            status_code=201 if result.created else 200, content=result.model_dump(mode="json")
        )

    @app.post("/api/v2/runs/{run_id}/choices")
    async def choose_turn(run_id: str, payload: ChoiceTurnInput) -> JSONResponse:
        result = await play_choice(run_id, payload)
        return JSONResponse(
            status_code=201 if result.created else 200, content=result.model_dump(mode="json")
        )

    @app.post("/api/v2/runs/{run_id}/rollbacks")
    async def rollback_turn(run_id: str, payload: TurnRollbackInput) -> JSONResponse:
        result = await play_rollback(run_id, payload)
        return JSONResponse(
            status_code=201 if result.created else 200, content=result.model_dump(mode="json")
        )

    async def stream_turn_events(
        run_id: str,
        payload: TurnInput,
        *,
        planned_choice: bool = False,
        choice_id: str | None = None,
    ) -> StreamingResponse:
        async def events():
            if not app.state.turn_coordinator.begin_operation(payload.request_id):
                yield _sse(
                    1,
                    "turn_failed",
                    {"category": "state", "detail": "operation is already running"},
                )
                return
            event_id = 1
            try:
                async for event_type, event_payload in app.state.turn_coordinator.stream(
                    run_id,
                    payload,
                    planned_choice=planned_choice,
                    choice_id=choice_id,
                ):
                    yield _sse(event_id, event_type, event_payload)
                    event_id += 1
            finally:
                app.state.turn_coordinator.finish_operation(payload.request_id)

        return StreamingResponse(events(), media_type="text/event-stream")

    @app.post("/api/v2/runs/{run_id}/turns:stream")
    async def stream_turn(run_id: str, payload: TurnInput) -> StreamingResponse:
        return await stream_turn_events(run_id, payload)

    @app.post("/api/v2/runs/{run_id}/choices:stream")
    async def stream_choice(run_id: str, payload: ChoiceTurnInput) -> StreamingResponse:
        return await stream_turn_events(
            run_id,
            TurnInput(
                request_id=payload.request_id,
                expected_revision=payload.expected_revision,
                player_input=payload.player_input,
                commands=[
                    {"type": "choose_story_choice", "payload": {"choice_id": payload.choice_id}}
                ],
            ),
            planned_choice=True,
            choice_id=payload.choice_id,
        )

    @app.post("/api/v2/model-profiles")
    async def create_model_profile(payload: ModelProfileInput) -> JSONResponse:
        try:
            profile = await app.state.model_profiles.create(payload)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return JSONResponse(status_code=201, content=profile.model_dump(mode="json"))

    @app.get("/api/v2/model-profiles")
    async def list_model_profiles() -> list[dict[str, object]]:
        return [item.model_dump(mode="json") for item in await app.state.model_profiles.list()]

    @app.put("/api/v2/model-profiles/{profile_id}")
    async def update_model_profile(
        profile_id: str, payload: ModelProfileInput
    ) -> dict[str, object]:
        try:
            return (await app.state.model_profiles.update(profile_id, payload)).model_dump(
                mode="json"
            )
        except ModelProfileConflictError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.post("/api/v2/model-profiles/{profile_id}:default")
    async def set_default_model_profile(profile_id: str) -> dict[str, object]:
        try:
            return (await app.state.model_profiles.set_default(profile_id)).model_dump(mode="json")
        except ModelProfileConflictError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @app.delete("/api/v2/model-profiles/{profile_id}", status_code=204)
    async def delete_model_profile(profile_id: str) -> None:
        try:
            await app.state.model_profiles.delete(profile_id)
        except ModelProfileConflictError as error:
            status = 409 if "used by" in str(error) else 404
            raise HTTPException(status_code=status, detail=str(error)) from error

    @app.post("/api/v2/model-profiles/{profile_id}:probe")
    async def probe_model_profile(profile_id: str) -> dict[str, object]:
        profile = await app.state.model_profiles.get(profile_id)
        if profile is None:
            raise HTTPException(status_code=404, detail="model profile not found")
        return (await app.state.model_prober.probe(profile)).model_dump(mode="json")

    return app


app = create_app()


def _sse(event_id: int, event_type: str, payload: dict[str, Any]) -> str:
    return (
        f"id: {event_id}\nevent: {event_type}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
    )
