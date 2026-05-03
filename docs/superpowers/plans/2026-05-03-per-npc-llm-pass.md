# Per-NPC Individual LLM Pass Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give each present NPC its own LLM call (with full character profile in the prompt) instead of one call for all NPCs, so a cold NPC and a warm NPC in the same scene get genuinely distinct reactions.

**Architecture:** Add `build_npc_single_react_messages(narrative, npc, user_action)` that embeds the NPC's archetype/description/emotions into the prompt. Add `run_single_npc_pass()` that returns one `ParseEvent | None`. Refactor `run_npc_post_pass()` to use `asyncio.gather(*[run_single_npc_pass(n) for n in npcs])` — calls are independent so they run in parallel. Update `game.py` to pass NPC ORM objects directly instead of formatted strings.

**Tech Stack:** Python asyncio, LangGraph (existing), existing `StreamingTagParser`, existing `NPC` ORM model, existing `ModelClient` abstraction.

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Modify | `backend/src/dzmm/prompts/npc_react_template.py` | Add `build_npc_single_react_messages(narrative, npc, user_action)` using NPC ORM fields |
| Modify | `backend/src/dzmm/service/gm_graph.py` | Add `run_single_npc_pass()`, refactor `run_npc_post_pass()` to asyncio.gather, add `import asyncio` |
| Modify | `backend/src/dzmm/service/game.py` | Pass NPC ORM objects directly instead of `f"{n.name}（状态：{n.state}）"` strings |
| Modify | `backend/tests/test_gm_graph.py` | Add `_FakeNpc`, update NPC-related tests to use objects |

---

## Task 1: Add single-NPC prompt template

**Files:**
- Modify: `backend/src/dzmm/prompts/npc_react_template.py`
- Modify: `backend/tests/test_gm_graph.py`

- [ ] **Step 1: Write failing test**

Append to `backend/tests/test_gm_graph.py` (after the last test, before EOF):

```python
class _FakeNpc:
    """Minimal NPC stub for testing — mirrors NPC ORM fields used by the prompt."""
    def __init__(
        self,
        name: str,
        archetype: str = "普通人",
        description: str = "一个普通的人。",
        state: str = "平静",
        purpose: str = "",
        emotion_json: str = "{}",
    ):
        self.name = name
        self.archetype = archetype
        self.description = description
        self.state = state
        self.purpose = purpose
        self.emotion_json = emotion_json


def test_build_npc_single_react_messages_embeds_archetype():
    from dzmm.prompts.npc_react_template import build_npc_single_react_messages
    npc = _FakeNpc(
        name="卫队长",
        archetype="冷酷军人",
        description="前帝国精锐，话少，但观察敏锐。",
        state="戒备",
        purpose="守护王城安全",
        emotion_json='{"suspicious": 7}',
    )
    msgs = build_npc_single_react_messages(
        narrative="你走进了城门，卫队长瞥了你一眼，手按在剑柄上。",
        npc=npc,
        user_action="我微笑着递上通行证",
    )
    assert len(msgs) == 1
    assert msgs[0].role == "user"
    assert "冷酷军人" in msgs[0].content
    assert "卫队长" in msgs[0].content
    assert "戒备" in msgs[0].content


def test_build_npc_single_react_messages_different_archetype():
    from dzmm.prompts.npc_react_template import build_npc_single_react_messages
    npc = _FakeNpc(
        name="酒馆老板",
        archetype="热情商人",
        description="胖乎乎，总是笑着，非常健谈。",
        state="高兴",
        purpose="经营酒馆，广结善缘",
    )
    msgs = build_npc_single_react_messages(
        narrative="你推开酒馆大门，热气扑面而来。",
        npc=npc,
        user_action="我走进酒馆",
    )
    assert "热情商人" in msgs[0].content
    assert "酒馆老板" in msgs[0].content
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd /Users/norman/development/dzmm/backend && python -m pytest tests/test_gm_graph.py::test_build_npc_single_react_messages_embeds_archetype -v 2>&1 | tail -5
```

Expected: `ImportError: cannot import name 'build_npc_single_react_messages'`

- [ ] **Step 3: Add `build_npc_single_react_messages` to `npc_react_template.py`**

Full new content of `backend/src/dzmm/prompts/npc_react_template.py` (keep existing function, add new one):

