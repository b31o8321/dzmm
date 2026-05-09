import pytest
from sqlalchemy import select

from dzmm.db.base import async_session, get_engine, init_db
from dzmm.db.models import AgentStream, NPC
from dzmm.models.client import ModelClient, StreamChunk, TokenUsage
from dzmm.parsing.events import NarrativeDelta, TagComplete
from dzmm.service.agents.orchestrator import run_turn_v10


@pytest.fixture
async def session_maker(tmp_path):
    db_url = f"sqlite+aiosqlite:///{tmp_path}/t.db"
    engine = get_engine(db_url)
    await init_db(engine)
    sm = async_session(engine)
    yield sm
    await engine.dispose()


class _MultiClient(ModelClient):
    """Returns different output based on prompt content. Director / Scene /
    NPC prompts have distinct headers we match on."""
    name = "multi"

    async def stream(self, msgs, params):
        # Scene path streams narrative
        text = "<narrative>巷子潮湿。</narrative>"
        yield StreamChunk(delta=text, finish_reason="stop")

    async def complete(self, msgs, params):
        joined = "\n".join(m.content for m in msgs)
        if "剧情导演" in joined:
            return ("<plot_directive>\n- 主推：见老者\n- NPC：丽莎主动\n"
                    "- 节奏：悬疑\n- 禁止：不开新场所\n</plot_directive>",
                    TokenUsage())
        if "扮演 TRPG 中的 NPC" in joined:
            return ('<say speaker="丽莎" mood="紧张">「快走！」</say>',
                    TokenUsage())
        return "", TokenUsage()


@pytest.mark.asyncio
async def test_run_turn_v10_yields_director_then_scene_then_npc(session_maker):
    from dzmm.db.models import Character, ModelConfig, Session as GameSession, World
    async with session_maker() as s:
        w = World(name="W", content_md="赛博朋克")
        c = Character(world_id=1, name="Riku", profile_md="hacker",
                      base_stats_json='{"hp":20}')
        m = ModelConfig(name="x", type="ollama", base_url="x", model_name="y")
        s.add_all([w, c, m])
        await s.flush()
        sess = GameSession(name="t", world_id=w.id, character_id=c.id,
                           gm_model_config_id=m.id, summarizer_model_config_id=m.id)
        s.add(sess)
        await s.flush()
        s.add(NPC(session_id=sess.id, name="丽莎", pinned=True,
                  archetype="热心邻家少女", description="21 岁",
                  purpose="找弟弟", state="焦虑",
                  gender="female", emotion_json='{"fear":60}'))
        await s.commit()
        sid = sess.id

    client = _MultiClient()
    events = []
    async with session_maker() as s:
        async for ev in run_turn_v10(
            s, session_id=sid, user_action="冲进巷子",
            scene_client=client, director_client=client,
            npc_client=client,
            world_md="赛博朋克", character_md="Riku - hacker",
            live_state_text='{"hp":20}', key_facts="第 1 回合",
            recent_messages=[],
        ):
            events.append(ev)
        await s.commit()

    narratives = [e for e in events if isinstance(e, NarrativeDelta)]
    tags = [e for e in events if isinstance(e, TagComplete)]
    assert any("巷子" in n.text for n in narratives)
    assert any(t.name == "say" and t.attrs.get("speaker") == "丽莎" for t in tags)

    async with session_maker() as s:
        streams = (await s.execute(
            select(AgentStream).where(AgentStream.session_id == sid)
        )).scalars().all()
        kinds = {(st.kind, st.ref) for st in streams}
        assert ("gm_director", "") in kinds
        assert ("npc", "丽莎") in kinds


def test_sort_npcs_for_turn_prioritizes_named_then_emotional():
    """v0.10.2 — name appears in user_action wins; then highest emotion;
    then last_seen_turn descending."""
    from types import SimpleNamespace
    from dzmm.service.agents.orchestrator import _sort_npcs_for_turn

    a = SimpleNamespace(name="阿伟", emotion_json='{"fear":80}', last_seen_turn=2)
    b = SimpleNamespace(name="丽莎", emotion_json='{"anger":30}', last_seen_turn=5)
    c = SimpleNamespace(name="老张", emotion_json='{}', last_seen_turn=10)

    out = _sort_npcs_for_turn([a, b, c], "我把丽莎拉过来")
    # 丽莎 (named in user_action) → first; 阿伟 (highest emotion 80) → second;
    # 老张 (no signal) → last.
    assert [n.name for n in out] == ["丽莎", "阿伟", "老张"]


