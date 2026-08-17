from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from . import API_VERSION, APP_NAME
from .config import Settings
from .content import (
    ContentNotFoundError,
    ContentService,
    LorebookPromotionInput,
    LorebookSelectionInput,
    SillyTavernImportInput,
)
from .contracts import contract_manifest
from .db import create_engine
from .lifecycle import (
    PurgeConfirmation,
    PurgeConfirmationError,
    WorldLifecycle,
    WorldNotFoundError,
    WorldVersionConflictError,
    WorldVersionInput,
    integrity_scan,
)
from .model_profiles import ModelProber, ModelProfileInput, ModelProfileService, NarrationError
from .pairing import (
    PairingCompletionInput,
    PairingError,
    PairingRequestInput,
    PairingService,
)
from .turns import (
    ChoiceTurnInput,
    RevisionConflictError,
    RunNotFoundError,
    TurnCoordinator,
    TurnIdempotencyConflictError,
    TurnInput,
    TurnResult,
    TurnRollbackInput,
)
from .world_templates import fog_harbor_template
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
        app.state.content = ContentService(app.state.sessions)
        app.state.pairing = PairingService(app.state.sessions)
        try:
            yield
        finally:
            await app.state.engine.dispose()

    app = FastAPI(title="DZMM Next Preview", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"^(http://(127\.0\.0\.1|localhost):\d+|https://tauri\.localhost)$",
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["authorization", "content-type"],
    )

    @app.middleware("http")
    async def restrict_lan_to_mobile_gameplay(request: Request, call_next):
        if (
            resolved_settings.allow_lan_gameplay
            and not _is_loopback(request)
            and not request.url.path.startswith("/api/v2/mobile/")
        ):
            return JSONResponse(
                status_code=403,
                content={"detail": "LAN Host only exposes paired mobile gameplay endpoints"},
            )
        return await call_next(request)

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

    @app.get("/api/v2/host/capabilities")
    async def host_capabilities() -> dict[str, object]:
        return {
            "api_version": API_VERSION,
            "mobile": {
                "pairing": "pin_approval",
                "capabilities": ["gameplay"],
                "lan_gameplay_enabled": resolved_settings.allow_lan_gameplay,
            },
        }

    @app.post("/api/v2/mobile/pairing-requests")
    async def create_pairing_request(payload: PairingRequestInput) -> dict[str, object]:
        return (await app.state.pairing.request(payload)).model_dump(mode="json")

    @app.get("/api/v2/host/pairing-requests")
    async def list_pairing_requests(request: Request) -> list[dict[str, object]]:
        _require_loopback_host(request)
        return [item.model_dump(mode="json") for item in await app.state.pairing.pending()]

    @app.post("/api/v2/host/pairing-requests/{request_id}:approve")
    async def approve_pairing_request(request_id: str, request: Request) -> dict[str, str]:
        _require_loopback_host(request)
        try:
            await app.state.pairing.approve(request_id)
        except PairingError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return {"request_id": request_id, "status": "approved"}

    @app.post("/api/v2/mobile/pairing-requests/{request_id}:complete")
    async def complete_pairing_request(
        request_id: str, payload: PairingCompletionInput
    ) -> dict[str, object]:
        try:
            return (await app.state.pairing.complete(request_id, payload)).model_dump()
        except PairingError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.get("/api/v2/mobile/session")
    async def mobile_session(authorization: str | None = Header(default=None)) -> dict[str, object]:
        return (await _mobile_device(app, authorization)).model_dump()

    @app.get("/api/v2/mobile/runs/{run_id}")
    async def get_mobile_run(
        run_id: str, authorization: str | None = Header(default=None)
    ) -> dict[str, object]:
        await _mobile_device(app, authorization)
        snapshot = await app.state.world_composer.load_run(run_id)
        if snapshot is None:
            raise HTTPException(status_code=404, detail="run not found")
        return snapshot.model_dump(mode="json")

    @app.post("/api/v2/mobile/runs/{run_id}/turns:stream")
    async def stream_mobile_turn(
        run_id: str, payload: TurnInput, authorization: str | None = Header(default=None)
    ) -> StreamingResponse:
        await _mobile_device(app, authorization)

        async def events():
            event_id = 1
            async for event_type, event_payload in app.state.turn_coordinator.stream(run_id, payload):
                yield _sse(event_id, event_type, event_payload)
                event_id += 1

        return StreamingResponse(events(), media_type="text/event-stream")

    @app.post("/api/v2/mobile/runs/{run_id}/choices")
    async def choose_mobile_turn(
        run_id: str, payload: ChoiceTurnInput, authorization: str | None = Header(default=None)
    ) -> JSONResponse:
        await _mobile_device(app, authorization)
        result = await play_choice(run_id, payload)
        return JSONResponse(
            status_code=201 if result.created else 200,
            content=result.model_dump(mode="json"),
        )

    @app.post("/api/v2/host/mobile-devices/{device_id}:revoke")
    async def revoke_mobile_device(device_id: str, request: Request) -> dict[str, str]:
        _require_loopback_host(request)
        try:
            await app.state.pairing.revoke(device_id)
        except PairingError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        return {"device_id": device_id, "status": "revoked"}

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

    @app.get("/api/v2/world-templates/fog-harbor")
    async def get_fog_harbor_template() -> dict[str, object]:
        return fog_harbor_template()

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

    @app.get("/api/v2/worlds/{world_id}")
    async def get_world(world_id: str) -> dict[str, object]:
        try:
            return (await app.state.world_lifecycle.get_world(world_id)).model_dump(mode="json")
        except WorldNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @app.post("/api/v2/worlds/{world_id}/versions")
    async def create_world_version(
        world_id: str, payload: WorldVersionInput
    ) -> dict[str, object]:
        try:
            return (
                await app.state.world_lifecycle.create_version(world_id, payload)
            ).model_dump(mode="json")
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
            return (
                await app.state.world_lifecycle.purge(world_id, payload)
            ).model_dump(mode="json")
        except WorldNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except PurgeConfirmationError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.get("/api/v2/integrity")
    async def get_integrity() -> dict[str, object]:
        orphans = await integrity_scan(app.state.sessions)
        return {"orphans": orphans, "clean": not any(orphans.values())}

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
            return (
                await app.state.content.select_lorebook(world_version_id, payload)
            ).model_dump(mode="json")
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
            return await app.state.content.export_character_card(world_version_id, character_card_id)
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
        try:
            return await app.state.turn_coordinator.play(run_id, payload)
        except RunNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except NarrationError as error:
            raise HTTPException(status_code=502, detail=str(error)) from error
        except (RevisionConflictError, TurnIdempotencyConflictError) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    async def play_rollback(run_id: str, payload: TurnRollbackInput) -> TurnResult:
        try:
            return await app.state.turn_coordinator.rollback(run_id, payload)
        except RunNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except (RevisionConflictError, TurnIdempotencyConflictError) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    async def play_choice(run_id: str, payload: ChoiceTurnInput) -> TurnResult:
        try:
            return await app.state.turn_coordinator.play_choice(run_id, payload)
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

    @app.post("/api/v2/runs/{run_id}/choices")
    async def choose_turn(run_id: str, payload: ChoiceTurnInput) -> JSONResponse:
        result = await play_choice(run_id, payload)
        return JSONResponse(
            status_code=201 if result.created else 200,
            content=result.model_dump(mode="json"),
        )

    @app.post("/api/v2/runs/{run_id}/rollbacks")
    async def rollback_turn(run_id: str, payload: TurnRollbackInput) -> JSONResponse:
        result = await play_rollback(run_id, payload)
        return JSONResponse(
            status_code=201 if result.created else 200,
            content=result.model_dump(mode="json"),
        )

    @app.post("/api/v2/runs/{run_id}/turns:stream")
    async def stream_turn(run_id: str, payload: TurnInput) -> StreamingResponse:
        async def events():
            event_id = 1
            async for event_type, event_payload in app.state.turn_coordinator.stream(run_id, payload):
                yield _sse(event_id, event_type, event_payload)
                event_id += 1

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


def _require_loopback_host(request: Request) -> None:
    if not _is_loopback(request):
        raise HTTPException(status_code=403, detail="host control requires a loopback connection")


def _is_loopback(request: Request) -> bool:
    client = request.client.host if request.client else ""
    return client in {"127.0.0.1", "::1", "testclient"}


def _bearer_token(authorization: str | None) -> str:
    prefix = "Bearer "
    if authorization is None or not authorization.startswith(prefix):
        raise HTTPException(status_code=401, detail="mobile bearer token is required")
    return authorization.removeprefix(prefix)


async def _mobile_device(app: FastAPI, authorization: str | None):
    try:
        device = await app.state.pairing.authenticate(_bearer_token(authorization))
    except PairingError as error:
        raise HTTPException(status_code=401, detail=str(error)) from error
    if "gameplay" not in device.capabilities:
        raise HTTPException(status_code=403, detail="mobile device lacks gameplay capability")
    return device
