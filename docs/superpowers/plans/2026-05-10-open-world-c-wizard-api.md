# Open World Framework — Plan C: Wizard API (8-Step WorldFramework Generation)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add 8 new Wizard API endpoints that generate a `WorldFramework` (locations → factions → NPC templates → events → optional campaign → character) and a new `finalize_framework` endpoint that atomically creates `WorldFramework` + all child records + `Session` with `framework_id` set.

**Architecture:** Each generation step is a stateless POST that takes `model_config_id` + context and returns structured JSON. All prompts live in separate `wizard_*.py` files following existing conventions. A new `wizard_framework.py` service file handles generation + DB finalization. Old `wizard.py` and its routes are left intact for legacy sessions.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy async, pytest-asyncio

**Prerequisites:** Plan A (DB models) must be merged.

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `backend/src/dzmm/prompts/wizard_locations.py` | Create | Location network generation prompt |
| `backend/src/dzmm/prompts/wizard_factions_fw.py` | Create | Faction template generation prompt |
| `backend/src/dzmm/prompts/wizard_npc_templates.py` | Create | NPC template generation prompt |
| `backend/src/dzmm/prompts/wizard_events_fw.py` | Create | Event library generation prompt |
| `backend/src/dzmm/prompts/wizard_campaign_fw.py` | Create | Campaign phase generation prompt |
| `backend/src/dzmm/service/wizard_framework.py` | Create | Generation functions + `finalize_framework` |
| `backend/src/dzmm/api/routes_wizard.py` | Modify | Add 8 new `/wizard/fw/*` endpoints |
| `backend/tests/test_wizard_framework.py` | Create | Unit tests for generation + finalize |

---

### Task 1: wizard_locations prompt + generate_locations service function

**Files:**
- Create: `backend/src/dzmm/prompts/wizard_locations.py`
- Create: `backend/src/dzmm/service/wizard_framework.py`
- Create: `backend/tests/test_wizard_framework.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_wizard_framework.py
import json
import pytest
from unittest.mock import AsyncMock, MagicMock
from dzmm.models.client import TokenUsage


class _FakeClient:
    def __init__(self, response: str):
        self._response = response
    async def complete(self, messages, params):
        return self._response, TokenUsage()
    async def stream(self, messages, params):
        from dzmm.models.client import StreamChunk
        yield StreamChunk(delta=self._response, finish_reason="stop")


LOCATIONS_JSON = json.dumps([
    {"name": "暗影港", "description_md": "阴暗的港口城市。", "location_type": "city",
     "connections": [{"target_name": "迷雾森林", "direction": "north", "distance": 1, "travel_turns": 2}],
     "initial_state": "normal"},
    {"name": "迷雾森林", "description_md": "雾气弥漫的森林。", "location_type": "wilderness",
     "connections": [{"target_name": "暗影港", "direction": "south", "distance": 1, "travel_turns": 2}],
     "initial_state": "normal"},
])


async def test_generate_locations_returns_list():
    from dzmm.service.wizard_framework import generate_locations
    client = _FakeClient(LOCATIONS_JSON)
    result = await generate_locations(
        genre="悬疑", world_brief_md="一个阴暗的维多利亚时代城市。", client=client
    )
    assert isinstance(result, list)
    assert len(result) == 2
    assert result[0]["name"] == "暗影港"
    assert "connections" in result[0]
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && uv run pytest tests/test_wizard_framework.py::test_generate_locations_returns_list -v
```

Expected: `FAILED` — `ModuleNotFoundError`

- [ ] **Step 3: Create wizard_locations.py prompt**

