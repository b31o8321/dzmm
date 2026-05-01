"""v0.2.0 wizard tests — service unit tests + endpoint integration tests."""
import json
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from dzmm.db.base import async_session, get_engine, init_db
from dzmm.db.models import (
    Character,
    NPC,
    Screenplay,
    Session as GameSession,
    World,
)
from dzmm.main import create_app
from dzmm.models.client import (
    GenerationParams,
    Message,
    ModelClient,
    StreamChunk,
    TokenUsage,
)
from dzmm.service.wizard import (
    _with_retry,
    finalize_wizard,
    generate_character,
    generate_npcs,
    generate_screenplay_from_wizard,
    generate_single_npc,
    generate_world_brief,
    generate_world_details,
)


class StubLLM(ModelClient):
    name = "stub-wizard"

    def __init__(self, output: str):
        self.output = output

    async def stream(
        self, messages: list[Message], params: GenerationParams
    ) -> AsyncIterator[StreamChunk]:
        yield StreamChunk(delta=self.output)
        yield StreamChunk(
            delta="",
            finish_reason="stop",
            usage=TokenUsage(input_tokens=20, output_tokens=80),
        )


# ============================================================================
# Service unit tests — generate_xxx
# ============================================================================

_BRIEF_OUTPUT = """## 名字
赛博九龙

## 年代与地点
2089 年的香港九龙城寨。霓虹永不熄灭，雨水带着电池液的酸味。义体与神经接驳普及。

## 核心冲突
四大企业暗中争夺一项可以改写人类记忆的「共感协议」。
黑客组织、警方、教派全部卷入。普通人在街角随时可能消失。
"""


async def test_generate_world_brief_parses_three_sections():
    client = StubLLM(_BRIEF_OUTPUT)
    out = await generate_world_brief("赛博朋克", "记忆与身份", client)
    assert out["name"] == "赛博九龙"
    assert "2089" in out["setting"]
    assert "共感协议" in out["conflict"]
    assert out["raw_md"].startswith("## 名字")


_DETAILS_OUTPUT = """## 地理与环境
高密度立体城市，街道分三层。

## 社会与势力
- **荒坂集团**：保守派
- **义体黑市**：地下势力
- **教会残党**：精神控制

## 风俗
义体改造日普及程度极高，每年「电节」时整城停电。

## 关键地点
- **九龙天井**：废弃电梯井改造的黑市
- **慈光教堂**：实验对象的最后归宿
"""


async def test_generate_world_details_returns_world_md():
    client = StubLLM(_DETAILS_OUTPUT)
    out = await generate_world_details("brief here", client)
    assert "world_md" in out
    assert "九龙天井" in out["world_md"]


_CHAR_OUTPUT = """## 基本信息
- 姓名：林默
- 年龄：28
- 职业：黑客
- 外貌：瘦削，左眼义体泛蓝光

## 性格
冷静而内疚

## 背景
出身九龙城寨，父亲是义体走私贩。

## 能力
- **神经入侵**：3 米内可瘫痪小型电子设备
- **记忆回放**：可重播自己 24 小时内的记忆

## 物品
- **黑市义眼**：来路不明
- **电磁刀**：父亲遗物

## 弱点
- **义眼过载**：连续使用 5 分钟会暂时失明
- **创伤后应激**：见到红色霓虹会眩晕
"""


async def test_generate_character_extracts_name():
    client = StubLLM(_CHAR_OUTPUT)
    out = await generate_character("world here", "黑客", client)
    assert out["name"] == "林默"
    assert "神经入侵" in out["profile_md"]


async def test_generate_character_fallback_when_no_name():
    """If LLM forgets to put 姓名: line, we return placeholder."""
    bad = "## 基本信息\n- 职业：刺客\n\n## 性格\n冷酷"
    client = StubLLM(bad)
    out = await generate_character("w", "a", client)
    assert out["name"] == "(未命名)"


_NPC_OUTPUT = json.dumps([
    {"name": "陈子轩", "role": "盟友",
     "description": "中年华人男子，前 SWAT", "motivation": "替女儿复仇"},
    {"name": "苍井博士", "role": "对手",
     "description": "白发精瘦，神经科学权威", "motivation": "完成共感协议"},
    {"name": "K", "role": "导师",
     "description": "永远只露半张脸的黑客", "motivation": "训练接班人"},
], ensure_ascii=False)


async def test_generate_npcs_parses_json():
    client = StubLLM(_NPC_OUTPUT)
    out = await generate_npcs("w", "c", client)
    assert len(out["npcs"]) == 3
    assert out["npcs"][0]["name"] == "陈子轩"
    assert out["npcs"][1]["role"] == "对手"


