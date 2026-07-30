"""Integration tests for the plot_turn pending → rewrite_in_background pipeline.

The scheduler in routes_sessions/turn.py detects pending ScreenplayRevision rows
(those with diff_summary="(pending outliner rewrite)") and fires
asyncio.create_task(rewrite_in_background(...)).  These tests verify the
underlying coroutine — rewrite_screenplay_after_decision — and the
rewrite_in_background wrapper that opens its own session, plus the
schedule_pending_rewrites helper that the SSE route delegates to.

New tests (Batch 6):
  test_post_turn_scheduler_picks_up_pending_revisions
  test_scheduler_skips_already_processed
  test_scheduler_marks_failed_rewrites
"""
import asyncio
import json
from collections.abc import AsyncIterator
from unittest.mock import patch

import pytest
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
from dzmm.models.client import GenerationParams, Message, ModelClient, StreamChunk, TokenUsage
from dzmm.parsing.events import TagComplete
from dzmm.service.screenplay import (
    rewrite_in_background,
    rewrite_screenplay_after_decision,
    schedule_pending_rewrites,
)
from dzmm.service.state_apply import apply_tags

# ---------------------------------------------------------------------------
# Stub outline JSON that the fake outliner always returns
# ---------------------------------------------------------------------------
_NEW_CHAPTERS = [
    {
        "title": "第一章：背叛",
        "summary": "PC 背叛了女王，陷入追杀",
        "main_events": ["逃出皇宫", "寻找盟友"],
        "optional_events": ["偷取印信"],
        "main_npcs": ["女王卫队长"],
    },
    {
        "title": "第二章：流亡",
        "summary": "PC 流亡边境，收集反抗力量",
        "main_events": ["抵达边境", "整合残军"],
        "optional_events": [],
        "main_npcs": ["边境守将"],
    },
]
_STUB_REWRITE_JSON = json.dumps(
    {
        "chapters": _NEW_CHAPTERS,
        "main_characters": [
            {"name": "女王卫队长", "role": "追击者", "description": "冷酷的精英卫队长", "intro_chapter": 1}
        ],
        "ending": "PC 最终推翻女王统治",
        "opening_hook": "背叛的代价比你想象的更沉重",
        "diff_summary": "PC 背叛女王后，后续章节全面改写为流亡路线",
    },
    ensure_ascii=False,
)


class StubOutliner(ModelClient):
    """Deterministic outliner stub — always returns _STUB_REWRITE_JSON."""

    name = "stub-outliner"

    async def stream(
        self, messages: list[Message], params: GenerationParams
    ) -> AsyncIterator[StreamChunk]:
        yield StreamChunk(delta=_STUB_REWRITE_JSON)
        yield StreamChunk(
            delta="",
            finish_reason="stop",
            usage=TokenUsage(input_tokens=10, output_tokens=50),
        )


class FailingOutliner(ModelClient):
    """Outliner stub that always raises to simulate LLM failure."""

    name = "failing-outliner"

    async def stream(
        self, messages: list[Message], params: GenerationParams
    ) -> AsyncIterator[StreamChunk]:
        raise RuntimeError("LLM timed out")
        yield  # make it a generator


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
_INITIAL_CHAPTERS = [
    {
        "title": "第一章：序曲",
        "summary": "PC 初抵宫廷",
        "main_events": ["觐见女王", "探查内幕"],
        "optional_events": [],
        "main_npcs": ["女王"],
    },
    {
        "title": "第二章：阴谋",
        "summary": "秘密逐渐浮出水面",
        "main_events": ["发现密信", "对质大臣"],
        "optional_events": ["夜探密室"],
        "main_npcs": ["宰相"],
    },
]


async def _seed_world_and_session(s, cfg_id: int) -> tuple[int, int, int]:
    """Seed World + Character + GameSession; returns (world_id, char_id, session_id)."""
    world = World(name="宫廷秘事", content_md="中世纪宫廷", style="dark")
    char = Character(world=world, name="游侠", profile_md="身手矫健的游侠", base_stats_json="{}")
    s.add_all([world, char])
    await s.flush()
    sess = GameSession(
        name="跑团局",
        world_id=world.id,
        character_id=char.id,
        gm_model_config_id=cfg_id,
        summarizer_model_config_id=cfg_id,
    )
    s.add(sess)
    await s.flush()
    return world.id, char.id, sess.id