def test_sort_npcs_for_turn_handles_invalid_emotion_json():
    """Emotion JSON that fails to parse must not crash sort — fall back to 0."""
    from types import SimpleNamespace
    from dzmm.service.agents.orchestrator import _sort_npcs_for_turn

    a = SimpleNamespace(name="A", emotion_json="not-json", last_seen_turn=1)
    b = SimpleNamespace(name="B", emotion_json='{"fear":50}', last_seen_turn=1)
    out = _sort_npcs_for_turn([a, b], "")
    # B has higher emotion → should come first.
    assert out[0].name == "B"


@pytest.mark.asyncio
async def test_run_turn_v10_uses_session_maker_for_isolated_npc_sessions(session_maker):
    """v0.10.2 — when session_maker is passed, NPC fan-out runs in parallel
    on isolated sessions. Verify the path doesn't crash and still yields
    the say tag in the orchestrator's sorted yield order."""
    from dzmm.db.models import Character, ModelConfig, Session as GameSession, World

    async with session_maker() as s:
        w = World(name="W", content_md="x")
        c = Character(world_id=1, name="Riku", profile_md="h",
                      base_stats_json='{"hp":20}')
        m = ModelConfig(name="x", type="ollama", base_url="x", model_name="y")
        s.add_all([w, c, m])
        await s.flush()
        sess = GameSession(name="t", world_id=w.id, character_id=c.id,
                           gm_model_config_id=m.id, summarizer_model_config_id=m.id)
        s.add(sess)
        await s.flush()
        s.add(NPC(session_id=sess.id, name="丽莎", pinned=True,
                  archetype="x", description="x", purpose="x", state="x",
                  gender="female", emotion_json='{"fear":60}'))
        await s.commit()
        sid = sess.id

    client = _MultiClient()
    events = []
    async with session_maker() as s:
        async for ev in run_turn_v10(
            s, session_id=sid, user_action="冲",
            scene_client=client, director_client=client, npc_client=client,
            session_maker=session_maker,
            world_md="x", character_md="x",
            live_state_text="{}", key_facts="",
            recent_messages=[],
        ):
            events.append(ev)
        await s.commit()

    say_tags = [e for e in events if isinstance(e, TagComplete) and e.name == "say"]
    assert len(say_tags) == 1
    assert say_tags[0].attrs.get("speaker") == "丽莎"


@pytest.mark.asyncio
async def test_build_director_snapshot_includes_pc_state_and_chapter(session_maker):
    """v0.10.3: Director snapshot 含 PC vital + 剧本章节进度，不再只有 turn/doom。"""
    import json
    from dzmm.db.models import (
        Character, CharState, ModelConfig,
        Screenplay, Session as GameSession, World,
    )
    from dzmm.service.agents.orchestrator import _build_director_snapshot

    async with session_maker() as s:
        w = World(name="W", content_md="x")
        c = Character(world_id=1, name="C", profile_md="x",
                      base_stats_json='{"hp":20}', level=3)
        m = ModelConfig(name="m", type="ollama", base_url="x", model_name="y")
        s.add_all([w, c, m])
        await s.flush()
        sess = GameSession(name="t", world_id=1, character_id=1,
                           gm_model_config_id=1, summarizer_model_config_id=1,
                           turn_count=5, doom_score=42)
        s.add(sess)
        await s.flush()
        s.add(CharState(
            session_id=sess.id,
            stats_json='{"hp":12, "sanity":8}',
            inventory_json='[]',
        ))
        s.add(Screenplay(
            session_id=sess.id,
            world_id=1,
            chapters_json=json.dumps([
                {"title": "废墟开端", "main_events": [
                    {"description": "PC 见到老者"},
                    {"description": "PC 取得地图"},
                ]},
            ], ensure_ascii=False),
            completed_events_json=json.dumps([
                {"chapter": 1, "event_idx": 0, "type": "main"},
            ]),
            current_chapter=1,
            status="active",
        ))
        await s.commit()

        snap = await _build_director_snapshot(s, sess.id, current_turn=6)

    assert "doom: 42" in snap
    assert "hp=12" in snap
    assert "sanity=8" in snap
    assert "PC level: 3" in snap
    assert "废墟开端" in snap
    assert "1/2" in snap  # 1 done out of 2 main events
    assert "PC 取得地图" in snap  # next pending event description


