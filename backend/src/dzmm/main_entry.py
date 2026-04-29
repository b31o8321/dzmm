"""PyInstaller entrypoint. Starts uvicorn synchronously."""
import asyncio
import os
import sys

import uvicorn

from dzmm.logging_config import setup_logging
from dzmm.main import build_default_app


def main():
    setup_logging()
    port = int(os.environ.get('DZMM_PORT', '8765'))
    host = os.environ.get('DZMM_HOST', '127.0.0.1')

    async def run():
        app = await build_default_app()
        config = uvicorn.Config(app, host=host, port=port, log_level='info')
        server = uvicorn.Server(config)
        await server.serve()

    asyncio.run(run())


if __name__ == '__main__':
    sys.exit(main() or 0)
