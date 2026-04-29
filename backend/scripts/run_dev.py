"""Start the FastAPI app for local development.

Usage:
    cd backend && python scripts/run_dev.py

Environment overrides (also useful for LAN access from a phone):
    DZMM_HOST=0.0.0.0 python scripts/run_dev.py
    DZMM_PORT=9000    python scripts/run_dev.py
"""
import asyncio
import os

import uvicorn

from dzmm.logging_config import setup_logging
from dzmm.main import build_default_app


async def main():
    setup_logging()
    host = os.environ.get("DZMM_HOST", "127.0.0.1")
    port = int(os.environ.get("DZMM_PORT", "8765"))
    app = await build_default_app()
    config = uvicorn.Config(app, host=host, port=port, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()


if __name__ == "__main__":
    asyncio.run(main())
