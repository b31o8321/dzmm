# Open World Framework — Plan B: Director Agent (Spatial Events)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the screenplay-chapter–based Director with an open-world Director that scores nearby `WorldEvent`s using a spatial distance formula, delivers far-away events as rumors, and triggers proactive NPC contact via `SessionNpcState.favor`.

**Architecture:** New Director path lives in `director_open_world.py`; `orchestrator.py` checks `session.framework_id` to dispatch the right path. The spatial graph (BFS over `WorldLocation.connections_json`) lives in `world_graph.py`. Rumor and NPC-contact logic are pure functions, easily unit-tested. The old Director (`director.py`) is untouched — it serves sessions without `framework_id`.

**Tech Stack:** Python 3.11, SQLAlchemy 2.x async, pytest-asyncio

**Prerequisites:** Plan A must be merged (DB models must exist).

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `backend/src/dzmm/service/world_graph.py` | Create | BFS distance on `WorldLocation` graph |
| `backend/src/dzmm/prompts/director_open_world_template.py` | Create | New Director system prompt |
| `backend/src/dzmm/service/agents/director_open_world.py` | Create | Event scoring, rumor, NPC contact, Director LLM call |
| `backend/src/dzmm/service/agents/orchestrator.py` | Modify | Dispatch to open-world Director when `framework_id` is set |
| `backend/tests/test_open_world_director.py` | Create | Unit tests for scoring, rumor, distance |

---

### Task 1: WorldGraph — BFS distance calculator

**Files:**
- Create: `backend/src/dzmm/service/world_graph.py`
- Create: `backend/tests/test_open_world_director.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_open_world_director.py
import json
import pytest
from dzmm.service.world_graph import build_graph, bfs_distance


def _loc(loc_id: int, connections: list[dict]) -> dict:
    return {"id": loc_id, "connections_json": json.dumps(connections)}


def test_bfs_distance_same_location():
    locs = [_loc(1, [{"target_id": 2, "distance": 1}])]
    graph = build_graph(locs)
    assert bfs_distance(graph, 1, 1) == 0


def test_bfs_distance_adjacent():
    locs = [
        _loc(1, [{"target_id": 2, "distance": 1}]),
        _loc(2, [{"target_id": 1, "distance": 1}]),
    ]
    graph = build_graph(locs)
    assert bfs_distance(graph, 1, 2) == 1


def test_bfs_distance_two_hops():
    locs = [
        _loc(1, [{"target_id": 2, "distance": 1}]),
        _loc(2, [{"target_id": 1, "distance": 1}, {"target_id": 3, "distance": 1}]),
        _loc(3, [{"target_id": 2, "distance": 1}]),
    ]
    graph = build_graph(locs)
    assert bfs_distance(graph, 1, 3) == 2


def test_bfs_distance_unreachable():
    locs = [
        _loc(1, []),
        _loc(2, []),
    ]
    graph = build_graph(locs)
    assert bfs_distance(graph, 1, 2) == 999
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && uv run pytest tests/test_open_world_director.py -v
```

Expected: `FAILED` — `ModuleNotFoundError: No module named 'dzmm.service.world_graph'`

- [ ] **Step 3: Implement world_graph.py**

