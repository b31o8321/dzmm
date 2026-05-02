import pytest
from dzmm.db.base import init_db, get_engine, async_session
from dzmm.db.models import (
    Character, ModelConfig, Session as GameSession, World,
)
from dzmm.service.state_apply._impl import apply_tags
from dzmm.parsing.events import TagComplete


@pytest.fixture
async def db(tmp_path):
    engine = get_engine(f"sqlite+aiosqlite:///{tmp_path}/d.db")
    await init_db(engine)
    SM = async_session(engine)
    async with SM() as s:
        world = World(name="W", content_md="x", style="dark")
        char = Character(world=world, name="C", profile_md="y", base_stats_json="{}")
        cfg = ModelConfig(name="m", type="ollama", base_url="http://localhost:11434", model_name="q")
        s.add_all([world, char, cfg])
        await s.flush()
        sess = GameSession(name="r", world_id=world.id, character_id=char.id,
                           gm_model_config_id=cfg.id, summarizer_model_config_id=cfg.id)
        s.add(sess)
        await s.commit()
        yield SM, sess.id
    await engine.dispose()


async def test_doom_tag_increases_score(db):
    SM, sid = db
    async with SM() as s:
        await apply_tags(s, sid, 1, [TagComplete(name="doom", attrs={"delta": "+15"}, content="")])
        await s.commit()
    async with SM() as s:
        sess = await s.get(GameSession, sid)
        assert sess.doom_score == 15


async def test_doom_tag_decreases_score(db):
    SM, sid = db
    async with SM() as s:
        sess = await s.get(GameSession, sid)
        sess.doom_score = 30
        await s.commit()
    async with SM() as s:
        await apply_tags(s, sid, 2, [TagComplete(name="doom", attrs={"delta": "-10"}, content="")])
        await s.commit()
    async with SM() as s:
        sess = await s.get(GameSession, sid)
        assert sess.doom_score == 20


async def test_doom_score_never_below_zero(db):
    SM, sid = db
    async with SM() as s:
        await apply_tags(s, sid, 1, [TagComplete(name="doom", attrs={"delta": "-50"}, content="")])
        await s.commit()
    async with SM() as s:
        sess = await s.get(GameSession, sid)
        assert sess.doom_score == 0


async def test_doom_score_capped_at_100(db):
    SM, sid = db
    async with SM() as s:
        sess = await s.get(GameSession, sid)
        sess.doom_score = 95
        await s.commit()
    async with SM() as s:
        await apply_tags(s, sid, 1, [TagComplete(name="doom", attrs={"delta": "+20"}, content="")])
        await s.commit()
    async with SM() as s:
        sess = await s.get(GameSession, sid)
        assert sess.doom_score == 100