```python
# backend/src/dzmm/prompts/wizard_locations.py
from __future__ import annotations
from dzmm.models.client import Message

_SYSTEM = """你是开放世界 TRPG 的地图设计师。根据世界设定，生成地点网络。

输出严格为 JSON 数组，不加 markdown 围栏，不加注释：
[
  {
    "name": "地点名称",
    "description_md": "2-4句简介",
    "location_type": "city|dungeon|wilderness|landmark",
    "connections": [
      {"target_name": "连接地点名", "direction": "north|south|east|west|up|down|portal", "distance": 1, "travel_turns": 1}
    ],
    "initial_state": "normal"
  }
]

要求：
- 生成 6-10 个地点
- 每个地点至少有 1 个连接
- 连接必须双向出现（A→B 则 B→A）
- distance: 1=相邻, 2=较近, 3+=较远
- 包含多种类型地点（城市/野外/地下城/地标）
"""


def build_locations_messages(genre: str, world_brief_md: str) -> list[Message]:
    return [
        Message(role="system", content=_SYSTEM),
        Message(
            role="user",
            content=f"类型：{genre}\n\n世界简介：\n{world_brief_md}\n\n请生成地点网络 JSON 数组。",
        ),
    ]
```

- [ ] **Step 4: Create wizard_framework.py with generate_locations**

```python
# backend/src/dzmm/service/wizard_framework.py
"""Open-world Wizard service — generates WorldFramework layer-by-layer.

Each function takes a ModelClient + context and returns parsed Python objects.
finalize_framework() commits everything to DB atomically.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.models.client import GenerationParams, ModelClient
from dzmm.prompts.wizard_locations import build_locations_messages

log = logging.getLogger(__name__)

_PARAMS = GenerationParams(temperature=0.7, max_tokens=4096)

_FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)
_TRAILING_COMMA_RE = re.compile(r",\s*([}\]])")


def _extract_json(text: str) -> str:
    text = text.strip()
    m = _FENCE_RE.match(text)
    if m:
        text = m.group(1).strip()
    obj = text.find("{")
    arr = text.find("[")
    if arr != -1 and (obj == -1 or arr < obj):
        end = text.rfind("]")
        if end != -1:
            text = text[arr:end+1]
    elif obj != -1:
        end = text.rfind("}")
        if end != -1:
            text = text[obj:end+1]
    text = _TRAILING_COMMA_RE.sub(r"\1", text)
    return text


async def generate_locations(
    genre: str, world_brief_md: str, client: ModelClient
) -> list[dict]:
    msgs = build_locations_messages(genre, world_brief_md)
    raw, _ = await client.complete(msgs, _PARAMS)
    return json.loads(_extract_json(raw))
```

- [ ] **Step 5: Run test to verify it passes**

```bash
cd backend && uv run pytest tests/test_wizard_framework.py::test_generate_locations_returns_list -v
```

Expected: `PASSED`

- [ ] **Step 6: Commit**

```bash
git add backend/src/dzmm/prompts/wizard_locations.py backend/src/dzmm/service/wizard_framework.py backend/tests/test_wizard_framework.py
git commit -m "feat(wizard): generate_locations + prompt (step 2)"
```

---

### Task 2: Factions, NPC templates, Events prompts + service functions

**Files:**
- Create: `backend/src/dzmm/prompts/wizard_factions_fw.py`
- Create: `backend/src/dzmm/prompts/wizard_npc_templates.py`
- Create: `backend/src/dzmm/prompts/wizard_events_fw.py`
- Modify: `backend/src/dzmm/service/wizard_framework.py`
- Modify: `backend/tests/test_wizard_framework.py`

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_wizard_framework.py`:

```python
FACTIONS_JSON = json.dumps([
    {"name": "暗夜公会", "description_md": "控制地下经济的秘密组织。",
     "rival_faction_names": ["教会"], "ally_faction_names": [],
     "tension_rules": {"passive_gain_per_turn": 1, "threshold_conflict": 80}},
    {"name": "教会", "description_md": "维护秩序的宗教势力。",
     "rival_faction_names": ["暗夜公会"], "ally_faction_names": [],
     "tension_rules": {"passive_gain_per_turn": 0, "threshold_conflict": 90}},
])

NPC_TEMPLATES_JSON = json.dumps([
    {"name": "李影", "gender": "female", "role": "公会密探",
     "description_md": "冷静多疑。", "motivation": "保护组织机密",
     "home_location_name": "暗影港", "faction_name": "暗夜公会",
     "contact_favor_threshold": 70, "contact_cooldown_turns": 10},
])