```python
# backend/src/dzmm/service/world_graph.py
"""Spatial graph utilities for WorldLocation topology.

build_graph(locations) → adjacency dict {loc_id: [neighbor_id, ...]}
bfs_distance(graph, src, dst) → int hop count (999 = unreachable)
"""
from __future__ import annotations

import json
from collections import deque


def build_graph(locations: list[dict]) -> dict[int, list[int]]:
    """Build adjacency list from a list of location dicts.

    Each dict must have keys: id (int), connections_json (str).
    connections_json is a list of {target_id, ...} objects.
    Graph is treated as undirected (edges added both ways).
    """
    graph: dict[int, list[int]] = {}
    for loc in locations:
        loc_id = int(loc["id"])
        graph.setdefault(loc_id, [])
        try:
            conns = json.loads(loc.get("connections_json") or "[]")
        except (TypeError, ValueError):
            conns = []
        for conn in conns:
            try:
                neighbor = int(conn["target_id"])
            except (KeyError, TypeError, ValueError):
                continue
            graph.setdefault(neighbor, [])
            if neighbor not in graph[loc_id]:
                graph[loc_id].append(neighbor)
            if loc_id not in graph[neighbor]:
                graph[neighbor].append(loc_id)
    return graph


def bfs_distance(graph: dict[int, list[int]], src: int, dst: int) -> int:
    """Return the shortest hop count from src to dst. Returns 999 if unreachable."""
    if src == dst:
        return 0
    visited = {src}
    queue: deque[tuple[int, int]] = deque([(src, 0)])
    while queue:
        node, dist = queue.popleft()
        for neighbor in graph.get(node, []):
            if neighbor == dst:
                return dist + 1
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append((neighbor, dist + 1))
    return 999
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd backend && uv run pytest tests/test_open_world_director.py -v
```

Expected: 4 tests `PASSED`

- [ ] **Step 5: Commit**

```bash
git add backend/src/dzmm/service/world_graph.py backend/tests/test_open_world_director.py
git commit -m "feat(director): world_graph BFS distance calculator"
```

---

### Task 2: Event scoring formula + rumor eligibility

**Files:**
- Modify: `backend/tests/test_open_world_director.py`
- Create: `backend/src/dzmm/service/agents/director_open_world.py` (scoring portion only)

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_open_world_director.py`:

```python
from dzmm.service.agents.director_open_world import score_event, is_rumor_eligible


def _event(importance: int, scope_ref: str = "1") -> dict:
    return {"id": 1, "importance": importance, "scope_ref": scope_ref,
            "scope_type": "location", "trigger_conditions_json": "[]",
            "is_repeatable": False, "cooldown_turns": 0}


def _npc_state(npc_template_id: int, current_location_id: int | None,
               is_companion: bool = False) -> dict:
    return {"npc_template_id": npc_template_id,
            "current_location_id": current_location_id,
            "is_companion": is_companion}


def test_score_event_at_same_location():
    ev = _event(importance=3, scope_ref="1")
    score = score_event(ev, pc_location_id=1, distance=0,
                        companion_npc_ids=set(), faction_rep_npcs=set())
    assert abs(score - 3.0 * 1.0) < 0.01


def test_score_event_with_companion_bonus():
    ev = {"id": 1, "importance": 3, "scope_ref": "1",
          "scope_type": "npc", "trigger_conditions_json": "[]",
          "is_repeatable": False, "cooldown_turns": 0}
    score = score_event(ev, pc_location_id=1, distance=1,
                        companion_npc_ids={5}, faction_rep_npcs=set(),
                        npc_template_ids_in_event={5})
    # importance(3) * dist_factor(0.8) + companion_bonus(0.3)
    assert abs(score - (3.0 * 0.8 + 0.3)) < 0.01


def test_score_event_dist3_returns_zero():
    ev = _event(importance=5, scope_ref="10")
    score = score_event(ev, pc_location_id=1, distance=3,
                        companion_npc_ids=set(), faction_rep_npcs=set())
    assert score == 0.0


def test_rumor_eligible_far_important():
    ev = _event(importance=3)
    assert is_rumor_eligible(ev, distance=3, delivered=False,
                             turns_since_last=10, cooldown=5) is True


def test_rumor_not_eligible_already_delivered():
    ev = _event(importance=3)
    assert is_rumor_eligible(ev, distance=3, delivered=True,
                             turns_since_last=10, cooldown=5) is False


def test_rumor_not_eligible_on_cooldown():
    ev = _event(importance=3)
    assert is_rumor_eligible(ev, distance=3, delivered=False,
                             turns_since_last=3, cooldown=5) is False