@pytest.mark.asyncio
async def test_director_trigger_state_detects_chapter_advance_last_turn(session_maker):
    """v0.10.3: 上一回合 emit chapter_advance → cs_obj.chapter_advanced_last_turn=True。"""
    import json
    from dzmm.db.models import (
        Character, ModelConfig, Message as MessageRow,
        Session as GameSession, World,
    )
    from dzmm.service.agents.orchestrator import _build_director_trigger_state

    async with session_maker() as s:
        w = World(name="W", content_md="x")
        c = Character(world_id=1, name="C", profile_md="x", base_stats_json='{}')
        m = ModelConfig(name="m", type="ollama", base_url="x", model_name="y")
        s.add_all([w, c, m])
        await s.flush()
        sess = GameSession(name="t", world_id=1, character_id=1,
                           gm_model_config_id=1, summarizer_model_config_id=1,
                           turn_count=4)
        s.add(sess)
        await s.flush()
        s.add(MessageRow(
            session_id=sess.id, role="assistant", turn=4, content="x",
            events_json=json.dumps([
                {"type": "narrative", "payload": {}, "content": ""},
                {"type": "chapter_advance", "payload": {}, "content": ""},
            ]),
        ))
        await s.commit()
        state = await _build_director_trigger_state(s, sess.id, sess, current_turn=5)
    assert state.chapter_advanced_last_turn is True
    assert state.major_plot_turn_last_turn is False


@pytest.mark.asyncio
async def test_director_trigger_state_detects_hp_critical(session_maker):
    """hp <= 5 → cs_obj.hp 真实值（trigger 那边判断）。"""
    from dzmm.db.models import (
        Character, CharState, ModelConfig,
        Session as GameSession, World,
    )
    from dzmm.service.agents.orchestrator import _build_director_trigger_state

    async with session_maker() as s:
        w = World(name="W", content_md="x")
        c = Character(world_id=1, name="C", profile_md="x", base_stats_json='{}')
        m = ModelConfig(name="m", type="ollama", base_url="x", model_name="y")
        s.add_all([w, c, m])
        await s.flush()
        sess = GameSession(name="t", world_id=1, character_id=1,
                           gm_model_config_id=1, summarizer_model_config_id=1,
                           turn_count=3)
        s.add(sess)
        await s.flush()
        s.add(CharState(session_id=sess.id, stats_json='{"hp": 3, "sanity": 15}'))
        await s.commit()
        state = await _build_director_trigger_state(s, sess.id, sess, current_turn=4)
    assert state.hp == 3
    assert state.sanity == 15


@pytest.mark.asyncio
async def test_compress_streams_folds_old_messages(session_maker):
    """超过 threshold 后，旧消息被压成 1 条 summary + 最近 keep_recent 条原文保留。"""
    from sqlalchemy import select
    from dzmm.db.models import AgentMessage
    from dzmm.models.client import ModelClient, StreamChunk, TokenUsage
    from dzmm.service.agents.streams import (
        append_message, compress_if_needed, get_or_create_stream,
    )

    class _Sum(ModelClient):
        name = "s"
        async def stream(self, msgs, params):
            yield StreamChunk(delta="", finish_reason="stop")
        async def complete(self, msgs, params):
            return "摘要", TokenUsage()

    async with session_maker() as s:
        st = await get_or_create_stream(s, 1, "npc", "丽莎")
        await s.flush()
        for i in range(50):
            await append_message(s, st.id, turn=i, role="user", content=f"u{i}")
            await append_message(s, st.id, turn=i, role="assistant", content=f"a{i}")
        await s.commit()
        await compress_if_needed(s, st.id, _Sum(), threshold=25, keep_recent=8)
        await s.commit()
        rows = (await s.execute(
            select(AgentMessage).where(AgentMessage.stream_id == st.id)
        )).scalars().all()
    assert sum(1 for r in rows if r.is_summary) == 1
    assert sum(1 for r in rows if not r.is_summary) == 8