EVENTS_JSON = json.dumps([
    {"name": "港口谋杀案", "summary_md": "港口发现神秘尸体。",
     "scope_type": "location", "scope_location_name": "暗影港", "importance": 3,
     "trigger_conditions": [{"type": "location", "location_name": "暗影港"}],
     "is_repeatable": False, "cooldown_turns": 0},
])


async def test_generate_factions_returns_list():
    from dzmm.service.wizard_framework import generate_factions
    client = _FakeClient(FACTIONS_JSON)
    result = await generate_factions(
        genre="悬疑", world_brief_md="维多利亚城市", locations=[], client=client
    )
    assert len(result) == 2
    assert result[0]["name"] == "暗夜公会"


async def test_generate_npc_templates_returns_list():
    from dzmm.service.wizard_framework import generate_npc_templates
    client = _FakeClient(NPC_TEMPLATES_JSON)
    result = await generate_npc_templates(
        genre="悬疑", world_brief_md="维多利亚城市",
        locations=[], factions=[], client=client,
    )
    assert len(result) == 1
    assert result[0]["gender"] == "female"


async def test_generate_events_returns_list():
    from dzmm.service.wizard_framework import generate_events
    client = _FakeClient(EVENTS_JSON)
    result = await generate_events(
        genre="悬疑", world_brief_md="维多利亚城市",
        locations=[], factions=[], npc_templates=[], client=client,
    )
    assert len(result) == 1
    assert result[0]["importance"] == 3
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && uv run pytest tests/test_wizard_framework.py -k "factions or npc_templates or events" -v
```

Expected: `FAILED` — `ImportError`

- [ ] **Step 3: Create the three prompt files**

```python
# backend/src/dzmm/prompts/wizard_factions_fw.py
from dzmm.models.client import Message

_SYSTEM = """你是开放世界 TRPG 的世界设计师，负责设计势力体系。

输出严格为 JSON 数组：
[
  {
    "name": "势力名",
    "description_md": "2-3句介绍，包括目标和手段",
    "rival_faction_names": ["对立势力名"],
    "ally_faction_names": ["盟友势力名"],
    "tension_rules": {"passive_gain_per_turn": 0, "threshold_conflict": 80}
  }
]

要求：3-5个势力；至少有 1 对对立关系；tension_rules.passive_gain_per_turn 通常 0-2。
"""

def build_factions_messages(genre: str, world_brief_md: str, location_names: list[str]) -> list[Message]:
    locs = "、".join(location_names) if location_names else "无"
    return [
        Message(role="system", content=_SYSTEM),
        Message(role="user", content=f"类型：{genre}\n世界：{world_brief_md}\n主要地点：{locs}\n\n请生成势力 JSON 数组。"),
    ]
```

```python
# backend/src/dzmm/prompts/wizard_npc_templates.py
from dzmm.models.client import Message

_SYSTEM = """你是开放世界 TRPG 的角色设计师，负责设计 NPC 模板库。

输出严格为 JSON 数组：
[
  {
    "name": "NPC名",
    "gender": "male|female",
    "role": "职业/身份",
    "description_md": "2-3句外貌和性格",
    "motivation": "一句话动机",
    "home_location_name": "主要驻留地点名",
    "faction_name": "所属势力名或null",
    "contact_favor_threshold": 70,
    "contact_cooldown_turns": 10
  }
]

要求：8-12个NPC；覆盖多个势力；包含盟友/中立/潜在敌对三类。
"""

def build_npc_templates_messages(genre: str, world_brief_md: str, location_names: list[str], faction_names: list[str]) -> list[Message]:
    return [
        Message(role="system", content=_SYSTEM),
        Message(role="user", content=f"类型：{genre}\n世界：{world_brief_md}\n地点：{', '.join(location_names)}\n势力：{', '.join(faction_names)}\n\n请生成NPC模板 JSON 数组。"),
    ]
```

```python
# backend/src/dzmm/prompts/wizard_events_fw.py
from dzmm.models.client import Message