def test_rumor_not_eligible_low_importance():
    ev = _event(importance=2)
    assert is_rumor_eligible(ev, distance=3, delivered=False,
                             turns_since_last=10, cooldown=5) is False
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && uv run pytest tests/test_open_world_director.py -k "score_event or rumor" -v
```

Expected: `FAILED` — `ImportError`

- [ ] **Step 3: Create director_open_world.py with scoring functions**

```python
# backend/src/dzmm/service/agents/director_open_world.py
"""Open-world Director agent.

Replaces the screenplay-chapter Director for sessions with framework_id set.
Scores nearby WorldEvents using a spatial decay formula, delivers far events
as rumors, checks NPC proactive contact, then calls the LLM for plot_directive.
"""
from __future__ import annotations

import json
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.models.client import GenerationParams, ModelClient
from dzmm.prompts.director_open_world_template import build_open_world_director_messages
from dzmm.service.agents.streams import (
    append_message,
    get_or_create_stream,
    load_history,
)
from dzmm.service.world_graph import bfs_distance, build_graph

log = logging.getLogger(__name__)

STREAM_KIND_DIRECTOR = "gm_director"
DIRECTOR_HISTORY_MAX = 20
_PARAMS = GenerationParams(temperature=0.4, max_tokens=500)

_RUMOR_COOLDOWN_TURNS = 5
_RUMOR_MIN_IMPORTANCE = 3

_FALLBACK_DIRECTIVE = (
    "<plot_directive>\n"
    "- 本回合主推：推进当前附近最高优先级事件\n"
    "- NPC 重点：（无）\n"
    "- 节奏：常态\n"
    "- 禁止：不要无视玩家本回合输入\n"
    "</plot_directive>"
)

_DIST_FACTORS = {0: 1.0, 1: 0.8, 2: 0.5}


def score_event(
    event: dict,
    pc_location_id: int,
    distance: int,
    companion_npc_ids: set[int],
    faction_rep_npcs: set[int],
    npc_template_ids_in_event: set[int] | None = None,
) -> float:
    """Compute Director priority score for a WorldEvent.

    Returns 0.0 for events at distance ≥ 3 (handled by rumor channel instead).
    Formula: importance × distance_factor + companion_bonus + faction_bonus
    """
    if distance >= 3:
        return 0.0
    dist_factor = _DIST_FACTORS.get(distance, 0.0)
    score = float(event["importance"]) * dist_factor

    npc_ids = npc_template_ids_in_event or set()
    if companion_npc_ids & npc_ids:
        score += 0.3
    if faction_rep_npcs & npc_ids:
        score += 0.2
    return score


def is_rumor_eligible(
    event: dict,
    distance: int,
    delivered: bool,
    turns_since_last: int,
    cooldown: int = _RUMOR_COOLDOWN_TURNS,
) -> bool:
    """Return True if a far event qualifies for rumor delivery."""
    if delivered:
        return False
    if distance < 3:
        return False
    if event["importance"] < _RUMOR_MIN_IMPORTANCE:
        return False
    if turns_since_last < cooldown:
        return False
    return True
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd backend && uv run pytest tests/test_open_world_director.py -k "score_event or rumor" -v
```

Expected: all 7 tests `PASSED`

- [ ] **Step 5: Commit**

```bash
git add backend/src/dzmm/service/agents/director_open_world.py backend/tests/test_open_world_director.py
git commit -m "feat(director): event scoring formula + rumor eligibility"
```

---

### Task 3: NPC proactive contact check

**Files:**
- Modify: `backend/src/dzmm/service/agents/director_open_world.py`
- Modify: `backend/tests/test_open_world_director.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_open_world_director.py`:

```python
from dzmm.service.agents.director_open_world import check_npc_proactive_contact


def _npc_state_dict(npc_id: int, favor: int, loc_id: int | None,
                    last_contact: int, threshold: int = 70, cooldown: int = 10) -> dict:
    return {
        "npc_template_id": npc_id,
        "favor": favor,
        "current_location_id": loc_id,
        "last_contact_turn": last_contact,
        "contact_favor_threshold": threshold,
        "contact_cooldown_turns": cooldown,
        "is_alive": True,
        "is_companion": False,
    }


def test_npc_contact_eligible():
    npc = _npc_state_dict(1, favor=80, loc_id=2, last_contact=0)
    result = check_npc_proactive_contact(
        npc_states=[npc], pc_location_id=1, current_turn=15
    )
    assert result is not None
    assert result["npc_template_id"] == 1


