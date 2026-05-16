"""Tests for PATCH /sessions/{session_id}/screenplay (manual outline editor)."""
import json
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from dzmm.db.base import async_session, get_engine, init_db
from dzmm.db.models import (
    Character,
    ModelConfig,
    Screenplay,
    ScreenplayRevision,
    Session as GameSession,
    World,
)
from dzmm.main import create_app
from dzmm.models.client import GenerationParams, Message, ModelClient, StreamChunk, TokenUsage


# ── Stub outliner (matches test_screenplay_service.py style) ────────────────

_STUB_OUTLINE = json.dumps({
    "chapters": [
        {
            "title": "第一章：迷雾",
            "summary": "调查一桩失踪",
            "main_events": ["发现线索 A", "对峙嫌疑人 B"],
            "optional_events": ["搜查老宅"],
            "main_npcs": ["陈子轩"],
        },
    ],
    "main_characters": [
        {"name": "陈子轩", "role": "线人", "description": "中年华人男子", "intro_chapter": 1},
    ],
    "ending": "PC 揭穿黑手党的阴谋",
    "opening_hook": "雨夜的霓虹下，你接到一通电话",
}, ensure_ascii=False)


class StubOutliner(ModelClient):
    name = "stub"

    def __init__(self, output: str = _STUB_OUTLINE):
        self.output = output

    async def stream(
        self, messages: list[Message], params: GenerationParams
    ) -> AsyncIterator[StreamChunk]:
        yield StreamChunk(delta=self.output)
        yield StreamChunk(
            delta="",
            finish_reason="stop",
            usage=TokenUsage(input_tokens=10, output_tokens=20),
        )


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
async def app(tmp_path, monkeypatch):
    """Full ASGI app with in-memory DB + stub outliner."""
    db_url = f"sqlite+aiosqlite:///{tmp_path}/t.db"
    engine = get_engine(db_url)
    await init_db(engine)
    SessionMaker = async_session(engine)
    application = create_app(SessionMaker)
    application.state.session_maker = SessionMaker
    yield application
    await engine.dispose()


@pytest.fixture
async def seeded(app):
    """Seed a world / character / model_config / session and generate a screenplay."""
    SessionMaker = app.state.session_maker
    async with SessionMaker() as s:
        world = World(name="W", content_md="cyberpunk", style="dark", rules_json='{"mode":"light"}')
        char = Character(world=world, name="Riku", profile_md="hacker", base_stats_json="{}")
        cfg = ModelConfig(name="m", type="ollama", base_url="x", model_name="q")
        s.add_all([world, char, cfg])
        await s.flush()
        sess = GameSession(
            name="run",
            world_id=world.id,
            character_id=char.id,
            gm_model_config_id=cfg.id,
            summarizer_model_config_id=cfg.id,
        )
        s.add(sess)
        await s.flush()

        # Create an active screenplay directly (no LLM needed)
        sp = Screenplay(
            session_id=sess.id,
            genre="悬疑探案",
            chapters_json=json.dumps(
                [{"title": "第一章", "summary": "开始", "main_events": ["A"], "optional_events": [], "main_npcs": []}],
                ensure_ascii=False,
            ),
            main_characters_json=json.dumps(
                [{"name": "NPC甲", "role": "线人", "description": "路人", "intro_chapter": 1}],
                ensure_ascii=False,
            ),
            ending_md="PC 获胜",
            opening_hook="黑夜，你接到电话",
            status="active",
        )
        s.add(sp)
        await s.commit()

    yield app, sess.id, sp.id


@pytest.fixture
async def http(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture
async def seeded_http(seeded):
    app, session_id, screenplay_id = seeded
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c, session_id, screenplay_id


# ── Tests ────────────────────────────────────────────────────────────────────

async def test_patch_chapters_replaces_field(seeded_http):
    http, session_id, _ = seeded_http
    new_chapters = [
        {
            "title": "全新第一章",
            "summary": "新摘要",
            "main_events": ["事件X"],
            "optional_events": [],
            "main_npcs": ["新NPC"],
        }
    ]
    r = await http.patch(
        f"/sessions/{session_id}/screenplay",
        json={"chapters": new_chapters},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["chapters"]) == 1
    assert body["chapters"][0]["title"] == "全新第一章"
    # opening_hook should remain unchanged
    assert body["opening_hook"] == "黑夜，你接到电话"


async def test_patch_ending_only_leaves_chapters_unchanged(seeded_http):
    http, session_id, _ = seeded_http
    r = await http.patch(
        f"/sessions/{session_id}/screenplay",
        json={"ending_md": "全新结局：NPC 叛变"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ending_md"] == "全新结局：NPC 叛变"
    # chapters untouched
    assert body["chapters"][0]["title"] == "第一章"


async def test_patch_with_invalid_chapter_structure_returns_422(seeded_http):
    """chapters must be list[dict]; passing a list of strings should 422."""
    http, session_id, _ = seeded_http
    # chapters value is not list[dict] — it's a plain string (not even parseable as list[dict])
    r = await http.patch(
        f"/sessions/{session_id}/screenplay",
        json={"chapters": "not a list"},
    )
    # Pydantic rejects non-list value for list[dict] field → 422 Unprocessable Entity
    assert r.status_code == 422


async def test_patch_creates_revision_row_with_manual_edit_trigger(seeded):
    app, session_id, screenplay_id = seeded
    SessionMaker = app.state.session_maker

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        r = await http.patch(
            f"/sessions/{session_id}/screenplay",
            json={"ending_md": "新结局"},
        )
        assert r.status_code == 200, r.text

    async with SessionMaker() as s:
        revs = (
            await s.execute(
                select(ScreenplayRevision).where(
                    ScreenplayRevision.screenplay_id == screenplay_id
                )
            )
        ).scalars().all()

    assert len(revs) == 1
    rev = revs[0]
    assert rev.trigger_description == "manual_edit"
    assert rev.diff_summary == "manual edit by user"


async def test_patch_404_when_no_active_screenplay(app):
    """PATCH on a session that has no screenplay → 404."""
    SessionMaker = app.state.session_maker
    async with SessionMaker() as s:
        world = World(name="W2", content_md="x", style="dark", rules_json="{}")
        char = Character(world=world, name="X", profile_md="y", base_stats_json="{}")
        cfg = ModelConfig(name="m2", type="ollama", base_url="x", model_name="q")
        s.add_all([world, char, cfg])
        await s.flush()
        sess = GameSession(
            name="empty",
            world_id=world.id,
            character_id=char.id,
            gm_model_config_id=cfg.id,
            summarizer_model_config_id=cfg.id,
        )
        s.add(sess)
        await s.commit()
        sid = sess.id

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        r = await http.patch(f"/sessions/{sid}/screenplay", json={"ending_md": "x"})
    assert r.status_code == 404


async def test_patch_404_when_session_missing(app):
    """PATCH on a non-existent session_id → 404."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        r = await http.patch("/sessions/99999/screenplay", json={"ending_md": "x"})
    assert r.status_code == 404