_SYSTEM = """你是开放世界 TRPG 的事件设计师，负责设计事件库。

输出严格为 JSON 数组：
[
  {
    "name": "事件名",
    "summary_md": "2-3句描述",
    "scope_type": "location|faction|global",
    "scope_location_name": "地点名（scope_type=location时填）",
    "scope_faction_name": "势力名（scope_type=faction时填）",
    "importance": 1-5,
    "trigger_conditions": [
      {"type": "location", "location_name": "地点名"},
      {"type": "npc_met", "npc_name": "NPC名"},
      {"type": "stat_gte", "stat": "属性名", "value": N},
      {"type": "event_done", "event_name": "事件名"},
      {"type": "faction_rep", "faction_name": "势力名", "op": "gte", "value": N}
    ],
    "is_repeatable": false,
    "cooldown_turns": 0
  }
]

要求：15-25个事件；importance 分布：1-2=次要(40%), 3=普通(40%), 4-5=重要(20%)；
trigger_conditions 为空列表表示随时可触发；多个条件为AND逻辑。
"""

def build_events_messages(genre: str, world_brief_md: str, location_names: list[str], faction_names: list[str], npc_names: list[str]) -> list[Message]:
    return [
        Message(role="system", content=_SYSTEM),
        Message(role="user", content=f"类型：{genre}\n世界：{world_brief_md}\n地点：{', '.join(location_names)}\n势力：{', '.join(faction_names)}\nNPC：{', '.join(npc_names)}\n\n请生成事件库 JSON 数组。"),
    ]
```

- [ ] **Step 4: Add the three generate functions to wizard_framework.py**

Append to `wizard_framework.py` after `generate_locations`:

```python
from dzmm.prompts.wizard_factions_fw import build_factions_messages
from dzmm.prompts.wizard_npc_templates import build_npc_templates_messages
from dzmm.prompts.wizard_events_fw import build_events_messages


async def generate_factions(
    genre: str, world_brief_md: str, locations: list[dict], client: ModelClient
) -> list[dict]:
    location_names = [l["name"] for l in locations]
    msgs = build_factions_messages(genre, world_brief_md, location_names)
    raw, _ = await client.complete(msgs, _PARAMS)
    return json.loads(_extract_json(raw))


async def generate_npc_templates(
    genre: str, world_brief_md: str, locations: list[dict],
    factions: list[dict], client: ModelClient,
) -> list[dict]:
    location_names = [l["name"] for l in locations]
    faction_names = [f["name"] for f in factions]
    msgs = build_npc_templates_messages(genre, world_brief_md, location_names, faction_names)
    raw, _ = await client.complete(msgs, _PARAMS)
    return json.loads(_extract_json(raw))


async def generate_events(
    genre: str, world_brief_md: str, locations: list[dict],
    factions: list[dict], npc_templates: list[dict], client: ModelClient,
) -> list[dict]:
    location_names = [l["name"] for l in locations]
    faction_names = [f["name"] for f in factions]
    npc_names = [n["name"] for n in npc_templates]
    msgs = build_events_messages(genre, world_brief_md, location_names, faction_names, npc_names)
    raw, _ = await client.complete(msgs, _PARAMS)
    return json.loads(_extract_json(raw))
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd backend && uv run pytest tests/test_wizard_framework.py -k "factions or npc_templates or events" -v
```

Expected: 3 tests `PASSED`

- [ ] **Step 6: Commit**

```bash
git add backend/src/dzmm/prompts/wizard_factions_fw.py backend/src/dzmm/prompts/wizard_npc_templates.py backend/src/dzmm/prompts/wizard_events_fw.py backend/src/dzmm/service/wizard_framework.py backend/tests/test_wizard_framework.py
git commit -m "feat(wizard): generate_factions, generate_npc_templates, generate_events (steps 3-5)"
```

---

### Task 3: Campaign prompt + generate_campaign + finalize_framework

**Files:**
- Create: `backend/src/dzmm/prompts/wizard_campaign_fw.py`
- Modify: `backend/src/dzmm/service/wizard_framework.py`
- Modify: `backend/tests/test_wizard_framework.py`

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_wizard_framework.py`:

```python
CAMPAIGN_JSON = json.dumps({
    "name": "暗影之战",
    "phases": [
        {"phase_id": 1, "name": "序章", "description": "调查谋杀案。",
         "prerequisite_phase_ids": [], "key_event_names": ["港口谋杀案"], "required_count": 1},
    ],
})


async def test_generate_campaign_returns_dict():
    from dzmm.service.wizard_framework import generate_campaign
    client = _FakeClient(CAMPAIGN_JSON)
    result = await generate_campaign(
        genre="悬疑", world_brief_md="城市",
        events=[{"name": "港口谋杀案", "importance": 3}], client=client,
    )
    assert result["name"] == "暗影之战"
    assert len(result["phases"]) == 1
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && uv run pytest tests/test_wizard_framework.py::test_generate_campaign_returns_dict -v
```

Expected: `FAILED` — `ImportError`

- [ ] **Step 3: Create wizard_campaign_fw.py**

```python
# backend/src/dzmm/prompts/wizard_campaign_fw.py
from dzmm.models.client import Message

_SYSTEM = """你是开放世界 TRPG 的主线剧情设计师。生成可选的主线剧情框架。

输出严格为 JSON 对象：
{
  "name": "主线名称",
  "phases": [
    {
      "phase_id": 1,
      "name": "阶段名",
      "description": "1-2句阶段概述",
      "prerequisite_phase_ids": [],
      "key_event_names": ["关键事件名1", "关键事件名2"],
      "required_count": 1
    }
  ]
}

要求：3-5个阶段；每阶段 required_count ≤ len(key_event_names)；
key_event_names 只能使用提供的事件名列表中的名字。
"""

def build_campaign_messages(genre: str, world_brief_md: str, event_summaries: list[dict]) -> list[Message]:
    ev_list = "\n".join(f"  - {e['name']}（重要性={e.get('importance',2)}）" for e in event_summaries)
    return [
        Message(role="system", content=_SYSTEM),
        Message(role="user", content=f"类型：{genre}\n世界：{world_brief_md}\n\n可用事件：\n{ev_list}\n\n请生成主线框架 JSON。"),
    ]
```

- [ ] **Step 4: Add generate_campaign to wizard_framework.py**

```python
from dzmm.prompts.wizard_campaign_fw import build_campaign_messages


async def generate_campaign(
    genre: str, world_brief_md: str, events: list[dict], client: ModelClient
) -> dict:
    event_summaries = [{"name": e["name"], "importance": e.get("importance", 2)} for e in events]
    msgs = build_campaign_messages(genre, world_brief_md, event_summaries)
    raw, _ = await client.complete(msgs, _PARAMS)
    return json.loads(_extract_json(raw))
```

- [ ] **Step 5: Write finalize_framework test**

Add to `backend/tests/test_wizard_framework.py`:

```python
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from dzmm.db.base import Base
from dzmm.db import models as _models  # noqa: F401


@pytest.fixture
async def fresh_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = async_sessionmaker(engine, expire_on_commit=False)
    async with sm() as s:
        yield s
    await engine.dispose()


async def test_finalize_framework_creates_records(fresh_db):
    from dzmm.service.wizard_framework import finalize_framework
    from dzmm.db.models import WorldFramework, WorldLocation, WorldFaction, WorldNPCTemplate, WorldEvent

    payload = {
        "name": "测试世界",
        "genre": "悬疑",
        "style": "noir",
        "description_md": "城市背景。",
        "locations": [
            {"name": "港口", "description_md": "港口区。", "location_type": "city",
             "connections": [], "initial_state": "normal"},
        ],
        "factions": [
            {"name": "公会", "description_md": "黑市。",
             "rival_faction_names": [], "ally_faction_names": [],
             "tension_rules": {"passive_gain_per_turn": 1, "threshold_conflict": 80}},
        ],
        "npc_templates": [
            {"name": "李影", "gender": "female", "role": "密探",
             "description_md": "冷静。", "motivation": "保密",
             "home_location_name": "港口", "faction_name": "公会",
             "contact_favor_threshold": 70, "contact_cooldown_turns": 10},
        ],
        "events": [
            {"name": "谋杀案", "summary_md": "尸体。", "scope_type": "location",
             "scope_location_name": "港口", "importance": 3,
             "trigger_conditions": [], "is_repeatable": False, "cooldown_turns": 0},
        ],
        "campaign": None,
    }
    framework_id = await finalize_framework(fresh_db, payload)
    assert framework_id > 0

    fw = await fresh_db.get(WorldFramework, framework_id)
    assert fw.name == "测试世界"

    locs = (await fresh_db.execute(
        __import__("sqlalchemy").select(WorldLocation).where(WorldLocation.framework_id == framework_id)
    )).scalars().all()
    assert len(locs) == 1
    assert locs[0].name == "港口"

    npcs = (await fresh_db.execute(
        __import__("sqlalchemy").select(WorldNPCTemplate).where(WorldNPCTemplate.framework_id == framework_id)
    )).scalars().all()
    assert len(npcs) == 1
    assert npcs[0].home_location_id == locs[0].id
```