def test_npc_contact_insufficient_favor():
    npc = _npc_state_dict(1, favor=50, loc_id=2, last_contact=0)
    assert check_npc_proactive_contact([npc], pc_location_id=1, current_turn=15) is None


def test_npc_contact_same_location_skipped():
    # NPC already with PC — no proactive contact needed
    npc = _npc_state_dict(1, favor=90, loc_id=1, last_contact=0)
    assert check_npc_proactive_contact([npc], pc_location_id=1, current_turn=15) is None


def test_npc_contact_on_cooldown():
    npc = _npc_state_dict(1, favor=90, loc_id=2, last_contact=10)
    assert check_npc_proactive_contact([npc], pc_location_id=1, current_turn=15) is None


def test_npc_contact_dead_skipped():
    npc = _npc_state_dict(1, favor=90, loc_id=2, last_contact=0)
    npc["is_alive"] = False
    assert check_npc_proactive_contact([npc], pc_location_id=1, current_turn=15) is None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && uv run pytest tests/test_open_world_director.py -k "npc_contact" -v
```

Expected: `FAILED` — `ImportError: cannot import name 'check_npc_proactive_contact'`

- [ ] **Step 3: Add check_npc_proactive_contact to director_open_world.py**

Append to `director_open_world.py`:

```python
def check_npc_proactive_contact(
    npc_states: list[dict],
    pc_location_id: int,
    current_turn: int,
) -> dict | None:
    """Return the best NPC candidate for proactive contact this turn, or None.

    Conditions (all must be true):
    - is_alive
    - not is_companion (companions are always with PC)
    - favor >= contact_favor_threshold
    - current_location_id != pc_location_id (NPC is away)
    - current_turn - last_contact_turn >= contact_cooldown_turns
    """
    candidates = []
    for npc in npc_states:
        if not npc.get("is_alive", True):
            continue
        if npc.get("is_companion", False):
            continue
        if npc.get("favor", 0) < npc.get("contact_favor_threshold", 70):
            continue
        if npc.get("current_location_id") == pc_location_id:
            continue
        last_contact = npc.get("last_contact_turn", 0)
        cooldown = npc.get("contact_cooldown_turns", 10)
        if current_turn - last_contact < cooldown:
            continue
        candidates.append(npc)
    if not candidates:
        return None
    # Pick highest favor
    return max(candidates, key=lambda n: n.get("favor", 0))
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd backend && uv run pytest tests/test_open_world_director.py -k "npc_contact" -v
```

Expected: 5 tests `PASSED`

- [ ] **Step 5: Commit**

```bash
git add backend/src/dzmm/service/agents/director_open_world.py backend/tests/test_open_world_director.py
git commit -m "feat(director): NPC proactive contact eligibility check"
```

---

### Task 4: Open-world Director prompt + LLM call

**Files:**
- Create: `backend/src/dzmm/prompts/director_open_world_template.py`
- Modify: `backend/src/dzmm/service/agents/director_open_world.py`
- Modify: `backend/tests/test_open_world_director.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_open_world_director.py`:

```python
import json as _json
from dzmm.prompts.director_open_world_template import build_open_world_director_messages


def test_open_world_director_messages_structure():
    msgs = build_open_world_director_messages(
        history=[],
        snapshot={
            "current_location": "暗影港",
            "pc_summary": "林峰，侦探",
            "companions": [],
            "candidate_events": [
                {"name": "谋杀案", "score": 2.4, "importance": 3, "summary_md": "港口尸体"},
            ],
            "rumor_events": [],
            "proactive_npc": None,
            "campaign_phase": None,
            "faction_tensions": [],
        },
    )
    assert msgs[0].role == "system"
    assert msgs[-1].role == "user"
    assert "暗影港" in msgs[-1].content
    assert "谋杀案" in msgs[-1].content
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && uv run pytest tests/test_open_world_director.py::test_open_world_director_messages_structure -v
```

Expected: `FAILED` — `ModuleNotFoundError`

- [ ] **Step 3: Create director_open_world_template.py**

```python
# backend/src/dzmm/prompts/director_open_world_template.py
"""Open-world Director prompt.

Director 读的是「附近可用事件 + 主线进度」，而非章节列表。
输出格式与旧 Director 相同（plot_directive XML 块），
增加 <event_trigger event_id="N"/> 标签可标记事件触发。
"""
from __future__ import annotations