async def _seed_screenplay(s, session_id: int) -> Screenplay:
    sp = Screenplay(
        session_id=session_id,
        version=1,
        genre="宫廷悬疑",
        custom_prompt="",
        outline_md="测试大纲",
        chapters_json=json.dumps(_INITIAL_CHAPTERS, ensure_ascii=False),
        main_characters_json="[]",
        ending_md="女王的阴谋被揭穿",
        opening_hook="皇宫的夜晚永远不平静",
        current_chapter=1,
        completed_events_json="[]",
        status="active",
    )
    s.add(sp)
    await s.flush()
    return sp


@pytest.fixture
async def db(tmp_path):
    """Yields (engine, SessionMaker, session_id) for a fully seeded DB."""
    engine = get_engine(f"sqlite+aiosqlite:///{tmp_path}/rewrite_int.db")
    await init_db(engine)
    SessionMaker = async_session(engine)

    async with SessionMaker() as s:
        cfg = ModelConfig(name="gm", type="ollama", base_url="http://localhost:11434", model_name="qwen")
        s.add(cfg)
        await s.flush()
        cfg_id = cfg.id
        _, _, session_id = await _seed_world_and_session(s, cfg_id)
        await s.commit()

    yield engine, SessionMaker, session_id
    await engine.dispose()


# ---------------------------------------------------------------------------
# Happy-path integration test
# ---------------------------------------------------------------------------
async def test_rewrite_in_background_updates_revision_and_screenplay(db):
    """Full pipeline: plot_turn major → pending revision → rewrite → chapters updated."""
    engine, SessionMaker, session_id = db

    # Step 1: seed screenplay and apply plot_turn via apply_tags
    async with SessionMaker() as s:
        sp = await _seed_screenplay(s, session_id)
        await s.commit()
        sp_id = sp.id

    async with SessionMaker() as s:
        tag = TagComplete(
            name="plot_turn",
            attrs={"impact": "major", "description": "PC 背叛了女王，拒绝执行刺杀命令"},
            content="",
        )
        await apply_tags(s, session_id, current_turn=3, tags=[tag])
        await s.commit()

    # Step 2: verify pending revision was created
    async with SessionMaker() as s:
        revs = (
            await s.execute(
                select(ScreenplayRevision).where(ScreenplayRevision.screenplay_id == sp_id)
            )
        ).scalars().all()
    assert len(revs) == 1
    rev = revs[0]
    assert rev.diff_summary == "(pending outliner rewrite)"
    assert rev.before_chapters_json == rev.after_chapters_json, (
        "before and after must be equal while still pending"
    )
    rev_id = rev.id

    # Step 3: invoke rewrite_in_background directly (no create_task wrapping)
    client = StubOutliner()
    # Patch the internal build so rewrite_in_background uses our stub client
    # by calling rewrite_screenplay_after_decision directly with the stub instead
    async with SessionMaker() as s:
        result = await rewrite_screenplay_after_decision(
            s,
            session_id,
            rev_id,
            "PC 背叛了女王，拒绝执行刺杀命令",
            client,
        )
        await s.commit()

    assert result is not None, "rewrite_screenplay_after_decision must return the revision on success"

    # Step 4: verify DB state after rewrite
    async with SessionMaker() as s:
        rev_after = await s.get(ScreenplayRevision, rev_id)
        sp_after = await s.get(Screenplay, sp_id)

    # diff_summary must be replaced (not the pending placeholder)
    assert rev_after.diff_summary != "(pending outliner rewrite)"
    assert "背叛" in rev_after.diff_summary or len(rev_after.diff_summary) > 0

    # after_chapters_json must now differ from before_chapters_json
    assert rev_after.after_chapters_json != rev_after.before_chapters_json

    # Screenplay.chapters_json must reflect new chapters
    new_chapters = json.loads(sp_after.chapters_json)
    assert len(new_chapters) == len(_NEW_CHAPTERS)
    assert new_chapters[0]["title"] == _NEW_CHAPTERS[0]["title"]
    assert new_chapters[1]["title"] == _NEW_CHAPTERS[1]["title"]

    # ScreenplayRevision.after_chapters_json must also carry the new chapters
    rev_after_chapters = json.loads(rev_after.after_chapters_json)
    assert rev_after_chapters[0]["title"] == _NEW_CHAPTERS[0]["title"]