async def test_generate_npcs_strips_code_fence():
    fenced = "```json\n" + _NPC_OUTPUT + "\n```"
    client = StubLLM(fenced)
    out = await generate_npcs("w", "c", client)
    assert len(out["npcs"]) == 3


async def test_generate_npcs_rejects_non_list():
    client = StubLLM('{"not": "a list"}')
    with pytest.raises(ValueError):
        await generate_npcs("w", "c", client)


_SCREENPLAY_OUTPUT = json.dumps({
    "chapters": [
        {"title": "第一章：雨幕", "summary": "调查",
         "main_events": ["接到委托", "前往九龙天井"],
         "optional_events": ["搜查教堂"],
         "main_npcs": ["陈子轩"]},
        {"title": "第二章：协议", "summary": "对峙博士",
         "main_events": ["潜入实验室", "对峙苍井"],
         "optional_events": [],
         "main_npcs": ["苍井博士"]},
    ],
    "main_characters": [
        {"name": "陈子轩", "role": "盟友",
         "description": "前 SWAT，PC 的线人", "intro_chapter": 1},
    ],
    "ending": "PC 销毁共感协议或将之据为己有",
    "opening_hook": "雨夜，电话响起，对方只说了一个地址",
}, ensure_ascii=False)


async def test_generate_screenplay_from_wizard_parses():
    client = StubLLM(_SCREENPLAY_OUTPUT)
    npcs = [
        {"name": "陈子轩", "role": "盟友",
         "description": "前 SWAT", "motivation": "复仇"},
    ]
    out = await generate_screenplay_from_wizard(
        world_md="赛博九龙",
        character_md="林默 黑客",
        npcs=npcs,
        genre="悬疑探案",
        client=client,
    )
    assert len(out["chapters"]) == 2
    assert out["chapters"][0]["title"] == "第一章：雨幕"
    assert "雨夜" in out["opening_hook"]


# ============================================================================
# finalize_wizard — atomic creation
# ============================================================================

@pytest.fixture
async def empty_db(tmp_path):
    engine = get_engine(f"sqlite+aiosqlite:///{tmp_path}/wiz.db")
    await init_db(engine)
    SessionMaker = async_session(engine)
    yield engine, SessionMaker
    await engine.dispose()


async def _seed_model_configs(SessionMaker) -> tuple[int, int]:
    from dzmm.db.models import ModelConfig
    async with SessionMaker() as s:
        m1 = ModelConfig(name="gm", type="ollama", base_url="x", model_name="q")
        m2 = ModelConfig(name="sum", type="ollama", base_url="x", model_name="q")
        s.add_all([m1, m2])
        await s.commit()
        return m1.id, m2.id


async def test_finalize_wizard_creates_all_rows(empty_db):
    _, SessionMaker = empty_db
    gm_id, sum_id = await _seed_model_configs(SessionMaker)
    bundle = {
        "world": {"name": "赛博九龙", "content_md": "霓虹永不熄灭", "style": "dark"},
        "character": {
            "name": "林默",
            "profile_md": "黑客 / 内疚 / 神经入侵",
            "base_stats_json": '{"hp":20}',
        },
        "pinned_npcs": [
            {"name": "陈子轩", "role": "盟友",
             "description": "前 SWAT", "motivation": "复仇"},
            {"name": "苍井博士", "role": "对手",
             "description": "白发精瘦", "motivation": "完成实验"},
        ],
        "screenplay": {
            "chapters": [{"title": "第一章", "summary": "x", "main_events": [],
                          "optional_events": [], "main_npcs": []}],
            "main_characters": [
                {"name": "陈子轩", "role": "盟友", "description": "线人",
                 "intro_chapter": 1},
            ],
            "ending_md": "销毁协议",
            "opening_hook": "雨夜电话",
        },
        "session_name": "九龙之雨",
        "gm_model_config_id": gm_id,
        "summarizer_model_config_id": sum_id,
        "genre": "赛博朋克悬疑",
    }
    async with SessionMaker() as s:
        sid = await finalize_wizard(s, bundle)
        await s.commit()
        assert isinstance(sid, int)

    async with SessionMaker() as s:
        worlds = (await s.execute(select(World))).scalars().all()
        chars = (await s.execute(select(Character))).scalars().all()
        sessions = (await s.execute(select(GameSession))).scalars().all()
        npcs = (await s.execute(select(NPC))).scalars().all()
        sps = (await s.execute(select(Screenplay))).scalars().all()
        assert len(worlds) == 1 and worlds[0].name == "赛博九龙"
        assert len(chars) == 1 and chars[0].name == "林默"
        assert len(sessions) == 1 and sessions[0].id == sid
        assert sessions[0].name == "九龙之雨"
        assert len(npcs) == 2
        names = {n.name for n in npcs}
        assert names == {"陈子轩", "苍井博士"}
        # v0.2.2: pinned NPCs only reveal `name` initially; GM unveils
        # description/purpose/archetype progressively via npc_update.
        for n in npcs:
            assert n.pinned is True
            rev = json.loads(n.revealed_json)
            assert rev.get("name") is True
            assert not rev.get("description")
            assert not rev.get("purpose")
            assert not rev.get("archetype")
        assert len(sps) == 1 and sps[0].status == "active"
        assert sps[0].current_chapter == 1
        chapters = json.loads(sps[0].chapters_json)
        assert chapters[0]["title"] == "第一章"