import json

from dzmm.models.client import Message

_SYSTEM = """你是开放世界 TRPG 的「剧情导演」（Director）。你不写场景描写，不演 NPC 台词。

你的职责：
1. 从候选事件中选择本回合要推动的事件（可以是 0 个）
2. 若有传闻事件，决定是否通过叙事投递（作为旅人传言）
3. 若有 NPC 主动联系提示，决定如何引入
4. 下发简洁剧情指令（plot_directive）

# 候选事件优先级
按 score 从高到低排列。score = 重要性 × 距离系数 + 加成。
score 越高 = 越应该本回合推动。

# 你产出（严格按顺序）

## 步骤一：事件触发声明（可选）
若上回合叙事/PC 行动已让某个候选事件"发生了"，emit：
<event_trigger event_id="N"/>

不确定则不 emit。已触发/已完成的事件不重复触发。

## 步骤二：剧情指令（必做，全文 ≤ 200 字）
<plot_directive>
- 本回合主推：[具体事件名 或 "自由探索"]
- NPC 重点：[0-2 个 NPC + 该做什么，若无则留空]
- 传闻投递：[事件名 或 "无"]
- 节奏：[紧张 / 缓和 / 悬疑 / 揭露 / 决断 之一]
- 禁止：[本回合不该做的 1 件事]
</plot_directive>

铁律：指令可执行，不空话；与上次指令保持连贯；优先推高 score 事件。
"""


