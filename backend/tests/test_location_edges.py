"""v0.10 T12 — LocationEdge model + tag handler + topology validation."""
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from dzmm.db.base import async_session, get_engine, init_db
from dzmm.db.models import Location, LocationEdge
from dzmm.main import create_app


@pytest.fixture
async def app(tmp_path):
    db_url = f"sqlite+aiosqlite:///{tmp_path}/t_location_edges.db"
    engine = get_engine(db_url)
    await init_db(engine)
    SessionMaker = async_session(engine)
    app = create_app(SessionMaker)
    app.state.session_maker = SessionMaker
    yield app
    await engine.dispose()


@pytest.fixture
async def http(app):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


@pytest.mark.asyncio
async def test_location_edge_unique_per_triple(app):
    SessionMaker = app.state.session_maker
    async with SessionMaker() as s:
        s.add_all([
            Location(session_id=1, name="修道院"),
            Location(session_id=1, name="实验室"),
        ])
        await s.flush()
        from_id = (await s.execute(
            select(Location.id).where(Location.name == "修道院")
        )).scalar_one()
        to_id = (await s.execute(
            select(Location.id).where(Location.name == "实验室")
        )).scalar_one()
        s.add(LocationEdge(
            session_id=1, from_loc_id=from_id, to_loc_id=to_id,
            relation="contains",
            description="实验室位于修道院地下三层",
        ))
        await s.commit()
        s.add(LocationEdge(
            session_id=1, from_loc_id=from_id, to_loc_id=to_id,
            relation="contains", description="重复",
        ))
        with pytest.raises(Exception):
            await s.commit()


@pytest.mark.asyncio
async def test_apply_location_edge_creates_locations_if_missing(app):
    from dzmm.service.state_apply.location_edge import _apply_location_edge

    SessionMaker = app.state.session_maker
    async with SessionMaker() as s:
        await _apply_location_edge(
            s, session_id=1,
            attrs={
                "from": "修道院", "to": "实验室",
                "relation": "contains",
                "description": "实验室位于修道院地下三层",
            },
            current_turn=2,
        )
        await s.commit()
        locs = (await s.execute(select(Location))).scalars().all()
        edges = (await s.execute(select(LocationEdge))).scalars().all()
    assert {location.name for location in locs} == {"修道院", "实验室"}
    assert len(edges) == 1
    assert edges[0].relation == "contains"
    assert edges[0].introduced_turn == 2


@pytest.mark.asyncio
async def test_apply_location_edge_idempotent(app):
    from dzmm.service.state_apply.location_edge import _apply_location_edge

    SessionMaker = app.state.session_maker
    async with SessionMaker() as s:
        for _ in range(3):
            await _apply_location_edge(
                s, session_id=1,
                attrs={"from": "A", "to": "B", "relation": "adjacent"},
                current_turn=1,
            )
        await s.commit()
        edges = (await s.execute(select(LocationEdge))).scalars().all()
    assert len(edges) == 1


@pytest.mark.asyncio
async def test_apply_location_edge_invalid_relation_skipped(app):
    from dzmm.service.state_apply.location_edge import _apply_location_edge

    SessionMaker = app.state.session_maker
    async with SessionMaker() as s:
        await _apply_location_edge(
            s, session_id=1,
            attrs={"from": "A", "to": "B", "relation": "tEleporT"},
            current_turn=1,
        )
        await s.commit()
        edges = (await s.execute(select(LocationEdge))).scalars().all()
    assert edges == []


@pytest.mark.asyncio
async def test_location_enter_warns_when_no_known_path(app):
    """从「实验室」直接 enter「天台」（无 edge）→ 切 is_current 但返回警告字符串。"""
    from dzmm.db.models import Character, ModelConfig, Session as GameSession, World
    from dzmm.service.state_apply.location import _apply_location_enter

    SessionMaker = app.state.session_maker
    async with SessionMaker() as s:
        s.add_all([
            World(name="W", content_md=""),
            Character(world_id=1, name="C", profile_md="", base_stats_json="{}"),
            ModelConfig(name="m", type="ollama", base_url="x", model_name="y"),
        ])
        await s.flush()
        s.add(GameSession(
            id=1, name="s", world_id=1, character_id=1,
            gm_model_config_id=1, summarizer_model_config_id=1,
        ))
        s.add(Location(
            session_id=1, name="实验室", is_current=True,
            first_visited_turn=1, last_visited_turn=1,
        ))
        await s.commit()

        warning = await _apply_location_enter(
            s, session_id=1, current_turn=2,
            attrs={"name": "天台", "description": "雨水"},
            content="",
        )
        await s.commit()
        locs = (await s.execute(select(Location))).scalars().all()
    by_name = {location.name: location for location in locs}
    assert by_name["天台"].is_current is True
    assert by_name["实验室"].is_current is False
    assert warning is not None
    assert "天台" in warning and "拓扑" in warning


@pytest.mark.asyncio
async def test_location_enter_no_warning_when_edge_exists(app):
    from dzmm.db.models import Character, ModelConfig, Session as GameSession, World
    from dzmm.service.state_apply.location import _apply_location_enter
    from dzmm.service.state_apply.location_edge import _apply_location_edge

    SessionMaker = app.state.session_maker
    async with SessionMaker() as s:
        s.add_all([
            World(name="W", content_md=""),
            Character(world_id=1, name="C", profile_md="", base_stats_json="{}"),
            ModelConfig(name="m", type="ollama", base_url="x", model_name="y"),
        ])
        await s.flush()
        s.add(GameSession(
            id=1, name="s", world_id=1, character_id=1,
            gm_model_config_id=1, summarizer_model_config_id=1,
        ))
        s.add(Location(
            session_id=1, name="实验室", is_current=True,
            first_visited_turn=1, last_visited_turn=1,
        ))
        await s.flush()
        await _apply_location_edge(
            s, session_id=1,
            attrs={"from": "实验室", "to": "走廊", "relation": "adjacent"},
            current_turn=1,
        )
        await s.commit()

        warning = await _apply_location_enter(
            s, session_id=1, current_turn=2,
            attrs={"name": "走廊", "description": "x"},
            content="",
        )
        await s.commit()
    assert warning is None