# ---------------------------------------------------------------------------
# Negative test 1: outliner failure leaves revision pending, screenplay intact
# ---------------------------------------------------------------------------
async def test_pending_revision_not_picked_up_when_outliner_fails(db):
    """When the outliner raises, diff_summary stays as the pending placeholder
    and Screenplay.chapters_json is untouched."""
    engine, SessionMaker, session_id = db

    async with SessionMaker() as s:
        sp = await _seed_screenplay(s, session_id)
        await s.commit()
        sp_id = sp.id
        original_chapters_json = sp.chapters_json

    async with SessionMaker() as s:
        tag = TagComplete(
            name="plot_turn",
            attrs={"impact": "major", "description": "PC 释放了大反派"},
            content="",
        )
        await apply_tags(s, session_id, current_turn=5, tags=[tag])
        await s.commit()

    async with SessionMaker() as s:
        rev = (
            await s.execute(
                select(ScreenplayRevision).where(ScreenplayRevision.screenplay_id == sp_id)
            )
        ).scalars().first()
        rev_id = rev.id

    # Call with a failing outliner
    failing_client = FailingOutliner()
    async with SessionMaker() as s:
        result = await rewrite_screenplay_after_decision(
            s,
            session_id,
            rev_id,
            "PC 释放了大反派",
            failing_client,
        )
        # On failure the function returns None and must NOT commit — session not committed

    assert result is None, "must return None when outliner raises"

    # Screenplay should be unchanged (session was not committed above)
    async with SessionMaker() as s:
        sp_after = await s.get(Screenplay, sp_id)
        rev_after = await s.get(ScreenplayRevision, rev_id)

    assert sp_after.chapters_json == original_chapters_json, (
        "Screenplay must be unchanged when outliner fails"
    )
    assert rev_after.diff_summary == "(pending outliner rewrite)", (
        "pending placeholder must survive an outliner failure"
    )