async def test_finalize_wizard_rolls_back_on_invalid_bundle(empty_db):
    _, SessionMaker = empty_db
    # Missing required keys.
    bad_bundle = {"world": {"name": "x", "content_md": "y"}}
    async with SessionMaker() as s:
        with pytest.raises(ValueError):
            await finalize_wizard(s, bad_bundle)
        await s.rollback()
    async with SessionMaker() as s:
        # Nothing should have been committed.
        assert (await s.execute(select(World))).scalars().all() == []
        assert (await s.execute(select(GameSession))).scalars().all() == []


# ============================================================================
# Endpoint integration tests
# ============================================================================

@pytest.fixture
async def app(tmp_path):
    db_url = f"sqlite+aiosqlite:///{tmp_path}/wapi.db"
    engine = get_engine(db_url)
    await init_db(engine)
    SessionMaker = async_session(engine)
    a = create_app(SessionMaker)
    a.state.session_maker = SessionMaker
    yield a
    await engine.dispose()


@pytest.fixture
async def http(app):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


async def _make_model_config(http) -> int:
    r = await http.post("/model_configs", json={
        "name": "local", "type": "ollama",
        "base_url": "http://localhost:11434", "model_name": "qwen2.5:7b",
    })
    return r.json()["id"]


def _patch_wizard_client(monkeypatch, output: str):
    def fake_build_client(cfg):
        return StubLLM(output)
    monkeypatch.setattr("dzmm.api.routes_wizard.build_client", fake_build_client)


