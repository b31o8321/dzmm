from contextlib import asynccontextmanager

from httpx import ASGITransport, AsyncClient


@asynccontextmanager
async def app_client(app, host: str = "127.0.0.1"):
    transport = ASGITransport(app=app, client=(host, 43123))
    async with AsyncClient(transport=transport, base_url="http://dzmm.test") as client:
        yield client