- [ ] **Step 6: Run test to verify it fails**

```bash
cd backend && uv run pytest tests/test_wizard_framework.py::test_finalize_framework_creates_records -v
```

Expected: `FAILED` — `ImportError: cannot import name 'finalize_framework'`

- [ ] **Step 7: Implement finalize_framework in wizard_framework.py**

```python
from dzmm.db.models import (
    WorldFramework,
    WorldLocation,
    WorldFaction,
    WorldNPCTemplate,
    WorldEvent,
    Campaign,
)


async def finalize_framework(s: AsyncSession, payload: dict) -> int:
    """Atomically create WorldFramework and all child records from wizard payload.

    Returns the new WorldFramework.id.
    Names in connections/scope/home_location/faction are resolved to IDs after insert.
    """
    fw = WorldFramework(
        name=payload["name"],
        genre=payload.get("genre", ""),
        style=payload.get("style", ""),
        description_md=payload.get("description_md", ""),
    )
    s.add(fw)
    await s.flush()  # assign fw.id

    # --- Locations (first pass, no connections yet) ---
    loc_name_to_id: dict[str, int] = {}
    loc_rows: list[WorldLocation] = []
    for loc_data in payload.get("locations", []):
        loc = WorldLocation(
            framework_id=fw.id,
            name=loc_data["name"],
            description_md=loc_data.get("description_md", ""),
            location_type=loc_data.get("location_type", "city"),
            connections_json="[]",
            initial_state=loc_data.get("initial_state", "normal"),
        )
        s.add(loc)
        loc_rows.append(loc)
    await s.flush()
    for loc, loc_data in zip(loc_rows, payload.get("locations", [])):
        loc_name_to_id[loc.name] = loc.id

    # Second pass: wire up connections_json with resolved IDs
    for loc, loc_data in zip(loc_rows, payload.get("locations", [])):
        resolved = []
        for conn in loc_data.get("connections", []):
            target_id = loc_name_to_id.get(conn.get("target_name", ""))
            if target_id:
                resolved.append({
                    "target_id": target_id,
                    "direction": conn.get("direction", ""),
                    "distance": conn.get("distance", 1),
                    "travel_turns": conn.get("travel_turns", 1),
                })
        loc.connections_json = json.dumps(resolved, ensure_ascii=False)

    # --- Factions ---
    faction_name_to_id: dict[str, int] = {}
    for f_data in payload.get("factions", []):
        faction = WorldFaction(
            framework_id=fw.id,
            name=f_data["name"],
            description_md=f_data.get("description_md", ""),
            rival_factions_json=json.dumps(f_data.get("rival_faction_names", []), ensure_ascii=False),
            ally_factions_json=json.dumps(f_data.get("ally_faction_names", []), ensure_ascii=False),
            tension_rules_json=json.dumps(f_data.get("tension_rules", {}), ensure_ascii=False),
        )
        s.add(faction)
        await s.flush()
        faction_name_to_id[faction.name] = faction.id

    # --- NPC Templates ---
    npc_name_to_id: dict[str, int] = {}
    for n_data in payload.get("npc_templates", []):
        home_id = loc_name_to_id.get(n_data.get("home_location_name", ""))
        faction_id = faction_name_to_id.get(n_data.get("faction_name", ""))
        npc = WorldNPCTemplate(
            framework_id=fw.id,
            name=n_data["name"],
            gender=n_data.get("gender", ""),
            role=n_data.get("role", ""),
            description_md=n_data.get("description_md", ""),
            motivation=n_data.get("motivation", ""),
            home_location_id=home_id,
            faction_id=faction_id,
            contact_favor_threshold=n_data.get("contact_favor_threshold", 70),
            contact_cooldown_turns=n_data.get("contact_cooldown_turns", 10),
        )
        s.add(npc)
        await s.flush()
        npc_name_to_id[npc.name] = npc.id

    # --- Events (resolve name refs to IDs in trigger_conditions) ---
    event_name_to_id: dict[str, int] = {}
    for e_data in payload.get("events", []):
        scope_ref = ""
        if e_data.get("scope_type") == "location":
            scope_ref = str(loc_name_to_id.get(e_data.get("scope_location_name", ""), ""))
        elif e_data.get("scope_type") == "faction":
            scope_ref = str(faction_name_to_id.get(e_data.get("scope_faction_name", ""), ""))

        # Resolve trigger_conditions name refs → IDs
        conds = []
        for cond in e_data.get("trigger_conditions", []):
            resolved_cond = dict(cond)
            if cond.get("type") == "location" and "location_name" in cond:
                resolved_cond["value"] = loc_name_to_id.get(cond["location_name"], 0)
                del resolved_cond["location_name"]
            elif cond.get("type") == "npc_met" and "npc_name" in cond:
                resolved_cond["value"] = npc_name_to_id.get(cond["npc_name"], 0)
                del resolved_cond["npc_name"]
            elif cond.get("type") == "faction_rep" and "faction_name" in cond:
                resolved_cond["faction_id"] = faction_name_to_id.get(cond["faction_name"], 0)
                del resolved_cond["faction_name"]
            conds.append(resolved_cond)

        event = WorldEvent(
            framework_id=fw.id,
            name=e_data["name"],
            summary_md=e_data.get("summary_md", ""),
            scope_type=e_data.get("scope_type", "global"),
            scope_ref=scope_ref,
            importance=e_data.get("importance", 2),
            trigger_conditions_json=json.dumps(conds, ensure_ascii=False),
            is_repeatable=e_data.get("is_repeatable", False),
            cooldown_turns=e_data.get("cooldown_turns", 0),
        )
        s.add(event)
        await s.flush()
        event_name_to_id[event.name] = event.id

    # --- Campaign (optional) ---
    campaign_data = payload.get("campaign")
    if campaign_data:
        phases = []
        for ph in campaign_data.get("phases", []):
            key_ids = [event_name_to_id[n] for n in ph.get("key_event_names", []) if n in event_name_to_id]
            phases.append({
                "phase_id": ph["phase_id"],
                "name": ph["name"],
                "description": ph.get("description", ""),
                "prerequisite_phase_ids": ph.get("prerequisite_phase_ids", []),
                "key_event_ids": key_ids,
                "required_count": ph.get("required_count", 1),
            })
        campaign = Campaign(
            framework_id=fw.id,
            name=campaign_data["name"],
            phases_json=json.dumps(phases, ensure_ascii=False),
        )
        s.add(campaign)

    await s.commit()
    return fw.id
```