# ---------------------------------------------------------------------------
# Negative test 2: two consecutive major turns → two revisions, second sees
# the first revision's result as the new baseline
# ---------------------------------------------------------------------------
async def test_multiple_plot_turns_serialize_correctly(db):
    """Two <plot_turn impact=major> tags produce two revisions; the second
    rewrite receives the *first* revision's chapters as its baseline."""
    engine, SessionMaker, session_id = db

    async with SessionMaker() as s:
        sp = await _seed_screenplay(s, session_id)
        await s.commit()
        sp_id = sp.id

    # First plot_turn
    async with SessionMaker() as s:
        tag1 = TagComplete(
            name="plot_turn",
            attrs={"impact": "major", "description": "PC 背叛了女王"},
            content="",
        )
        await apply_tags(s, session_id, current_turn=3, tags=[tag1])
        await s.commit()

    # Rewrite revision 1
    async with SessionMaker() as s:
        rev1 = (
            await s.execute(
                select(ScreenplayRevision).where(ScreenplayRevision.screenplay_id == sp_id)
            )
        ).scalars().first()
        rev1_id = rev1.id
        result1 = await rewrite_screenplay_after_decision(
            s, session_id, rev1_id, "PC 背叛了女王", StubOutliner()
        )
        await s.commit()

    assert result1 is not None

    # Verify screenplay now has new chapters after first rewrite
    async with SessionMaker() as s:
        sp_after_first = await s.get(Screenplay, sp_id)
    chapters_after_first = json.loads(sp_after_first.chapters_json)
    assert chapters_after_first[0]["title"] == _NEW_CHAPTERS[0]["title"]

    # Second plot_turn (applied after first rewrite committed)
    async with SessionMaker() as s:
        tag2 = TagComplete(
            name="plot_turn",
            attrs={"impact": "major", "description": "PC 发现了秘密武器"},
            content="",
        )
        await apply_tags(s, session_id, current_turn=6, tags=[tag2])
        await s.commit()

    # There should now be two ScreenplayRevision rows
    async with SessionMaker() as s:
        all_revs = (
            await s.execute(
                select(ScreenplayRevision)
                .where(ScreenplayRevision.screenplay_id == sp_id)
                .order_by(ScreenplayRevision.id)
            )
        ).scalars().all()
    assert len(all_revs) == 2

    rev2 = all_revs[1]
    rev2_id = rev2.id

    # The second revision's before_chapters_json must be the *new* chapters
    # (i.e. the result of the first rewrite, not the original)
    before_chapters_rev2 = json.loads(rev2.before_chapters_json)
    assert before_chapters_rev2[0]["title"] == _NEW_CHAPTERS[0]["title"], (
        "second revision's before snapshot must reflect the first rewrite's output"
    )

    # Rewrite revision 2 as well
    async with SessionMaker() as s:
        result2 = await rewrite_screenplay_after_decision(
            s, session_id, rev2_id, "PC 发现了秘密武器", StubOutliner()
        )
        await s.commit()

    assert result2 is not None

    async with SessionMaker() as s:
        rev2_after = await s.get(ScreenplayRevision, rev2_id)

    assert rev2_after.diff_summary != "(pending outliner rewrite)"
    # The stub always returns the same chapters as what is already stored
    # (since the first rewrite already wrote _NEW_CHAPTERS into the screenplay).
    # What matters is that diff_summary was filled in (rewrite ran successfully)
    # and after_chapters_json is set (not empty).
    assert rev2_after.after_chapters_json is not None
    after_chapters_rev2 = json.loads(rev2_after.after_chapters_json)
    assert len(after_chapters_rev2) == len(_NEW_CHAPTERS)


# ---------------------------------------------------------------------------
# Batch-6 scheduler tests
# ---------------------------------------------------------------------------


async def test_post_turn_scheduler_picks_up_pending_revisions(db):
    """schedule_pending_rewrites should detect a pending revision and fire a task.

    We patch asyncio.create_task to intercept the call so we can (a) verify
    exactly one task was scheduled and (b) actually await the coroutine with a
    stub client so the DB state can be asserted synchronously.
    """
    engine, SessionMaker, session_id = db

    # Seed screenplay and apply a major plot_turn
    async with SessionMaker() as s:
        sp = await _seed_screenplay(s, session_id)
        await s.commit()
        sp_id = sp.id

    async with SessionMaker() as s:
        tag = TagComplete(
            name="plot_turn",
            attrs={"impact": "major", "description": "PC 夺取了皇权"},
            content="",
        )
        await apply_tags(s, session_id, current_turn=4, tags=[tag])
        await s.commit()

    # Gather rewrite coroutines created by create_task so we can await them.
    # We filter to only `rewrite_in_background` coroutines to avoid capturing
    # SQLAlchemy-internal create_task calls that fire during session cleanup.
    rewrite_coros: list = []
    _orig_create_task = asyncio.create_task

    def _capture_task(coro, **kw):
        coro_name = getattr(coro, "__qualname__", "") or getattr(coro, "__name__", "")
        if "rewrite_in_background" in coro_name:
            rewrite_coros.append(coro)
            return asyncio.ensure_future(asyncio.sleep(0))
        return _orig_create_task(coro, **kw)

    with patch("asyncio.create_task", side_effect=_capture_task):
        count = await schedule_pending_rewrites(SessionMaker, session_id)

    assert count == 1, "exactly one pending revision should have been scheduled"
    assert len(rewrite_coros) == 1

    # Now run the captured coroutine with our stub client by patching build_client
    with patch("dzmm.models.factory.build_client", return_value=StubOutliner()):
        await rewrite_coros[0]

    # Verify DB state was updated
    async with SessionMaker() as s:
        rev_all = (await s.execute(
            select(ScreenplayRevision).where(ScreenplayRevision.screenplay_id == sp_id)
        )).scalars().all()
    assert len(rev_all) == 1
    rev = rev_all[0]
    assert rev.diff_summary != "(pending outliner rewrite)", (
        "after scheduler runs, diff_summary should be filled in"
    )
    assert rev.after_chapters_json != rev.before_chapters_json