async def test_post_world_brief_endpoint(http, monkeypatch):
    mid = await _make_model_config(http)
    _patch_wizard_client(monkeypatch, _BRIEF_OUTPUT)
    r = await http.post("/wizard/world_brief", json={
        "model_config_id": mid, "genre": "赛博朋克", "theme": "记忆与身份",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["name"] == "赛博九龙"
    assert "2089" in body["setting"]
    assert "共感协议" in body["conflict"]


async def test_post_world_details_endpoint(http, monkeypatch):
    mid = await _make_model_config(http)
    _patch_wizard_client(monkeypatch, _DETAILS_OUTPUT)
    r = await http.post("/wizard/world_details", json={
        "model_config_id": mid, "brief_md": "已确认的 brief",
    })
    assert r.status_code == 200, r.text
    assert "九龙天井" in r.json()["world_md"]


async def test_post_character_endpoint(http, monkeypatch):
    mid = await _make_model_config(http)
    _patch_wizard_client(monkeypatch, _CHAR_OUTPUT)
    r = await http.post("/wizard/character", json={
        "model_config_id": mid, "world_md": "world", "archetype": "黑客",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["name"] == "林默"
    assert "神经入侵" in body["profile_md"]


async def test_post_npcs_endpoint(http, monkeypatch):
    mid = await _make_model_config(http)
    _patch_wizard_client(monkeypatch, _NPC_OUTPUT)
    r = await http.post("/wizard/npcs", json={
        "model_config_id": mid, "world_md": "w", "character_md": "c",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["npcs"]) == 3


async def test_post_screenplay_endpoint(http, monkeypatch):
    mid = await _make_model_config(http)
    _patch_wizard_client(monkeypatch, _SCREENPLAY_OUTPUT)
    r = await http.post("/wizard/screenplay", json={
        "model_config_id": mid,
        "world_md": "w",
        "character_md": "c",
        "npcs": [{"name": "陈子轩", "role": "盟友",
                  "description": "前 SWAT", "motivation": "复仇"}],
        "genre": "悬疑探案",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["chapters"]) == 2
    assert "雨夜" in body["opening_hook"]


async def test_post_finalize_endpoint(http, app):
    # Seed model configs via API so we have valid IDs.
    mid = await _make_model_config(http)
    bundle = {
        "world": {"name": "赛博九龙", "content_md": "霓虹永不熄灭", "style": "dark"},
        "character": {
            "name": "林默",
            "profile_md": "黑客",
            "base_stats_json": '{"hp":20}',
        },
        "pinned_npcs": [
            {"name": "陈子轩", "role": "盟友",
             "description": "前 SWAT", "motivation": "复仇"},
        ],
        "screenplay": {
            "chapters": [{"title": "第一章", "summary": "x", "main_events": [],
                          "optional_events": [], "main_npcs": []}],
            "main_characters": [],
            "ending_md": "销毁协议",
            "opening_hook": "雨夜电话",
        },
        "session_name": "九龙之雨",
        "gm_model_config_id": mid,
        "summarizer_model_config_id": mid,
        "genre": "赛博朋克",
    }
    r = await http.post("/wizard/finalize", json=bundle)
    assert r.status_code == 200, r.text
    sid = r.json()["session_id"]
    assert isinstance(sid, int)

    # Verify session is fetchable through the regular API.
    r = await http.get(f"/sessions/{sid}")
    assert r.status_code == 200
    assert r.json()["name"] == "九龙之雨"

    # Verify NPC was created.
    r = await http.get(f"/sessions/{sid}/npcs")
    assert r.status_code == 200
    npcs = r.json()
    assert any(n["name"] == "陈子轩" and n["pinned"] is True for n in npcs)


async def test_post_finalize_rejects_invalid_bundle(http):
    r = await http.post("/wizard/finalize", json={"world": {"name": "x"}})
    assert r.status_code == 400


async def test_world_brief_404_when_model_missing(http, monkeypatch):
    _patch_wizard_client(monkeypatch, _BRIEF_OUTPUT)
    r = await http.post("/wizard/world_brief", json={
        "model_config_id": 99999, "genre": "x", "theme": "y",
    })
    assert r.status_code == 404


# ============================================================================
# _with_retry + fallback / default archetype (v0.2.4 T1)
# ============================================================================

@pytest.mark.asyncio
async def test_with_retry_succeeds_on_first():
    calls = []
    async def fn():
        calls.append(1)
        return "ok"
    result = await _with_retry(fn, max_attempts=3)
    assert result == "ok"
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_with_retry_retries_on_value_error():
    calls = []
    async def fn():
        calls.append(1)
        if len(calls) < 3:
            raise ValueError("bad format")
        return "ok"
    result = await _with_retry(fn, max_attempts=3)
    assert result == "ok"
    assert len(calls) == 3


@pytest.mark.asyncio
async def test_with_retry_raises_after_max():
    async def fn():
        raise ValueError("always bad")
    with pytest.raises(ValueError, match="always bad"):
        await _with_retry(fn, max_attempts=3)


@pytest.mark.asyncio
async def test_generate_world_brief_fallback_when_parse_fails():
    """If _parse_section finds no matching headers, raw_md is always populated."""
    raw = "The world has no proper headers, just freeform text about the world."
    client = StubLLM(raw)
    result = await generate_world_brief("悬疑", "侦探题材", client)
    assert result["raw_md"] == raw
    assert isinstance(result["name"], str)
    assert isinstance(result["setting"], str)
    assert isinstance(result["conflict"], str)


@pytest.mark.asyncio
async def test_generate_character_uses_default_archetype_when_empty():
    """Empty archetype → uses fallback string, does not raise."""
    profile = "## 基本信息\n姓名：张三\n\n## 背景\n平凡侦探"
    client = StubLLM(profile)
    result = await generate_character("赛博朋克世界", "", client)
    assert result["name"] == "张三"
    assert "基本信息" in result["profile_md"]


# ============================================================================
# generate_single_npc (v0.2.4 T2)
# ============================================================================

class _FakeClient(ModelClient):
    """Returns responses from a list, one per stream() call."""
    name = "fake-sequence"

    def __init__(self, responses: list[str]):
        self._responses = list(responses)
        self._idx = 0

    async def stream(
        self, messages: list[Message], params: GenerationParams
    ) -> AsyncIterator[StreamChunk]:
        text = self._responses[self._idx % len(self._responses)]
        self._idx += 1
        yield StreamChunk(delta=text)
        yield StreamChunk(
            delta="",
            finish_reason="stop",
            usage=TokenUsage(input_tokens=10, output_tokens=40),
        )


@pytest.mark.asyncio
async def test_generate_single_npc_returns_npc_dict():
    """generate_single_npc parses a valid JSON NPC response."""
    npc_json = '{"name": "王五", "description": "神秘商人", "archetype": "商人", "purpose": "提供线索"}'
    client = _FakeClient([npc_json])
    result = await generate_single_npc("赛博朋克世界", "主角档案", "黑市商人", client)
    assert result["name"] == "王五"
    assert result["archetype"] == "商人"


@pytest.mark.asyncio
async def test_generate_single_npc_retries_on_bad_json():
    """generate_single_npc retries when LLM returns invalid JSON."""
    responses = ["not json at all", '{"name": "李四", "description": "守门人", "archetype": "盟友", "purpose": "开门"}']
    client = _FakeClient(responses)
    result = await generate_single_npc("世界", "主角", "守门人", client)
    assert result["name"] == "李四"