def build_open_world_director_messages(
    history: list[Message],
    snapshot: dict,
) -> list[Message]:
    """Build messages for an open-world Director LLM call.

    snapshot keys:
      current_location: str
      pc_summary: str
      companions: list[str]  — companion NPC names
      candidate_events: list[{name, score, importance, summary_md}]
      rumor_events: list[{name, importance, summary_md}]
      proactive_npc: str | None  — NPC name that wants to contact PC
      campaign_phase: str | None
      faction_tensions: list[{name, tension}]
    """
    lines = [
        f"当前地点：{snapshot.get('current_location', '未知')}",
        f"PC 概要：{snapshot.get('pc_summary', '')}",
    ]
    companions = snapshot.get("companions") or []
    if companions:
        lines.append(f"旅伴：{', '.join(companions)}")

    events = snapshot.get("candidate_events") or []
    if events:
        lines.append("\n候选事件（按优先级排序）：")
        for ev in events:
            lines.append(
                f"  - [{ev['importance']}★] {ev['name']}（score={ev['score']:.1f}）：{ev['summary_md']}"
            )
    else:
        lines.append("\n候选事件：无（自由探索回合）")

    rumors = snapshot.get("rumor_events") or []
    if rumors:
        lines.append("\n可投递传闻：")
        for r in rumors:
            lines.append(f"  - {r['name']}（重要性={r['importance']}）：{r['summary_md']}")

    proactive = snapshot.get("proactive_npc")
    if proactive:
        lines.append(f"\n建议本回合引入 NPC 主动联系：{proactive}")

    phase = snapshot.get("campaign_phase")
    if phase:
        lines.append(f"\n主线进度：{phase}")

    tensions = snapshot.get("faction_tensions") or []
    if tensions:
        lines.append("\n势力紧张度：" + "；".join(f"{t['name']}={t['tension']}" for t in tensions))

    user_content = "\n".join(lines)
    msgs: list[Message] = [Message(role="system", content=_SYSTEM)]
    msgs.extend(history)
    msgs.append(Message(role="user", content=user_content))
    return msgs
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd backend && uv run pytest tests/test_open_world_director.py::test_open_world_director_messages_structure -v
```

Expected: `PASSED`

- [ ] **Step 5: Add run_open_world_director to director_open_world.py**

Append to `director_open_world.py` (after `check_npc_proactive_contact`):

```python
async def run_open_world_director(
    s: AsyncSession,
    session_id: int,
    framework_id: int,
    client: ModelClient,
    current_turn: int,
    pc_location_id: int,
    character_name: str,
    character_md: str,
) -> tuple[str, int, int]:
    """Run the open-world Director for one turn.

    Loads WorldLocations + pending WorldEvents + SessionNpcStates from DB,
    computes scoring, builds snapshot, calls LLM, returns (directive, tok_in, tok_out).
    """
    from dzmm.db.models import (
        WorldLocation,
        WorldEvent,
        WorldNPCTemplate,
        WorldFaction,
        SessionNpcState,
        SessionEventState,
        SessionFactionState,
        SessionCampaignState,
        Campaign,
    )
    from sqlalchemy import select as _select

    # 1. Load all world locations for this framework
    locs = (await s.execute(
        _select(WorldLocation).where(WorldLocation.framework_id == framework_id)
    )).scalars().all()
    loc_dicts = [
        {"id": loc.id, "connections_json": loc.connections_json, "name": loc.name}
        for loc in locs
    ]
    graph = build_graph(loc_dicts)

    # 2. Load pending world events
    events = (await s.execute(
        _select(WorldEvent).where(WorldEvent.framework_id == framework_id)
    )).scalars().all()

    # 3. Load session event states (triggered/completed → skip)
    ev_states_rows = (await s.execute(
        _select(SessionEventState).where(SessionEventState.session_id == session_id)
    )).scalars().all()
    done_event_ids = {
        es.event_id for es in ev_states_rows
        if es.status in ("triggered", "completed")
    }
    rumor_event_ids = {
        es.event_id for es in ev_states_rows if es.rumor_delivered
    }
    last_rumor_turns = {es.event_id: es.rumor_delivered_turn for es in ev_states_rows}

    # 4. Load NPC states for proactive contact check
    npc_states_rows = (await s.execute(
        _select(SessionNpcState, WorldNPCTemplate)
        .join(WorldNPCTemplate, SessionNpcState.npc_template_id == WorldNPCTemplate.id)
        .where(SessionNpcState.session_id == session_id)
    )).all()
    companion_npc_ids = {
        row.SessionNpcState.npc_template_id
        for row in npc_states_rows
        if row.SessionNpcState.is_companion
    }
    npc_state_dicts = [
        {
            "npc_template_id": row.SessionNpcState.npc_template_id,
            "favor": row.SessionNpcState.favor,
            "current_location_id": row.SessionNpcState.current_location_id,
            "last_contact_turn": row.SessionNpcState.last_contact_turn,
            "contact_favor_threshold": row.WorldNPCTemplate.contact_favor_threshold,
            "contact_cooldown_turns": row.WorldNPCTemplate.contact_cooldown_turns,
            "is_alive": row.SessionNpcState.is_alive,
            "is_companion": row.SessionNpcState.is_companion,
            "name": row.WorldNPCTemplate.name,
        }
        for row in npc_states_rows
    ]

    # 5. Load faction tensions
    faction_states = (await s.execute(
        _select(SessionFactionState, WorldFaction)
        .join(WorldFaction, SessionFactionState.faction_id == WorldFaction.id)
        .where(SessionFactionState.session_id == session_id)
    )).all()
    faction_tensions = [
        {"name": row.WorldFaction.name, "tension": row.SessionFactionState.tension}
        for row in faction_states
        if row.SessionFactionState.tension > 0
    ]

    # 6. Score candidate events
    candidate_events = []
    rumor_events = []
    for ev in events:
        if ev.id in done_event_ids:
            continue
        # Determine location distance
        try:
            scope_loc_id = int(ev.scope_ref) if ev.scope_type == "location" else None
        except (ValueError, TypeError):
            scope_loc_id = None
        dist = bfs_distance(graph, pc_location_id, scope_loc_id) if scope_loc_id else 0

        sc = score_event(
            {"id": ev.id, "importance": ev.importance, "scope_ref": ev.scope_ref,
             "scope_type": ev.scope_type},
            pc_location_id=pc_location_id,
            distance=dist,
            companion_npc_ids=companion_npc_ids,
            faction_rep_npcs=set(),
        )
        if sc > 0:
            candidate_events.append({
                "id": ev.id, "name": ev.name, "score": sc,
                "importance": ev.importance, "summary_md": ev.summary_md,
            })
        elif is_rumor_eligible(
            {"importance": ev.importance},
            distance=dist,
            delivered=ev.id in rumor_event_ids,
            turns_since_last=current_turn - last_rumor_turns.get(ev.id, 0),
        ):
            rumor_events.append({
                "id": ev.id, "name": ev.name,
                "importance": ev.importance, "summary_md": ev.summary_md,
            })

    candidate_events.sort(key=lambda e: e["score"], reverse=True)
    candidate_events = candidate_events[:5]

    # 7. NPC proactive contact
    proactive = check_npc_proactive_contact(
        npc_state_dicts, pc_location_id=pc_location_id, current_turn=current_turn
    )
    proactive_name = proactive["name"] if proactive else None

    # 8. Campaign phase
    campaign_phase_str: str | None = None
    camp_state = await s.get(SessionCampaignState, session_id)
    if camp_state and camp_state.current_phase_id:
        camp_row = (await s.execute(
            _select(Campaign).where(Campaign.framework_id == framework_id)
        )).scalars().first()
        if camp_row:
            phases = json.loads(camp_row.phases_json or "[]")
            phase = next((p for p in phases if p["phase_id"] == camp_state.current_phase_id), None)
            if phase:
                triggered = json.loads(camp_state.triggered_key_events_json or "[]")
                campaign_phase_str = (
                    f"{phase['name']}（{len(triggered)}/{phase['required_count']} 关键事件）"
                )

    # 9. Build snapshot + call LLM
    snapshot = {
        "current_location": next((l["name"] for l in loc_dicts if l["id"] == pc_location_id), "未知"),
        "pc_summary": f"{character_name}",
        "companions": [n["name"] for n in npc_state_dicts if n["is_companion"]],
        "candidate_events": candidate_events,
        "rumor_events": rumor_events[:3],
        "proactive_npc": proactive_name,
        "campaign_phase": campaign_phase_str,
        "faction_tensions": faction_tensions,
    }

    stream = await get_or_create_stream(s, session_id, STREAM_KIND_DIRECTOR, "")
    history = await load_history(s, stream.id, max_messages=DIRECTOR_HISTORY_MAX)
    msgs = build_open_world_director_messages(history, snapshot)

    try:
        output, usage = await client.complete(msgs, _PARAMS)
    except Exception as exc:  # noqa: BLE001
        log.warning("open-world director: LLM call failed: %s", exc)
        return _FALLBACK_DIRECTIVE, 0, 0

    text = (output or "").strip()
    if not text:
        return _FALLBACK_DIRECTIVE, 0, 0

    tok_in = usage.input_tokens if usage else 0
    tok_out = usage.output_tokens if usage else 0

    snapshot_str = _json_snapshot(snapshot)
    await append_message(s, stream.id, current_turn, "user", snapshot_str, tokens_in=tok_in)
    await append_message(s, stream.id, current_turn, "assistant", text, tokens_out=tok_out)
    stream.last_run_turn = current_turn
    return text, tok_in, tok_out


