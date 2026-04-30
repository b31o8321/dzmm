import json
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import select

from dzmm.db.base import async_session, get_engine, init_db
from dzmm.db.models import (
    Character,
    ModelConfig,
    Screenplay,
    Session as GameSession,
    World,
)
from dzmm.models.client import GenerationParams, Message, ModelClient, StreamChunk, TokenUsage
from dzmm.service.screenplay import generate_screenplay


_STUB_OUTLINE = json.dumps({
    "chapters": [
        {"title": "第一章：迷雾", "summary": "调查一桩失踪",
         "main_events": ["发现线索 A", "对峙嫌疑人 B"],
         "optional_events": ["搜查老宅"],
         "main_npcs": ["陈子轩"]},
        {"title": "第二章：真相", "summary": "对峙幕后黑手",
         "main_events": ["进入据点", "战斗主反派"],
         "optional_events": [],
         "main_npcs": ["黑手党头目"]},
    ],
    "main_characters": [
        {"name": "陈子轩", "role": "线人", "description": "中年华人男子",
         "intro_chapter": 1},
    ],
    "ending": "PC 揭穿黑手党的阴谋",
    "opening_hook": "雨夜的霓虹下，你接到一通电话",
}, ensure_ascii=False)


class StubOutliner(ModelClient):
    name = "stub"

    def __init__(self, output: str):
        self.output = output

    async def stream(
        self, messages: list[Message], params: GenerationParams
    ) -> AsyncIterator[StreamChunk]:
        yield StreamChunk(delta=self.output)
        yield StreamChunk(delta="", finish_reason="stop",
                          usage=TokenUsage(input_tokens=10, output_tokens=20))


@pytest.fixture
async def seeded(tmp_path):
    engine = get_engine(f"sqlite+aiosqlite:///{tmp_path}/t.db")
    await init_db(engine)
    SessionMaker = async_session(engine)
    async with SessionMaker() as s:
        world = World(name="W", content_md="cyberpunk", style="dark", rules_json='{"mode":"light"}')
        char = Character(world=world, name="Riku", profile_md="hacker", base_stats_json='{}')
        cfg = ModelConfig(name="m", type="ollama", base_url="x", model_name="q")
        s.add_all([world, char, cfg])
        await s.flush()
        sess = GameSession(name="run", world_id=world.id, character_id=char.id,
                           gm_model_config_id=cfg.id, summarizer_model_config_id=cfg.id)
        s.add(sess)
        await s.commit()
        sid = sess.id
    yield engine, SessionMaker, sid
    await engine.dispose()


async def test_generate_screenplay_persists_outline(seeded):
    engine, SessionMaker, sid = seeded
    client = StubOutliner(_STUB_OUTLINE)
    async with SessionMaker() as s:
        await generate_screenplay(s, sid, "悬疑探案", "", client)
        await s.commit()
    async with SessionMaker() as s:
        row = (await s.execute(select(Screenplay).where(Screenplay.session_id == sid))).scalar_one()
        chapters = json.loads(row.chapters_json)
        assert len(chapters) == 2
        assert chapters[0]["title"] == "第一章：迷雾"
        mc = json.loads(row.main_characters_json)
        assert mc[0]["name"] == "陈子轩"
        assert "雨夜" in row.opening_hook
        assert row.status == "active"
        assert row.current_chapter == 1
        assert row.version == 1


async def test_generate_screenplay_strips_markdown_code_fence(seeded):
    """Defensive: model sometimes wraps JSON in ```json ... ``` despite instruction."""
    engine, SessionMaker, sid = seeded
    fenced = "```json\n" + _STUB_OUTLINE + "\n```"
    client = StubOutliner(fenced)
    async with SessionMaker() as s:
        await generate_screenplay(s, sid, "悬疑探案", "", client)
        await s.commit()
        # If we got here, parsing tolerated the fence


async def test_generate_screenplay_rejects_invalid_json(seeded):
    engine, SessionMaker, sid = seeded
    client = StubOutliner("not json at all")
    with pytest.raises(ValueError):
        async with SessionMaker() as s:
            await generate_screenplay(s, sid, "悬疑探案", "", client)