async def test_scheduler_skips_already_processed(db):
    """schedule_pending_rewrites must not fire a task for a revision whose
    diff_summary is already a real summary (not the pending placeholder)."""
    engine, SessionMaker, session_id = db

    async with SessionMaker() as s:
        sp = await _seed_screenplay(s, session_id)
        await s.commit()
        sp_id = sp.id

    # Create a revision that has already been processed (diff_summary filled)
    async with SessionMaker() as s:
        sp_row = await s.get(Screenplay, sp_id)
        rev = ScreenplayRevision(
            screenplay_id=sp_id,
            revision_num=1,
            trigger_turn=2,
            trigger_description="PC 已经做过决定了",
            before_chapters_json=sp_row.chapters_json,
            after_chapters_json=json.dumps(_NEW_CHAPTERS, ensure_ascii=False),
            diff_summary="PC 背叛女王后，后续章节全面改写为流亡路线",
        )
        s.add(rev)
        await s.commit()

    # count == 0 is the key assertion; we also verify no rewrite coros were fired.
    _orig_create_task2 = asyncio.create_task
    rewrite_coros2: list = []

    def _capture_task2(coro, **kw):
        coro_name = getattr(coro, "__qualname__", "") or getattr(coro, "__name__", "")
        if "rewrite_in_background" in coro_name:
            rewrite_coros2.append(coro)
            return asyncio.ensure_future(asyncio.sleep(0))
        return _orig_create_task2(coro, **kw)

    with patch("asyncio.create_task", side_effect=_capture_task2):
        count = await schedule_pending_rewrites(SessionMaker, session_id)

    assert count == 0, "already-processed revision must not trigger a new task"
    assert len(rewrite_coros2) == 0, "no rewrite tasks should have been created"


async def test_scheduler_marks_failed_rewrites(db):
    """When rewrite_in_background's outliner raises, diff_summary must be
    updated to '(rewrite failed: ...)' so the scheduler won't retry forever."""
    engine, SessionMaker, session_id = db

    async with SessionMaker() as s:
        sp = await _seed_screenplay(s, session_id)
        await s.commit()
        sp_id = sp.id

    async with SessionMaker() as s:
        tag = TagComplete(
            name="plot_turn",
            attrs={"impact": "major", "description": "PC 销毁了魔法石"},
            content="",
        )
        await apply_tags(s, session_id, current_turn=7, tags=[tag])
        await s.commit()

    async with SessionMaker() as s:
        rev = (await s.execute(
            select(ScreenplayRevision).where(ScreenplayRevision.screenplay_id == sp_id)
        )).scalars().first()
        rev_id = rev.id
        original_chapters = rev.before_chapters_json

    # Patch build_client inside rewrite_in_background to return a failing outliner
    with patch("dzmm.models.factory.build_client", return_value=FailingOutliner()):
        await rewrite_in_background(SessionMaker, session_id, rev_id, "PC 销毁了魔法石")

    async with SessionMaker() as s:
        rev_after = await s.get(ScreenplayRevision, rev_id)
        sp_after = await s.get(Screenplay, sp_id)

    assert "rewrite failed" in rev_after.diff_summary.lower(), (
        f"diff_summary should contain 'rewrite failed', got: {rev_after.diff_summary!r}"
    )
    assert rev_after.after_chapters_json == rev_after.before_chapters_json, (
        "chapters must be unchanged after a failed rewrite"
    )
    assert sp_after.chapters_json == original_chapters, (
        "Screenplay.chapters_json must be unchanged after a failed rewrite"
    )