- [ ] **Step 8: Run all wizard_framework tests**

```bash
cd backend && uv run pytest tests/test_wizard_framework.py -v
```

Expected: All tests `PASSED`

- [ ] **Step 9: Commit**

```bash
git add backend/src/dzmm/prompts/wizard_campaign_fw.py backend/src/dzmm/service/wizard_framework.py backend/tests/test_wizard_framework.py
git commit -m "feat(wizard): generate_campaign + finalize_framework with full name→ID resolution"
```

---

### Task 4: Add /wizard/fw/* API endpoints

**Files:**
- Modify: `backend/src/dzmm/api/routes_wizard.py`

- [ ] **Step 1: Identify insertion point**

```bash
tail -20 backend/src/dzmm/api/routes_wizard.py
```

- [ ] **Step 2: Add imports and 7 new endpoints to routes_wizard.py**

Append after the last existing endpoint in `routes_wizard.py`:

```python
# ── Open-World Framework Wizard endpoints (/wizard/fw/*) ─────────────
from dzmm.service.wizard_framework import (
    generate_locations,
    generate_factions,
    generate_npc_templates,
    generate_events,
    generate_campaign,
    finalize_framework,
)


@router.post("/fw/locations")
async def fw_locations(payload: dict, s: AsyncSession = Depends(get_session_dep)):
    """Step 2: Generate location network from world brief."""
    client = await _client_for(s, _require_int(payload, "model_config_id"))
    return await generate_locations(
        genre=str(payload.get("genre", "")),
        world_brief_md=str(payload.get("world_brief_md", "")),
        client=client,
    )


@router.post("/fw/factions")
async def fw_factions(payload: dict, s: AsyncSession = Depends(get_session_dep)):
    """Step 3: Generate factions from world brief + locations."""
    client = await _client_for(s, _require_int(payload, "model_config_id"))
    return await generate_factions(
        genre=str(payload.get("genre", "")),
        world_brief_md=str(payload.get("world_brief_md", "")),
        locations=payload.get("locations", []),
        client=client,
    )


@router.post("/fw/npc_templates")
async def fw_npc_templates(payload: dict, s: AsyncSession = Depends(get_session_dep)):
    """Step 4: Generate NPC templates from world + locations + factions."""
    client = await _client_for(s, _require_int(payload, "model_config_id"))
    return await generate_npc_templates(
        genre=str(payload.get("genre", "")),
        world_brief_md=str(payload.get("world_brief_md", "")),
        locations=payload.get("locations", []),
        factions=payload.get("factions", []),
        client=client,
    )


@router.post("/fw/events")
async def fw_events(payload: dict, s: AsyncSession = Depends(get_session_dep)):
    """Step 5: Generate event library."""
    client = await _client_for(s, _require_int(payload, "model_config_id"))
    return await generate_events(
        genre=str(payload.get("genre", "")),
        world_brief_md=str(payload.get("world_brief_md", "")),
        locations=payload.get("locations", []),
        factions=payload.get("factions", []),
        npc_templates=payload.get("npc_templates", []),
        client=client,
    )


@router.post("/fw/campaign")
async def fw_campaign(payload: dict, s: AsyncSession = Depends(get_session_dep)):
    """Step 7 (optional): Generate campaign main-plot phases."""
    client = await _client_for(s, _require_int(payload, "model_config_id"))
    return await generate_campaign(
        genre=str(payload.get("genre", "")),
        world_brief_md=str(payload.get("world_brief_md", "")),
        events=payload.get("events", []),
        client=client,
    )


@router.post("/fw/finalize")
async def fw_finalize(payload: dict, s: AsyncSession = Depends(get_session_dep)):
    """Step 8: Commit WorldFramework to DB. Returns {framework_id}."""
    framework_id = await finalize_framework(s, payload)
    return {"framework_id": framework_id}
```

- [ ] **Step 3: Run full test suite**

```bash
cd backend && uv run pytest tests/ -v --tb=short 2>&1 | tail -20
```

Expected: All tests pass.

- [ ] **Step 4: Commit**

```bash
git add backend/src/dzmm/api/routes_wizard.py
git commit -m "feat(wizard): add /wizard/fw/* endpoints (steps 2-8)"
```

---

### Task 5: Cleanup — mark old Screenplay wizard routes deprecated

The old `/wizard/screenplay` and `/wizard/finalize` endpoints still work for legacy sessions. Add a deprecation note; full removal happens when frontend no longer calls them.

- [ ] **Step 1: Add deprecation comment in routes_wizard.py**

Find the `@router.post("/finalize")` endpoint and add above it:

```python
# DEPRECATED(Plan-D): Old Screenplay-based wizard finalize.
# Remove once WizardView.vue fully migrates to /wizard/fw/* flow.
```

- [ ] **Step 2: Commit**

```bash
git add backend/src/dzmm/api/routes_wizard.py
git commit -m "chore: mark old /wizard/finalize as deprecated (removal in Plan D)"
```