def _json_snapshot(snapshot: dict) -> str:
    import json
    return json.dumps(snapshot, ensure_ascii=False, indent=None)
```

- [ ] **Step 6: Run all director tests**

```bash
cd backend && uv run pytest tests/test_open_world_director.py -v
```

Expected: All tests `PASSED`

- [ ] **Step 7: Commit**

```bash
git add backend/src/dzmm/prompts/director_open_world_template.py backend/src/dzmm/service/agents/director_open_world.py backend/tests/test_open_world_director.py
git commit -m "feat(director): open-world director prompt + LLM call with spatial scoring"
```

---

### Task 5: Wire open-world Director into orchestrator

**Files:**
- Modify: `backend/src/dzmm/service/agents/orchestrator.py`

The orchestrator already has `run_director` imported and called at line ~577. We add a branch: if `sess.framework_id` is set, call `run_open_world_director` instead.

- [ ] **Step 1: Find the exact lines to modify**

```bash
grep -n "run_director\|framework_id\|should_run_director" backend/src/dzmm/service/agents/orchestrator.py | head -20
```

- [ ] **Step 2: Add import at top of orchestrator.py**

After the existing `from dzmm.service.agents.director import run_director, ...` import, add:

```python
from dzmm.service.agents.director_open_world import run_open_world_director
```

- [ ] **Step 3: Add open-world branch in the director-fire block**

Find the block (around line 573):
```python
    fire, reason = should_run_director(director_stream, cs_obj, current_turn)
    if fire:
        log.info("director firing (reason=%s) at turn %d", reason, current_turn)
        snapshot = await _build_director_snapshot(s, session_id, current_turn)
        directive, d_in, d_out = await run_director(
            s, session_id, director_client, current_turn, snapshot,
        )
