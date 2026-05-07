"""Tests for the Faction system (v0.9 T7).

Uses the same fixtures as test_api.py (app / http).
"""
import pytest
from httpx import ASGITransport, AsyncClient

from dzmm.db.base import init_db, get_engine, async_session
from dzmm.main import create_app


# ── fixtures (mirrors test_api.py) ────────────────────────────────────────

@pytest.fixture
async def app(tmp_path):
    db_url = f"sqlite+aiosqlite:///{tmp_path}/t_factions.db"
    engine = get_engine(db_url)
    await init_db(engine)
    SessionMaker = async_session(engine)
    app = create_app(SessionMaker)
    app.state.session_maker = SessionMaker
    yield app
    await engine.dispose()


@pytest.fixture
async def http(app):
    async with AsyncClient(transport=ASGITransport(app=app),
                           base_url="http://test") as c:
        yield c


async def _make_session(http) -> int:
    r = await http.post("/worlds", json={"name": "W", "content_md": "x", "style": "dark"})
    wid = r.json()["id"]
    r = await http.post("/characters", json={
        "world_id": wid, "name": "C", "profile_md": "y",
        "base_stats_json": '{"hp":20}',
    })
    cid = r.json()["id"]
    r = await http.post("/model_configs", json={
        "name": "local", "type": "ollama",
        "base_url": "http://localhost:11434", "model_name": "qwen2.5:7b",
    })
    mcid = r.json()["id"]
    r = await http.post("/sessions", json={
        "name": "run1", "world_id": wid, "character_id": cid,
        "gm_model_config_id": mcid, "summarizer_model_config_id": mcid,
    })
    return r.json()["id"]


# ── tests ─────────────────────────────────────────────────────────────────

async def test_list_factions_empty(http):
    """New session has no factions."""
    sid = await _make_session(http)
    r = await http.get(f"/sessions/{sid}/factions")
    assert r.status_code == 200
    assert r.json() == []


async def test_faction_create_then_change(http, app):
    """End-to-end: apply handlers directly, then verify via API."""
    sid = await _make_session(http)
    SessionMaker = app.state.session_maker
    from dzmm.service.state_apply.factions import _apply_faction_create, _apply_faction_change

    async with SessionMaker() as s:
        await _apply_faction_create(
            s, sid,
            {"name": "暗影教团", "ideology": "颠覆王权"},
            "300年前由先知建立的秘密组织。",
        )
        await s.commit()

    r = await http.get(f"/sessions/{sid}/factions")
    assert r.status_code == 200
    factions = r.json()
    assert len(factions) == 1
    f = factions[0]
    assert f["name"] == "暗影教团"
    assert f["ideology"] == "颠覆王权"
    assert f["pc_reputation"] == 0

    # Apply rep_delta
    async with SessionMaker() as s:
        await _apply_faction_change(s, sid, {"name": "暗影教团", "rep_delta": "20"})
        await s.commit()

    r2 = await http.get(f"/sessions/{sid}/factions")
    assert r2.status_code == 200
    updated = next(f for f in r2.json() if f["name"] == "暗影教团")
    assert updated["pc_reputation"] == 20


async def test_faction_create_idempotent(app):
    """Same name twice should not create a duplicate."""
    from dzmm.db.base import init_db, get_engine, async_session as mk_async_session
    from dzmm.db.models import Faction
    from sqlalchemy import select

    SessionMaker = app.state.session_maker
    from dzmm.service.state_apply.factions import _apply_faction_create

    # We need a valid session_id — grab from app's DB by using a dummy session_id=9999
    # (no FK enforcement in SQLite by default, so this works for a unit-style test).
    sid = 9999
    async with SessionMaker() as s:
        await _apply_faction_create(s, sid, {"name": "光明教会", "ideology": "守护秩序"}, "白色圣堂")
        await s.commit()

    async with SessionMaker() as s:
        await _apply_faction_create(s, sid, {"name": "光明教会", "ideology": "守护秩序"}, "重复")
        await s.commit()

    async with SessionMaker() as s:
        rows = (await s.execute(
            select(Faction).where(Faction.session_id == sid, Faction.name == "光明教会")
        )).scalars().all()
        assert len(rows) == 1, "duplicate faction should not be created"


async def test_faction_rep_clamp(app):
    """pc_reputation should be clamped to [-100, 100]."""
    from dzmm.service.state_apply.factions import _apply_faction_create, _apply_faction_change
    from dzmm.db.models import Faction
    from sqlalchemy import select

    SessionMaker = app.state.session_maker
    sid = 8888

    async with SessionMaker() as s:
        await _apply_faction_create(s, sid, {"name": "邪教"}, "")
        await s.commit()

    # Apply a very large delta that would exceed +100
    async with SessionMaker() as s:
        await _apply_faction_change(s, sid, {"name": "邪教", "rep_delta": "200"})
        await s.commit()

    async with SessionMaker() as s:
        f = (await s.execute(
            select(Faction).where(Faction.session_id == sid, Faction.name == "邪教")
        )).scalar_one()
        assert f.pc_reputation == 100

    # Apply a large negative delta
    async with SessionMaker() as s:
        await _apply_faction_change(s, sid, {"name": "邪教", "rep_delta": "-300"})
        await s.commit()

    async with SessionMaker() as s:
        f = (await s.execute(
            select(Faction).where(Faction.session_id == sid, Faction.name == "邪教")
        )).scalar_one()
        assert f.pc_reputation == -100


async def test_faction_create_hostile_allied_json(app):
    """hostile_to and allied_to JSON arrays are stored and returned correctly."""
    from dzmm.service.state_apply.factions import _apply_faction_create
    from dzmm.db.models import Faction
    from sqlalchemy import select

    SessionMaker = app.state.session_maker
    sid = 7777

    async with SessionMaker() as s:
        await _apply_faction_create(
            s, sid,
            {
                "name": "北方联盟",
                "ideology": "扩张领土",
                "hostile_to": '["南方帝国"]',
                "allied_to": '["草原部落"]',
            },
            "三国鼎立中的北方势力。",
        )
        await s.commit()

    async with SessionMaker() as s:
        f = (await s.execute(
            select(Faction).where(Faction.session_id == sid, Faction.name == "北方联盟")
        )).scalar_one()
        import json
        assert json.loads(f.hostile_to_json) == ["南方帝国"]
        assert json.loads(f.allied_to_json) == ["草原部落"]
