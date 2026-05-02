import asyncio
import pytest
from httpx import ASGITransport, AsyncClient

from dzmm.db.base import init_db, get_engine, async_session
from dzmm.main import create_app


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
async def client(tmp_path):
    db_url = f"sqlite+aiosqlite:///{tmp_path}/t.db"
    engine = get_engine(db_url)
    await init_db(engine)
    session_maker = async_session(engine)
    app = create_app(session_maker)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    await engine.dispose()