```

Replace the `run_director` call with:

```python
    fire, reason = should_run_director(director_stream, cs_obj, current_turn)
    if fire:
        log.info("director firing (reason=%s) at turn %d", reason, current_turn)
        if sess.framework_id:
            directive, d_in, d_out = await run_open_world_director(
                s=s,
                session_id=session_id,
                framework_id=sess.framework_id,
                client=director_client,
                current_turn=current_turn,
                pc_location_id=_get_pc_location_id(s, sess),
                character_name=char.name,
                character_md=char.profile_md,
            )
        else:
            snapshot = await _build_director_snapshot(s, session_id, current_turn)
            directive, d_in, d_out = await run_director(
                s, session_id, director_client, current_turn, snapshot,
            )
```

- [ ] **Step 4: Add _get_pc_location_id helper to orchestrator.py**

This reads the current PC location from `SessionNpcState` or falls back to a default. Add near the other helper functions:

```python
def _get_pc_location_id(s: AsyncSession, sess) -> int:
    """Return the PC's current WorldLocation ID. Returns 0 if not tracked yet."""
    # framework sessions store pc_location_id in settings_json
    try:
        import json
        settings = json.loads(sess.settings_json or "{}")
        return int(settings.get("pc_location_id", 0))
    except (TypeError, ValueError):
        return 0
```

Note: `pc_location_id` in `settings_json` is updated by the `<location_enter>` handler (Plan C will add this). For now it defaults to 0 (framework root).

- [ ] **Step 5: Run full backend test suite**

```bash
cd backend && uv run pytest tests/ -v --tb=short 2>&1 | tail -30
```

Expected: All tests pass.

- [ ] **Step 6: Commit**

```bash
git add backend/src/dzmm/service/agents/orchestrator.py
git commit -m "feat(director): wire open-world Director into orchestrator (framework_id branch)"
```

---

### Task 6: Cleanup — remove PlotThread and screenplay-based Director snapshot

These are replaced by the open-world event system. Only safe to remove now that the replacement is in place.

**Files:**
- Modify: `backend/src/dzmm/service/agents/orchestrator.py` — remove `_build_director_snapshot` screenplay references if they only served the old path (verify first)
- Do NOT remove `PlotThread` ORM yet — wait for Plan C (Wizard) to stop creating it

- [ ] **Step 1: Check if _build_director_snapshot uses PlotThread**

```bash
grep -n "PlotThread\|plot_threads\|screenplay" backend/src/dzmm/service/agents/orchestrator.py | head -20
```

- [ ] **Step 2: If PlotThread is referenced only in old Director snapshot, note it for Plan C**

Add a comment at the top of `_build_director_snapshot`:

```python
# TODO(Plan-C): Remove this function once all sessions use framework_id.
# Old screenplay-based Director snapshot — kept for legacy sessions only.
```

- [ ] **Step 3: Commit**

```bash
git add backend/src/dzmm/service/agents/orchestrator.py
git commit -m "chore: mark legacy Director snapshot for removal in Plan C"
```
