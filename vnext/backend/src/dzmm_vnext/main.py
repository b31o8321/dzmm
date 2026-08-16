from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from . import API_VERSION, APP_NAME
from .config import Settings
from .contracts import contract_manifest
from .db import create_engine
from .lifecycle import (
    PurgeConfirmation,
    PurgeConfirmationError,
    WorldLifecycle,
    WorldNotFoundError,
    integrity_scan,
)
from .model_profiles import ModelProber, ModelProfileInput, ModelProfileService, NarrationError
from .turns import (
    RevisionConflictError,
    RunNotFoundError,
    TurnCoordinator,
    TurnIdempotencyConflictError,
    TurnInput,
    TurnResult,
)
from .worlds import (
    ComposeWorldInput,
    DomainValidationError,
    IdempotencyConflictError,
    WorldComposer,
)


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
        app.state.turn_coordinator = TurnCoordinator(app.state.sessions)
        app.state.model_profiles = ModelProfileService(app.state.sessions)
        app.state.model_prober = ModelProber()
        app.state.world_lifecycle = WorldLifecycle(app.state.sessions)
        try:
            yield
        finally:
            await app.state.engine.dispose()

    app = FastAPI(title="DZMM Next Preview", version="0.1.0", lifespan=lifespan)

    @app.get("/health")
    async def health() -> dict[str, object]:
        async with app.state.engine.connect() as connection:
            foreign_keys = (await connection.execute(text("PRAGMA foreign_keys"))).scalar_one()
        return {
            "app": APP_NAME,
            "api_version": API_VERSION,
            "contract": app.state.contracts,
            "storage": "isolated",
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

    @app.get("/api/v2/runs/{run_id}")
    async def get_run(run_id: str) -> dict[str, object]:
        snapshot = await app.state.world_composer.load_run(run_id)
        if snapshot is None:
            raise HTTPException(status_code=404, detail="run not found")
        return snapshot.model_dump(mode="json")

    @app.post("/api/v2/worlds/{world_id}:archive")
    async def archive_world(world_id: str) -> dict[str, str]:
        try:
            status = await app.state.world_lifecycle.archive(world_id)
        except WorldNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        return {"world_id": world_id, "status": status}

    @app.get("/api/v2/worlds/{world_id}/purge-manifest")
    async def world_purge_manifest(world_id: str) -> dict[str, object]:
        try:
            return (await app.state.world_lifecycle.manifest(world_id)).model_dump(mode="json")
        except WorldNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @app.delete("/api/v2/worlds/{world_id}")
    async def purge_world(world_id: str, payload: PurgeConfirmation) -> dict[str, object]:
        try:
            return (
                await app.state.world_lifecycle.purge(world_id, payload.confirmation_token)
            ).model_dump(mode="json")
        except WorldNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except PurgeConfirmationError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.get("/api/v2/integrity")
    async def get_integrity() -> dict[str, object]:
        orphans = await integrity_scan(app.state.sessions)
        return {"orphans": orphans, "clean": not any(orphans.values())}

    async def play_turn(run_id: str, payload: TurnInput) -> TurnResult:
        try:
            return await app.state.turn_coordinator.play(run_id, payload)
        except RunNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except NarrationError as error:
            raise HTTPException(status_code=502, detail=str(error)) from error
        except (RevisionConflictError, TurnIdempotencyConflictError) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.post("/api/v2/runs/{run_id}/turns")
    async def create_turn(run_id: str, payload: TurnInput) -> JSONResponse:
        result = await play_turn(run_id, payload)
        return JSONResponse(
            status_code=201 if result.created else 200,
            content=result.model_dump(mode="json"),
        )

    @app.post("/api/v2/runs/{run_id}/turns:stream")
    async def stream_turn(run_id: str, payload: TurnInput) -> StreamingResponse:
        result = await play_turn(run_id, payload)

        async def events():
            event_id = result.sequence * 100
            yield _sse(event_id, "turn_started", {"revision": result.before_revision})
            yield _sse(event_id + 1, "narrative_delta", {"text": result.narrative})
            for index, outcome in enumerate(result.outcomes, start=2):
                yield _sse(event_id + index, "command_applied", outcome)
            yield _sse(
                event_id + len(result.outcomes) + 2,
                "turn_completed",
                {
                    "turn_id": result.turn_id,
                    "revision": result.after_revision,
                    "created": result.created,
                },
            )

        return StreamingResponse(events(), media_type="text/event-stream")

    @app.post("/api/v2/model-profiles")
    async def create_model_profile(payload: ModelProfileInput) -> JSONResponse:
        try:
            profile = await app.state.model_profiles.create(payload)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return JSONResponse(status_code=201, content=profile.model_dump(mode="json"))

    @app.post("/api/v2/model-profiles/{profile_id}:probe")
    async def probe_model_profile(profile_id: str) -> dict[str, object]:
        profile = await app.state.model_profiles.get(profile_id)
        if profile is None:
            raise HTTPException(status_code=404, detail="model profile not found")
        return (await app.state.model_prober.probe(profile)).model_dump(mode="json")

    return app


app = create_app()


def _sse(event_id: int, event_type: str, payload: dict[str, Any]) -> str:
    import json

    return f"id: {event_id}\nevent: {event_type}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