```python
import json as _json

from dzmm.models.client import Message

# ── 旧版（多 NPC 列表，保留供参考） ─────────────────────────────
_TEMPLATE = """你是 TRPG NPC 行为顾问。根据本回合叙事，判断在场 NPC 是否有额外反应需要补充。

# 本回合叙事（GM 刚刚生成）
{narrative}

# 玩家行动
{user_action}

# 在场 NPC 列表
{npc_list}

# 任务
检查上面的叙事里是否有遗漏的 NPC 反应。如果有需要补充的 NPC 状态变化，
用 XML 格式输出（每个 NPC 一个标签）：
<npc_update name="NPC名字">新的状态描述</npc_update>

如果叙事已经足够完整，不需要补充，输出：
<npc_update name="none">无需补充</npc_update>

只输出 XML，不要其他说明。
"""


def build_npc_react_messages(
    narrative: str,
    present_npcs: list[str],
    user_action: str,
) -> list[Message]:
    npc_list = "\n".join(f"- {npc}" for npc in present_npcs) if present_npcs else "（无在场 NPC）"
    return [
        Message(
            role="user",
            content=_TEMPLATE.format(
                narrative=narrative.strip() or "（无叙事）",
                user_action=user_action.strip(),
                npc_list=npc_list,
            ),
        )
    ]


# ── 新版（单 NPC 独立调用，人设更丰富） ──────────────────────────
_SINGLE_NPC_TEMPLATE = """你正在扮演 TRPG 中的 NPC「{name}」。根据本回合叙事，决定你的反应。

# 角色设定
- 姓名：{name}
- 性格原型：{archetype}
- 人物简介：{description}
- 目的/动机：{purpose}
- 当前状态：{state}
- 当前情绪：{emotions}

# 本回合叙事（GM 刚刚生成）
{narrative}

# 玩家行动
{user_action}

# 任务
以「{name}」的性格和当前状态，判断这一刻是否需要补充反应。
你的反应必须符合「{archetype}」的性格特征，不能与其他角色混淆。

只输出 XML，不要其他说明：

如果需要补充（动作/台词/状态变化）：
<npc_update name="{name}">具体反应（1-2 句，符合人物性格）</npc_update>

如果叙事中已经完整描述了「{name}」的反应：
<npc_update name="none">无需补充</npc_update>
"""


def build_npc_single_react_messages(
    narrative: str,
    npc,  # NPC ORM object: .name, .archetype, .description, .state, .purpose, .emotion_json
    user_action: str,
) -> list[Message]:
    # Parse emotion_json safely — format as "好奇:7, 警惕:3" or "无"
    try:
        emotions_dict = _json.loads(npc.emotion_json or "{}")
        emotions_str = (
            ", ".join(f"{k}:{v}" for k, v in emotions_dict.items())
            if emotions_dict
            else "无"
        )
    except (ValueError, TypeError):
        emotions_str = "无"

    return [
        Message(
            role="user",
            content=_SINGLE_NPC_TEMPLATE.format(
                name=(npc.name or "未知").strip(),
                archetype=(npc.archetype or "普通人").strip() or "普通人",
                description=(npc.description or "（无简介）").strip()[:300],
                purpose=(npc.purpose or "（未知）").strip()[:200],
                state=(npc.state or "未知").strip(),
                emotions=emotions_str,
                narrative=narrative.strip() or "（无叙事）",
                user_action=user_action.strip(),
            ),
        )
    ]
```

- [ ] **Step 4: Run template tests**

```bash
cd /Users/norman/development/dzmm/backend && python -m pytest tests/test_gm_graph.py::test_build_npc_single_react_messages_embeds_archetype tests/test_gm_graph.py::test_build_npc_single_react_messages_different_archetype -v
```

Expected: both PASS.

- [ ] **Step 5: Commit**

```bash
cd /Users/norman/development/dzmm && git add backend/src/dzmm/prompts/npc_react_template.py backend/tests/test_gm_graph.py && git commit -m "feat(npc): add build_npc_single_react_messages with full character profile"
```

---

## Task 2: Refactor gm_graph.py to per-NPC parallel calls

**Files:**
- Modify: `backend/src/dzmm/service/gm_graph.py`
- Modify: `backend/tests/test_gm_graph.py`

- [ ] **Step 1: Write failing tests**

Append to `backend/tests/test_gm_graph.py`:

```python
@pytest.mark.asyncio
async def test_run_npc_post_pass_per_npc_with_objects():
    """run_npc_post_pass should call LLM once per NPC object and return all non-none events."""
    call_count = 0

    class _CountingClient(ModelClient):
        name = "counting"
        async def stream(self, messages, params):
            yield StreamChunk(delta=f'<npc_update name="{messages[0].content[:2]}">反应</npc_update>', finish_reason="stop")
        async def complete(self, messages, params):
            nonlocal call_count
            call_count += 1
            npc_name = "王五" if call_count == 1 else "李四"
            return f'<npc_update name="{npc_name}">有反应</npc_update>', TokenUsage()

    npc1 = _FakeNpc(name="王五", archetype="冷酷商人")
    npc2 = _FakeNpc(name="李四", archetype="热情向导")
    events = await run_npc_post_pass(
        narrative="你进入了市场。",
        present_npcs=[npc1, npc2],
        user_action="我四处张望",
        client=_CountingClient(),
    )
    assert call_count == 2  # one call per NPC
    assert len(events) == 2


@pytest.mark.asyncio
async def test_run_npc_post_pass_skips_none_responses():
    """NPCs that respond with 'none' should not contribute events."""
    responses = iter([
        '<npc_update name="none">无需补充</npc_update>',
        '<npc_update name="村民">惊讶地看着你</npc_update>',
    ])

    class _SequentialClient(ModelClient):
        name = "seq"
        async def stream(self, messages, params):
            yield StreamChunk(delta=next(responses), finish_reason="stop")
        async def complete(self, messages, params):
            return next(responses), TokenUsage()

    npc1 = _FakeNpc(name="守卫")
    npc2 = _FakeNpc(name="村民")
    events = await run_npc_post_pass(
        narrative="你走进村子。",
        present_npcs=[npc1, npc2],
        user_action="我进村",
        client=_SequentialClient(),
    )
    assert len(events) == 1
    assert events[0].attrs.get("name") == "村民"
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd /Users/norman/development/dzmm/backend && python -m pytest tests/test_gm_graph.py::test_run_npc_post_pass_per_npc_with_objects -v 2>&1 | tail -8
```

Expected: `TypeError` (present_npcs receives NPC objects but current code calls `build_npc_react_messages` which expects strings).

- [ ] **Step 3: Rewrite gm_graph.py**

Full new content of `backend/src/dzmm/service/gm_graph.py`:

