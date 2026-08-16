from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import text

from . import API_VERSION, APP_NAME
from .config import Settings
from .contracts import contract_manifest
from .db import create_engine


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        resolved_settings.ensure_layout()
        app.state.settings = resolved_settings
        app.state.contracts = contract_manifest()
        app.state.engine = create_engine(resolved_settings)
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

    return app


app = create_app()
