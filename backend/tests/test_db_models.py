import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.db.base import init_db, get_engine, async_session
from dzmm.db.models import World, Character, Session as GameSession, Message, ModelConfig


@pytest.fixture
async def db(tmp_path):
    db_path = tmp_path / "test.db"
    engine = get_engine(f"sqlite+aiosqlite:///{db_path}")
    await init_db(engine)
    async with async_session(engine)() as s:
        yield s
    await engine.dispose()


async def test_create_world_and_character(db: AsyncSession):
    world = World(name="Cyberpunk", content_md="Neon city.", style="dark")
    db.add(world)
    await db.flush()

    char = Character(world_id=world.id, name="Riku", profile_md="Ex-corp runner.",
                     base_stats_json='{"hp":20,"sanity":15}')
    db.add(char)
    await db.commit()

    assert world.id is not None
    assert char.world_id == world.id


async def test_create_session_with_messages(db: AsyncSession):
    world = World(name="W", content_md="x", style="realistic")
    char = Character(world=world, name="C", profile_md="y", base_stats_json="{}")
    cfg = ModelConfig(name="local", type="ollama", base_url="http://localhost:11434",
                      model_name="qwen2.5:7b")
    db.add_all([world, char, cfg])
    await db.flush()

    sess = GameSession(name="Run 1", world_id=world.id, character_id=char.id,
                       gm_model_config_id=cfg.id, summarizer_model_config_id=cfg.id,
                       schema_version=1)
    db.add(sess)
    await db.flush()

    db.add(Message(session_id=sess.id, role="user", content="look around", turn=1))
    db.add(Message(session_id=sess.id, role="assistant",
                   content="<narrative>The street is empty.</narrative>", turn=1))
    await db.commit()