```python
# ============================================================
# Phase B — LangGraph 多 Agent GM 管线
# ============================================================
# 【架构说明】
#   把 GM 拆成三个阶段：
#     1. 规则预处理（Pre-pass）— LangGraph StateGraph
#        rules_node 分析行动类型和技能检定需求
#        → 条件边：有检定 → dice_enrich_node；无检定 → END
#     2. 主叙事生成（Narrative）— 现有流式生成，不变
#     3. NPC 后处理（Post-pass）— 每个在场 NPC 独立一次 LLM 调用，asyncio.gather 并行
#        每次调用包含该 NPC 的完整人设（archetype/description/emotions），
#        保证"冷酷商人"和"热情向导"给出符合各自性格的不同反应。
#
# 【LangGraph 核心概念】
#   StateGraph:  有向图，节点是状态处理函数，边是流程控制
#   TypedDict:   图状态的类型定义（类似 Java 的 DTO/Record）
#   add_node:    注册一个处理步骤
#   add_conditional_edges: 根据状态内容决定下一步走哪个节点
#   compile():   把图编译成可执行对象
#   ainvoke():   异步执行整个图，返回最终状态
# ============================================================

import asyncio
import logging
from typing import TypedDict

from langgraph.graph import END, StateGraph

from dzmm.models.client import GenerationParams, ModelClient
from dzmm.parsing.events import ParseEvent, TagComplete
from dzmm.parsing.stream_parser import StreamingTagParser
from dzmm.prompts.npc_react_template import build_npc_single_react_messages
from dzmm.prompts.rules_template import build_rules_messages

log = logging.getLogger(__name__)

_RULES_PARAMS = GenerationParams(temperature=0.3, max_tokens=120)
_NPC_PARAMS = GenerationParams(temperature=0.7, max_tokens=150)


# ── LangGraph 状态定义 ────────────────────────────────────
class PrePassState(TypedDict):
    key_facts: str
    user_action: str
    rules_enrichment: str


# ── 节点函数 ──────────────────────────────────────────────
def make_rules_node(client: ModelClient):
    """工厂函数：返回一个绑定了 client 的 rules_node（闭包注入依赖）。"""
    async def rules_node(state: PrePassState) -> PrePassState:
        msgs = build_rules_messages(state["key_facts"], state["user_action"])
        output, _ = await client.complete(msgs, _RULES_PARAMS)
        return {**state, "rules_enrichment": output.strip()}
    return rules_node


async def dice_enrich_node(state: PrePassState) -> PrePassState:
    """条件节点：当 rules_node 检测到技能检定需求时，高亮骰子上下文。"""
    enrichment = state["rules_enrichment"]
    highlighted = "🎲 **骰子检定预告（仅 GM 可见）**\n" + enrichment
    return {**state, "rules_enrichment": highlighted}


def _route_after_rules(state: PrePassState) -> str:
    """条件边路由：根据规则分析结果决定下一步。"""
    enrichment = state.get("rules_enrichment", "")
    if "检定" in enrichment and "DC" in enrichment:
        return "dice_enrich"
    return END


# ── 图构建 ───────────────────────────────────────────────
def make_pre_pass_graph(client: ModelClient):
    """构建并编译 pre-pass StateGraph。"""
    builder = StateGraph(PrePassState)
    builder.add_node("rules", make_rules_node(client))
    builder.add_node("dice_enrich", dice_enrich_node)
    builder.set_entry_point("rules")
    builder.add_conditional_edges(
        "rules",
        _route_after_rules,
        {"dice_enrich": "dice_enrich", END: END},
    )
    builder.add_edge("dice_enrich", END)
    return builder.compile()


# ── 公共 API ─────────────────────────────────────────────
async def run_pre_pass(
    key_facts: str,
    user_action: str,
    client: ModelClient,
) -> str:
    """运行预处理图，返回注入了规则分析的增强版 key_facts。失败时回退到原始值。"""
    try:
        graph = make_pre_pass_graph(client)
        initial: PrePassState = {
            "key_facts": key_facts,
            "user_action": user_action,
            "rules_enrichment": "",
        }
        result = await graph.ainvoke(initial)
        enrichment = result.get("rules_enrichment", "")
        if enrichment:
            return key_facts + "\n\n## 🎮 规则分析（仅 GM 可见）\n" + enrichment
    except Exception as exc:
        log.warning("gm_graph pre_pass failed, using original key_facts: %s", exc)
    return key_facts


async def run_single_npc_pass(
    narrative: str,
    npc,  # NPC ORM object: .name .archetype .description .state .purpose .emotion_json
    user_action: str,
    client: ModelClient,
) -> ParseEvent | None:
    """单个 NPC 的独立 LLM 调用，返回一个 TagComplete 事件或 None。

    【学习点：per-NPC 并行调用】
      相比把所有 NPC 塞进一次调用，每个 NPC 独立调用有两个优势：
      1. 每次 LLM 调用的 prompt 里只有一个角色的人设，注意力集中，性格更准确
      2. 多个调用用 asyncio.gather 并行，总延迟 ≈ 最慢那个 NPC 的单次调用
    """
    try:
        msgs = build_npc_single_react_messages(narrative, npc, user_action)
        output, _ = await client.complete(msgs, _NPC_PARAMS)
        if not output.strip() or 'name="none"' in output:
            return None
        parser = StreamingTagParser()
        events: list[ParseEvent] = []
        for ev in parser.feed(output):
            if isinstance(ev, TagComplete) and ev.name == "npc_update":
                events.append(ev)
        events.extend(
            ev for ev in parser.finish()
            if isinstance(ev, TagComplete) and ev.name == "npc_update"
        )
        return events[0] if events else None
    except Exception as exc:
        log.warning("gm_graph npc_single_pass failed (%s): %s", getattr(npc, "name", "?"), exc)
        return None


async def run_npc_post_pass(
    narrative: str,
    present_npcs: list,  # list of NPC ORM objects
    user_action: str,
    client: ModelClient,
) -> list[ParseEvent]:
    """NPC 后处理：每个在场 NPC 独立一次 LLM 调用，asyncio.gather 并行执行。"""
    if not present_npcs:
        return []
    try:
        results = await asyncio.gather(
            *[run_single_npc_pass(narrative, npc, user_action, client) for npc in present_npcs]
        )
        return [ev for ev in results if ev is not None]
    except Exception as exc:
        log.warning("gm_graph npc_post_pass failed: %s", exc)
        return []
```

- [ ] **Step 4: Update old NPC post-pass tests to use `_FakeNpc`**

