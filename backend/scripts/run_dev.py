"""Start the FastAPI app for local development.

Usage:
    cd backend && python scripts/run_dev.py
"""
import asyncio

import uvicorn

from dzmm.logging_config import setup_logging
from dzmm.main import build_default_app


async def main():
    setup_logging()
    app = await build_default_app()
    config = uvicorn.Config(app, host="127.0.0.1", port=8765, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()


if __name__ == "__main__":
    asyncio.run(main())
