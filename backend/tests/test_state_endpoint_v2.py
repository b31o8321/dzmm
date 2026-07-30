"""Tests for the v0.15 extended GET /sessions/{id}/state endpoint.

Verifies that the new fields (attributes, vitals, skills, inventory_v2,
equipment, combat_order, recent_resolutions) are present and correctly
shaped in the response, and that existing fields still work.
"""
import json
import pytest
from httpx import ASGITransport, AsyncClient

from dzmm.db.base import init_db, get_engine, async_session
from dzmm.main import create_app


@pytest.fixture
async def app(tmp_path):
    db_url = f"sqlite+aiosqlite:///{tmp_path}/v2test.db"
    engine = get_engine(db_url)
    await init_db(engine)
    session_maker = async_session(engine)
    app = create_app(session_maker)
    app.state.session_maker = session_maker
    yield app
    await engine.dispose()


@pytest.fixture
async def http(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def _make_session(http) -> int:
    r = await http.post("/worlds", json={"name": "W", "content_md": "x", "style": "dark"})
    wid = r.json()["id"]
    r = await http.post("/characters", json={
        "world_id": wid, "name": "Hero", "profile_md": "brave",
        "base_stats_json": '{"hp": 25, "sanity": 40}',
    })
    cid = r.json()["id"]
    r = await http.post("/model_configs", json={
        "name": "local", "type": "ollama",
        "base_url": "http://localhost:11434", "model_name": "qwen2.5:7b",
    })
    mcid = r.json()["id"]
    r = await http.post("/sessions", json={
        "name": "test", "world_id": wid, "character_id": cid,
        "gm_model_config_id": mcid, "summarizer_model_config_id": mcid,
    })
    assert r.status_code == 200, r.text
    return r.json()["id"]


async def test_state_v2_attributes_present(http):
    """GET /state must include 'attributes' with all 6 D&D stats."""
    sid = await _make_session(http)
    r = await http.get(f"/sessions/{sid}/state")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "attributes" in body
    attrs = body["attributes"]
    for key in ("strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma"):
        assert key in attrs, f"Missing attribute: {key}"
        assert isinstance(attrs[key], int)


async def test_state_v2_vitals_present(http):
    """GET /state must include 'vitals' with hp/sanity/stamina + their maxes."""
    sid = await _make_session(http)
    r = await http.get(f"/sessions/{sid}/state")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "vitals" in body
    vitals = body["vitals"]
    for key in ("hp", "max_hp", "sanity", "max_sanity", "stamina", "max_stamina"):
        assert key in vitals, f"Missing vital: {key}"
        assert isinstance(vitals[key], int)
    # max values must be positive
    assert vitals["max_hp"] > 0
    assert vitals["max_sanity"] > 0
    assert vitals["max_stamina"] > 0


async def test_state_v2_skills_and_inventory_v2_present(http):
    """GET /state must include 'skills' (dict) and 'inventory_v2' (list)."""
    sid = await _make_session(http)
    r = await http.get(f"/sessions/{sid}/state")
    assert r.status_code == 200, r.text
    body = r.json()
    # skills is a dict (may be empty on a fresh character)
    assert "skills" in body
    assert isinstance(body["skills"], dict)
    # inventory_v2 is a list (empty on a fresh character)
    assert "inventory_v2" in body
    assert isinstance(body["inventory_v2"], list)


async def test_state_v2_combat_order_and_resolutions(http, app):
    """GET /state must include combat_order and recent_resolutions from Session JSON columns."""
    from dzmm.db.models import Session as GameSession

    sid = await _make_session(http)

    # Seed combat_order and pending_resolutions_json on the Session row
    async with app.state.session_maker() as s:
        sess = await s.get(GameSession, sid)
        sess.combat_order_json = json.dumps([
            {"kind": "pc", "id": 1, "name": "Hero", "initiative_total": 18},
            {"kind": "npc", "id": 7, "name": "Goblin", "initiative_total": 11},
        ])
        sess.pending_resolutions_json = json.dumps([
            {"turn": 1, "kind": "dice", "input": {"expression": "2d6"}, "result": {"total": 9}},
            {"turn": 2, "kind": "skill", "input": {"skill_name": "潜行", "dc": 14},
             "result": {"roll": 18, "success": True}},
        ])
        await s.commit()

    r = await http.get(f"/sessions/{sid}/state")
    assert r.status_code == 200, r.text
    body = r.json()

    # combat_order
    co = body.get("combat_order", [])
    assert len(co) == 2
    assert co[0]["name"] == "Hero"
    assert co[0]["initiative_total"] == 18

    # recent_resolutions — last 5 entries
    rr = body.get("recent_resolutions", [])
    assert len(rr) == 2
    assert rr[0]["kind"] == "dice"
    assert rr[1]["kind"] == "skill"