The existing tests `test_run_npc_post_pass_*` in `test_gm_graph.py` pass string lists — update them:

Find and replace the three existing post-pass tests (lines ~68–98 of the original file). The new versions:

```python
@pytest.mark.asyncio
async def test_run_npc_post_pass_parses_npc_update_tags():
    client = _FakeClient('<npc_update name="王五">注意到你，微微点头</npc_update>')
    npc = _FakeNpc(name="王五", archetype="冷静商人", state="平静")
    events = await run_npc_post_pass(
        narrative="你走进了酒馆",
        present_npcs=[npc],
        user_action="我走进酒馆",
        client=client,
    )
    assert len(events) == 1
    assert isinstance(events[0], TagComplete)
    assert events[0].name == "npc_update"
    assert events[0].attrs.get("name") == "王五"


@pytest.mark.asyncio
async def test_run_npc_post_pass_returns_empty_for_none_response():
    client = _FakeClient('<npc_update name="none">无需补充</npc_update>')
    npc = _FakeNpc(name="李四")
    events = await run_npc_post_pass(
        narrative="...", present_npcs=[npc], user_action="...", client=client
    )
    assert events == []


@pytest.mark.asyncio
async def test_run_npc_post_pass_returns_empty_when_no_npcs():
    client = _FakeClient("should not be called")
    events = await run_npc_post_pass(
        narrative="...", present_npcs=[], user_action="...", client=client
    )
    assert events == []
```

- [ ] **Step 5: Run all gm_graph tests**

```bash
cd /Users/norman/development/dzmm/backend && python -m pytest tests/test_gm_graph.py -v
```

Expected: all 12 tests pass (3 old pre-pass + 2 old template + 2 new template + 3 updated post-pass + 2 new per-NPC tests).

- [ ] **Step 6: Commit**

```bash
cd /Users/norman/development/dzmm && git add backend/src/dzmm/service/gm_graph.py backend/tests/test_gm_graph.py && git commit -m "feat(npc): per-NPC individual LLM calls with asyncio.gather (Phase B enhancement)"
```

---

## Task 3: Update game.py caller + full suite

**Files:**
- Modify: `backend/src/dzmm/service/game.py`

- [ ] **Step 1: Update game.py to pass NPC objects directly**

Find this block in `backend/src/dzmm/service/game.py` (around line 483–490):

```python
        if recent_npc_rows:
            present_npc_strs = [
                f"{n.name}（状态：{n.state or '未知'}）" for n in recent_npc_rows
            ]
            narrative_so_far = "".join(narrative_parts)
            npc_extra_events = await run_npc_post_pass(
                narrative_so_far, present_npc_strs, user_action, client
            )
```

Replace with:

```python
        if recent_npc_rows:
            narrative_so_far = "".join(narrative_parts)
            npc_extra_events = await run_npc_post_pass(
                narrative_so_far, list(recent_npc_rows), user_action, client
            )
```

- [ ] **Step 2: Run full test suite**

```bash
cd /Users/norman/development/dzmm/backend && python -m pytest tests/ -x --ignore=tests/test_ollama.py --ignore=tests/test_openai_compat.py -q 2>&1 | tail -10
```

Expected: all tests pass (≥383).

- [ ] **Step 3: Commit**

```bash
cd /Users/norman/development/dzmm && git add backend/src/dzmm/service/game.py && git commit -m "refactor(game): pass NPC objects directly to run_npc_post_pass"
```

---

## Self-Review

**Spec coverage:**
- [x] Each NPC gets its own LLM call ✓ (`run_single_npc_pass`)
- [x] Character profile (archetype/description/emotions) in each prompt ✓ (`build_npc_single_react_messages`)
- [x] Parallel execution ✓ (`asyncio.gather`)
- [x] 2 NPCs → 2 separate LLM calls ✓ (tested in `test_run_npc_post_pass_per_npc_with_objects`)
- [x] Graceful failure per NPC ✓ (individual try/except in `run_single_npc_pass`)

**Placeholder scan:** None found.

**Type consistency:**
- `build_npc_single_react_messages(narrative, npc, user_action)` — defined Task 1, called Task 2. ✓
- `run_single_npc_pass(narrative, npc, user_action, client) -> ParseEvent | None` — defined Task 2. ✓
- `run_npc_post_pass(narrative, present_npcs: list, ...)` — updated Task 2, caller updated Task 3. ✓
- `_FakeNpc` — defined Task 1 tests, reused Task 2 tests. ✓
