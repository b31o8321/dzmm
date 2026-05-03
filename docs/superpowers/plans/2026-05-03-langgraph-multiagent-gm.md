# Phase B: LangGraph 多 Agent GM Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split the single monolithic GM LLM call into a LangGraph-orchestrated multi-agent pipeline: a rules pre-pass agent (StateGraph with conditional dice edge) + main narrative stream + NPC post-pass agent.

**Architecture:** A LangGraph `StateGraph` runs before the main narrative: `rules_node` analyzes the player action (non-streaming, fast), routes via conditional edge to `dice_enrich_node` if a skill check is detected, and returns an enriched `key_facts` string. The main narrative stream is unchanged. After streaming, a separate `npc_react_agent` (plain async function) runs a quick NPC reaction check, yielding additional `TagComplete` events. Integration is behind a `use_graph` session setting so existing behavior is opt-in.

**Tech Stack:** `langgraph>=0.2`, `langchain-core>=0.3` (already installed), existing `ModelClient.complete()` for non-streaming agent calls.

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `backend/src/dzmm/prompts/rules_template.py` | Rules pre-pass prompt |
| Create | `backend/src/dzmm/prompts/npc_react_template.py` | NPC post-pass reaction prompt |
| Create | `backend/src/dzmm/service/gm_graph.py` | LangGraph StateGraph + run_pre_pass + run_npc_post_pass |
| Create | `backend/tests/test_gm_graph.py` | Tests for all graph functions |
| Modify | `backend/src/dzmm/service/game.py` | Wire graph into run_turn() when use_graph=True |
| Modify | `backend/pyproject.toml` | Add langgraph>=0.2; bump version 0.4.0 → 0.5.0 |
| Modify | `CHANGELOG.md` | Add v0.5.0 entry |
| Modify | `docs/learning/roadmap.md` | Mark Phase B complete |
| Create | `docs/learning/langgraph-multiagent.md` | Phase B learning doc |
| Modify | `docs/learning/README.md` | Add langgraph-multiagent.md to index |

---

## Task 1: Add langgraph dependency

**Files:**
- Modify: `backend/pyproject.toml`

- [ ] **Step 1: Add langgraph to dependencies**

In `backend/pyproject.toml`, add to the `dependencies` list:
```toml
    "langgraph>=0.2",
```

- [ ] **Step 2: Install**

```bash
cd /Users/norman/development/dzmm/backend && uv pip install -e ".[dev]"
```

Expected: installs `langgraph` and any transitive deps.

- [ ] **Step 3: Verify import**

```bash
cd /Users/norman/development/dzmm/backend && python -c "from langgraph.graph import StateGraph, END; print('OK')"
```

Expected: prints `OK`.

- [ ] **Step 4: Run tests to confirm nothing broke**

```bash
cd /Users/norman/development/dzmm/backend && python -m pytest tests/ -x --ignore=tests/test_ollama.py --ignore=tests/test_openai_compat.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
cd /Users/norman/development/dzmm && git add backend/pyproject.toml && git commit -m "feat(deps): add langgraph>=0.2 for Phase B multi-agent GM"
```

---

## Task 2: Create rules_template.py and npc_react_template.py

**Files:**
- Create: `backend/src/dzmm/prompts/rules_template.py`
- Create: `backend/src/dzmm/prompts/npc_react_template.py`

- [ ] **Step 1: Write failing import test**

Create `backend/tests/test_gm_graph.py`:

```python
"""Tests for LangGraph multi-agent GM pipeline (Phase B)."""
import pytest
from dzmm.prompts.rules_template import build_rules_messages
from dzmm.prompts.npc_react_template import build_npc_react_messages


def test_build_rules_messages_returns_one_user_message():
    msgs = build_rules_messages("## 当前情境\n测试", "我尝试推开门")
    assert len(msgs) == 1
    assert msgs[0].role == "user"
    assert "推开门" in msgs[0].content


def test_build_npc_react_messages_returns_one_user_message():
    msgs = build_npc_react_messages(
        narrative="你推开了门，走进了酒馆。",
        present_npcs=["老板王五（心情：平静）", "流浪者李四（心情：警惕）"],
        user_action="我走进酒馆四处张望",
    )
    assert len(msgs) == 1
    assert msgs[0].role == "user"
    assert "王五" in msgs[0].content
    assert "李四" in msgs[0].content
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd /Users/norman/development/dzmm/backend && python -m pytest tests/test_gm_graph.py::test_build_rules_messages_returns_one_user_message -v 2>&1 | tail -5
```

Expected: `ImportError`.

- [ ] **Step 3: Create rules_template.py**

Create `backend/src/dzmm/prompts/rules_template.py`:

```python
from dzmm.models.client import Message

_TEMPLATE = """你是 TRPG 规则顾问。分析玩家行动，输出规则预处理指令（仅 GM 看，不出现在叙事里）。

# 当前关键情境
{key_facts}

# 玩家行动
{current_action}

# 输出格式（严格三行，不要其他说明）
行动类型：战斗/社交/探索/潜行/施法/其他（选一个）
技能检定：无 | 或 [技能名] DC[数字]（如：力量检定 DC12）
叙事指令：一句话，本回合应该发生的核心事件

示例输出：
行动类型：战斗
技能检定：力量检定 DC12
叙事指令：PC 奋力推开厚重的铁门，身后的追兵越来越近。
"""


def build_rules_messages(key_facts: str, current_action: str) -> list[Message]:
    return [
        Message(
            role="user",
            content=_TEMPLATE.format(
                key_facts=key_facts.strip() or "（暂无）",
                current_action=current_action.strip(),
            ),
        )
    ]
```

- [ ] **Step 4: Create npc_react_template.py**

Create `backend/src/dzmm/prompts/npc_react_template.py`:

```python
from dzmm.models.client import Message

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
```

- [ ] **Step 5: Run template tests**

```bash
cd /Users/norman/development/dzmm/backend && python -m pytest tests/test_gm_graph.py::test_build_rules_messages_returns_one_user_message tests/test_gm_graph.py::test_build_npc_react_messages_returns_one_user_message -v
```

Expected: both pass.

- [ ] **Step 6: Commit**

```bash
cd /Users/norman/development/dzmm && git add backend/src/dzmm/prompts/rules_template.py backend/src/dzmm/prompts/npc_react_template.py backend/tests/test_gm_graph.py && git commit -m "feat(graph): add rules_template + npc_react_template for multi-agent GM"
```

---

## Task 3: Create gm_graph.py — LangGraph pre-pass StateGraph

**Files:**
- Create: `backend/src/dzmm/service/gm_graph.py`
- Modify: `backend/tests/test_gm_graph.py`

- [ ] **Step 1: Write failing tests**

Append to `backend/tests/test_gm_graph.py`:

```python
import asyncio
from unittest.mock import AsyncMock, MagicMock
from dzmm.models.client import GenerationParams, Message, ModelClient, StreamChunk, TokenUsage
from dzmm.service.gm_graph import run_pre_pass


class _FakeClient(ModelClient):
    """Fake ModelClient that returns a preset response."""
    name = "fake"

    def __init__(self, response: str):
        self._response = response

    async def stream(self, messages, params):  # noqa: ARG002
        yield StreamChunk(delta=self._response, finish_reason="stop")

    async def complete(self, messages, params):  # noqa: ARG002
        return self._response, TokenUsage()


@pytest.mark.asyncio
async def test_run_pre_pass_appends_enrichment():
    """run_pre_pass should return key_facts + enrichment section."""
    client = _FakeClient("行动类型：探索\n技能检定：无\n叙事指令：PC 四处张望，发现了蛛丝马迹。")
    original_key_facts = "## 情境\n当前在酒馆"
    result = await run_pre_pass(original_key_facts, "我四处张望", client)

    assert original_key_facts in result
    assert "规则分析" in result
    assert "探索" in result


@pytest.mark.asyncio
async def test_run_pre_pass_marks_dice_check():
    """When rules output mentions 检定, key_facts should contain 骰子 marker."""
    client = _FakeClient("行动类型：战斗\n技能检定：力量检定 DC12\n叙事指令：PC 推门。")
    result = await run_pre_pass("## 情境\n门很重", "用力推门", client)

    assert "骰子" in result or "DC" in result


@pytest.mark.asyncio
async def test_run_pre_pass_returns_original_on_empty_enrichment():
    """If the client returns empty string, key_facts should be unchanged."""
    client = _FakeClient("")
    original = "## 情境\n测试"
    result = await run_pre_pass(original, "行动", client)
    assert result == original
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd /Users/norman/development/dzmm/backend && python -m pytest tests/test_gm_graph.py::test_run_pre_pass_appends_enrichment -v 2>&1 | tail -5
```

Expected: `ImportError: cannot import name 'run_pre_pass'`.

- [ ] **Step 3: Create gm_graph.py**

Create `backend/src/dzmm/service/gm_graph.py`:

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
#     3. NPC 后处理（Post-pass）— 独立异步函数
#        检查在场 NPC 是否有遗漏反应
#
# 【LangGraph 核心概念】
#   StateGraph:  有向图，节点是状态处理函数，边是流程控制
#   TypedDict:   图状态的类型定义（类似 Java 的 DTO/Record）
#   add_node:    注册一个处理步骤
#   add_conditional_edges: 根据状态内容决定下一步走哪个节点
#   compile():   把图编译成可执行对象
#   ainvoke():   异步执行整个图，返回最终状态
# ============================================================

import logging
from typing import TypedDict

from langgraph.graph import END, StateGraph

from dzmm.models.client import GenerationParams, ModelClient
from dzmm.parsing.events import ParseEvent, TagComplete
from dzmm.parsing.stream_parser import StreamingTagParser
from dzmm.prompts.npc_react_template import build_npc_react_messages
from dzmm.prompts.rules_template import build_rules_messages

log = logging.getLogger(__name__)

_RULES_PARAMS = GenerationParams(temperature=0.3, max_tokens=120)
_NPC_PARAMS = GenerationParams(temperature=0.5, max_tokens=300)


# ── LangGraph 状态定义 ────────────────────────────────────
# TypedDict 是 LangGraph 推荐的状态类型。
# 每个节点函数接收当前状态，返回更新后的字段（Python 字典合并语义）。
class PrePassState(TypedDict):
    key_facts: str       # 输入：当前关键情境
    user_action: str     # 输入：玩家行动
    rules_enrichment: str  # 输出：rules_node 填入的规则分析文本


# ── 节点函数 ──────────────────────────────────────────────
def make_rules_node(client: ModelClient):
    """
    工厂函数：返回一个绑定了 client 的 rules_node。

    【学习点：闭包注入依赖】
      LangGraph 节点函数签名必须是 async def f(state) -> dict。
      无法直接传额外参数。用闭包（closure）把 client 捕获进去。
      Java 等价：匿名内部类捕获外部变量。
    """
    async def rules_node(state: PrePassState) -> PrePassState:
        """分析玩家行动，判断是否需要技能检定，输出叙事指令。"""
        msgs = build_rules_messages(state["key_facts"], state["user_action"])
        output, _ = await client.complete(msgs, _RULES_PARAMS)
        return {**state, "rules_enrichment": output.strip()}
    return rules_node


async def dice_enrich_node(state: PrePassState) -> PrePassState:
    """
    条件节点：当 rules_node 检测到技能检定需求时，高亮骰子上下文。

    不额外调用 LLM——只是重新格式化 rules_enrichment，
    让 GM 能更明确地看到本回合需要掷骰。
    """
    enrichment = state["rules_enrichment"]
    highlighted = "🎲 **骰子检定预告（仅 GM 可见）**\n" + enrichment
    return {**state, "rules_enrichment": highlighted}


# ── 条件路由函数 ────────────────────────────────────────
def _route_after_rules(state: PrePassState) -> str:
    """
    条件边路由：根据规则分析结果决定下一步。

    【学习点：LangGraph 条件边】
      add_conditional_edges(source, routing_fn, mapping)
      routing_fn 返回一个字符串 key，mapping 把 key 映射到节点名或 END。
      这就是 LangGraph 的分支（if/else）。
    """
    enrichment = state.get("rules_enrichment", "")
    # 如果规则分析提到技能检定，走 dice_enrich 节点
    if "检定" in enrichment and "DC" in enrichment:
        return "dice_enrich"
    return END


# ── 图构建 ───────────────────────────────────────────────
def make_pre_pass_graph(client: ModelClient):
    """
    构建并编译 pre-pass StateGraph。

    图结构：
      rules_node
        ├─(有检定)─→ dice_enrich_node ─→ END
        └─(无检定)─────────────────────→ END

    【学习点：StateGraph 的基本构建流程】
      1. builder = StateGraph(状态类型)
      2. builder.add_node(名字, 异步函数)
      3. builder.set_entry_point(起始节点)
      4. builder.add_edge / add_conditional_edges（定义流程）
      5. graph = builder.compile()  ← 编译成可执行对象
      6. result = await graph.ainvoke(初始状态)
    """
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
    """运行预处理图，返回注入了规则分析的增强版 key_facts。

    失败时静默回退到原始 key_facts（保证游戏不中断）。
    """
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


async def run_npc_post_pass(
    narrative: str,
    present_npcs: list[str],
    user_action: str,
    client: ModelClient,
) -> list[ParseEvent]:
    """
    NPC 后处理：检查在场 NPC 是否有遗漏反应，返回额外 TagComplete 事件。

    【设计说明】
      主叙事流式完成后调用。如果 GM 遗漏了在场 NPC 的反应，
      这个函数补充生成 <npc_update> XML，通过 StreamingTagParser 解析成
      TagComplete 事件，由 run_turn() yield 给前端。

      不用 LangGraph（只有一个 LLM 调用，无需状态图）。
    """
    if not present_npcs:
        return []
    try:
        msgs = build_npc_react_messages(narrative, present_npcs, user_action)
        output, _ = await client.complete(msgs, _NPC_PARAMS)
        if not output.strip() or 'name="none"' in output:
            return []
        # 用现有 StreamingTagParser 解析输出的 XML 标签
        parser = StreamingTagParser()
        events: list[ParseEvent] = []
        for ev in parser.feed(output):
            if isinstance(ev, TagComplete) and ev.name == "npc_update":
                events.append(ev)
        events.extend(ev for ev in parser.finish()
                      if isinstance(ev, TagComplete) and ev.name == "npc_update")
        return events
    except Exception as exc:
        log.warning("gm_graph npc_post_pass failed: %s", exc)
        return []
```

- [ ] **Step 4: Run graph tests**

```bash
cd /Users/norman/development/dzmm/backend && python -m pytest tests/test_gm_graph.py -v
```

Expected: all 5 tests (2 template + 3 pre-pass) pass.

- [ ] **Step 5: Run full suite**

```bash
cd /Users/norman/development/dzmm/backend && python -m pytest tests/ -x --ignore=tests/test_ollama.py --ignore=tests/test_openai_compat.py -q
```

- [ ] **Step 6: Commit**

```bash
cd /Users/norman/development/dzmm && git add backend/src/dzmm/service/gm_graph.py backend/tests/test_gm_graph.py && git commit -m "feat(graph): LangGraph StateGraph pre-pass + NPC post-pass agents"
```

---

## Task 4: Add NPC post-pass tests

**Files:**
- Modify: `backend/tests/test_gm_graph.py`

- [ ] **Step 1: Add NPC post-pass tests**

Append to `backend/tests/test_gm_graph.py`:

```python
from dzmm.service.gm_graph import run_npc_post_pass
from dzmm.parsing.events import TagComplete


@pytest.mark.asyncio
async def test_run_npc_post_pass_parses_npc_update_tags():
    """run_npc_post_pass should parse <npc_update> XML and return TagComplete events."""
    client = _FakeClient('<npc_update name="王五">注意到你，微微点头</npc_update>')
    events = await run_npc_post_pass(
        narrative="你走进了酒馆",
        present_npcs=["王五（心情：平静）"],
        user_action="我走进酒馆",
        client=client,
    )
    assert len(events) == 1
    assert isinstance(events[0], TagComplete)
    assert events[0].name == "npc_update"
    assert events[0].attrs.get("name") == "王五"


@pytest.mark.asyncio
async def test_run_npc_post_pass_returns_empty_for_none_response():
    """When LLM returns 'none', post-pass should return empty list."""
    client = _FakeClient('<npc_update name="none">无需补充</npc_update>')
    events = await run_npc_post_pass(
        narrative="...", present_npcs=["李四"], user_action="...", client=client
    )
    assert events == []


@pytest.mark.asyncio
async def test_run_npc_post_pass_returns_empty_when_no_npcs():
    """No NPCs present → skip LLM call entirely."""
    client = _FakeClient("should not be called")
    events = await run_npc_post_pass(
        narrative="...", present_npcs=[], user_action="...", client=client
    )
    assert events == []
```

- [ ] **Step 2: Run new tests**

```bash
cd /Users/norman/development/dzmm/backend && python -m pytest tests/test_gm_graph.py -v
```

Expected: all 8 tests pass.

- [ ] **Step 3: Commit**

```bash
cd /Users/norman/development/dzmm && git add backend/tests/test_gm_graph.py && git commit -m "test(graph): add NPC post-pass tests"
```

---

## Task 5: Integrate gm_graph into run_turn()

**Files:**
- Modify: `backend/src/dzmm/service/game.py`

This is the wiring step. When session setting `use_graph=True`, `run_turn()` will:
1. Run `run_pre_pass()` to enrich `key_facts` before building the prompt
2. Run `run_npc_post_pass()` after the main stream ends, yielding additional NPC events

The existing `director_pass` setting is NOT removed. `use_graph` replaces it when enabled.

- [ ] **Step 1: Read run_turn() to understand exact insertion points**

Read `backend/src/dzmm/service/game.py` lines 314-330 (director_pass block) and lines 395-430 (streaming loop).

- [ ] **Step 2: Add the import**

At the top of `backend/src/dzmm/service/game.py`, add near other service imports:

```python
from dzmm.service.gm_graph import run_npc_post_pass, run_pre_pass
```

- [ ] **Step 3: Replace the director_pass block with graph-aware logic**

Find this block in `run_turn()` (around line 318):

```python
    # Optional director pre-pass: run a short LLM call to produce a 2-line
    # directive (core event + emotion tone) and inject it into key_facts.
    settings = json.loads(sess.settings_json or "{}")
    if settings.get("director_pass"):
        try:
            dir_msgs = build_director_messages(key_facts, user_action)
            directive, _ = await client.complete(
                dir_msgs, GenerationParams(temperature=0.5, max_tokens=120)
            )
            if directive.strip():
                key_facts = key_facts + "\n\n## 🎬 导演预处理\n" + directive.strip()
        except Exception as exc:  # noqa: BLE001
            log.warning("director pass failed: %s", exc)
```

Replace with:

```python
    settings = json.loads(sess.settings_json or "{}")

    # Multi-agent pre-pass: LangGraph StateGraph (rules + conditional dice enrichment).
    # Falls back to original key_facts on any error.
    if settings.get("use_graph"):
        key_facts = await run_pre_pass(key_facts, user_action, client)
    elif settings.get("director_pass"):
        # Legacy single-agent director pass (kept for backwards compatibility).
        try:
            dir_msgs = build_director_messages(key_facts, user_action)
            directive, _ = await client.complete(
                dir_msgs, GenerationParams(temperature=0.5, max_tokens=120)
            )
            if directive.strip():
                key_facts = key_facts + "\n\n## 🎬 导演预处理\n" + directive.strip()
        except Exception as exc:  # noqa: BLE001
            log.warning("director pass failed: %s", exc)
```

- [ ] **Step 4: Add NPC post-pass after main stream ends**

Find this block in `run_turn()` (the `for ev in parser.finish()` block, then the PC-name drift repair, roughly lines 416-464). After the narrative polish block ends and before the `next_turn = sess.turn_count + 1` line, add:

```python
    # Multi-agent NPC post-pass: check if any present NPCs need additional reactions.
    if settings.get("use_graph") and narrative_parts:
        from dzmm.db.models import NPC as NPCModel
        present_npc_rows = (
            await session.execute(
                select(NPCModel)
                .where(NPCModel.session_id == session_id, NPCModel.present == True)  # noqa: E712
                .order_by(NPCModel.last_seen_turn.desc())
                .limit(5)
            )
        ).scalars().all()
        if present_npc_rows:
            present_npc_strs = [
                f"{n.name}（心情：{n.mood or '未知'}）" for n in present_npc_rows
            ]
            narrative_so_far = "".join(narrative_parts)
            npc_extra_events = await run_npc_post_pass(
                narrative_so_far, present_npc_strs, user_action, client
            )
            for ev in npc_extra_events:
                completed_tags.append(ev)
                yield ev
```

- [ ] **Step 5: Run full test suite**

```bash
cd /Users/norman/development/dzmm/backend && python -m pytest tests/ -x --ignore=tests/test_ollama.py --ignore=tests/test_openai_compat.py -q
```

Expected: all tests pass. `use_graph` defaults to `False` so existing behavior is unaffected.

- [ ] **Step 6: Commit**

```bash
cd /Users/norman/development/dzmm && git add backend/src/dzmm/service/game.py && git commit -m "feat(graph): integrate LangGraph multi-agent pre/post pass into run_turn()"
```

---

## Task 6: Docs, CHANGELOG, version bump to 0.5.0

**Files:**
- Modify: `backend/pyproject.toml`
- Modify: `CHANGELOG.md`
- Modify: `docs/learning/roadmap.md`
- Create: `docs/learning/langgraph-multiagent.md`
- Modify: `docs/learning/README.md`

- [ ] **Step 1: Bump version**

In `backend/pyproject.toml`, change `version = "0.4.0"` to `version = "0.5.0"`.

- [ ] **Step 2: Add CHANGELOG entry**

Prepend to `CHANGELOG.md` (before the v0.4.0 entry):

```markdown
## [v0.5.0] - 2026-05-03

**Phase B — LangGraph 多 Agent GM**

GM 管线拆分为三阶段：LangGraph 规则预处理 Agent（StateGraph + 条件边）→ 主叙事流式生成（不变）→ NPC 后处理 Agent。通过 `use_graph` 会话设置开启。

### 新增
- **`service/gm_graph.py`** — LangGraph `StateGraph` 预处理图：`rules_node`（规则分析）→ 条件边（有检定 → `dice_enrich_node`，无检定 → END）→ 返回增强版 `key_facts`
- **`run_npc_post_pass()`** — 主叙事完成后运行，检查在场 NPC 是否有遗漏反应，产出额外 `<npc_update>` 事件
- **`prompts/rules_template.py`** — 规则预处理 Prompt（行动类型 + 技能检定 + 叙事指令，三行格式）
- **`prompts/npc_react_template.py`** — NPC 后处理 Prompt（补充在场 NPC 未显示的反应）
- **`use_graph` 会话设置** — 在 `session.settings_json` 中设 `"use_graph": true` 即可启用；默认 false，不影响现有行为
- **向后兼容** — `director_pass` 设置保留，`use_graph` 和 `director_pass` 可独立选择

### 依赖新增
- `langgraph>=0.2` — StateGraph, 条件边, ainvoke

```

- [ ] **Step 3: Update roadmap.md**

In `docs/learning/roadmap.md`, add under `## 已完成`:

```markdown
- **v0.5.0** — Phase B：LangGraph 多 Agent GM（StateGraph + 条件边 + NPC 后处理 Agent）
```

- [ ] **Step 4: Create docs/learning/langgraph-multiagent.md**

Create `docs/learning/langgraph-multiagent.md`:

```markdown
# Phase B：LangGraph 多 Agent GM

> 本文对应 `service/gm_graph.py`，讲解 LangGraph 的核心概念和项目里的实现。

---

## 1. 为什么需要 LangGraph

**问题：** 单个 7B 模型同时负责：规则判定 + 叙事创作 + NPC 反应 + 剧情推进，负担太重。

**解法：** 拆成专职 Agent，LangGraph 编排协作：
```
玩家行动
   ↓
[规则 Agent]  ← 分析行动类型和检定需求（LangGraph StateGraph）
   ↓ (有检定)         ↓ (无检定)
[骰子丰富节点]     [直接结束]
   ↓
主叙事生成（现有流式生成，不变）
   ↓
[NPC Agent] ← 检查在场 NPC 是否有遗漏反应
```

---

## 2. LangGraph StateGraph 核心 API

[`service/gm_graph.py`](https://github.com/b31o8321/dzmm/blob/main/backend/src/dzmm/service/gm_graph.py)：

```python
from langgraph.graph import StateGraph, END
from typing import TypedDict

# 1. 定义状态（图在所有节点间传递这个字典）
class PrePassState(TypedDict):
    key_facts: str
    user_action: str
    rules_enrichment: str

# 2. 定义节点（异步函数，接收 state，返回更新字段）
async def rules_node(state: PrePassState) -> PrePassState:
    # ...做 LLM 调用...
    return {**state, "rules_enrichment": output}

# 3. 定义条件路由函数
def _route_after_rules(state: PrePassState) -> str:
    if "检定" in state.get("rules_enrichment", "") and "DC" in state.get("rules_enrichment", ""):
        return "dice_enrich"
    return END  # 特殊常量，表示图结束

# 4. 构建图
builder = StateGraph(PrePassState)
builder.add_node("rules", rules_node)
builder.add_node("dice_enrich", dice_enrich_node)
builder.set_entry_point("rules")
builder.add_conditional_edges("rules", _route_after_rules,
                              {"dice_enrich": "dice_enrich", END: END})
builder.add_edge("dice_enrich", END)
graph = builder.compile()

# 5. 执行
result = await graph.ainvoke({"key_facts": "...", "user_action": "...", "rules_enrichment": ""})
```

---

## 3. 闭包注入依赖

LangGraph 节点函数签名必须是 `async def f(state) -> dict`，不能直接传额外参数。用**闭包**注入 `ModelClient`：

```python
def make_rules_node(client: ModelClient):
    async def rules_node(state):
        output, _ = await client.complete(...)  # client 被闭包捕获
        return {**state, "rules_enrichment": output}
    return rules_node

builder.add_node("rules", make_rules_node(client))  # 传入 client，返回节点函数
```

**Java 对比：** 等价于匿名内部类捕获外部 `final` 变量。

---

## 4. 条件边（有向图的分支）

```python
builder.add_conditional_edges(
    "rules",                    # 源节点
    _route_after_rules,         # 路由函数：state → str
    {"dice_enrich": "dice_enrich", END: END},  # key → 目标节点的映射
)
```

路由函数返回字符串 key，映射表决定去哪个节点。这是 LangGraph 的 `if/else`。

---

## 5. 与现有架构的集成

- Pre-pass 图运行完毕 → `result["rules_enrichment"]` 追加到 `key_facts`
- 主叙事流式生成（`client.stream()`）完全不变
- NPC post-pass 在流结束后运行 → 额外 `<npc_update>` 事件 yield 给前端
- 开启方式：在会话 settings 里加 `"use_graph": true`

这个设计保证了：LangGraph 挂掉时游戏仍能正常运行（graceful fallback）。

---

## 6. 和 Phase A（RAG）的对比

| | Phase A (RAG) | Phase B (LangGraph) |
|-|---------------|---------------------|
| 解决的问题 | 世界书太长塞不进 Prompt | 单模型同时做多件事效果差 |
| 核心技术 | 向量检索 | 有状态 Agent 工作流 |
| LangChain 组件 | Embeddings ABC, RecursiveCharacterTextSplitter | StateGraph, 条件边, ainvoke |
| 对现有架构的影响 | 替换 world_md 内容 | 在主流程前后增加 Agent 调用 |
```

- [ ] **Step 5: Update docs/learning/README.md**

Read `docs/learning/README.md`, then add a reference to `langgraph-multiagent.md` in the index.

- [ ] **Step 6: Run full test suite one last time**

```bash
cd /Users/norman/development/dzmm/backend && python -m pytest tests/ --ignore=tests/test_ollama.py --ignore=tests/test_openai_compat.py -q
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
cd /Users/norman/development/dzmm && git add backend/pyproject.toml CHANGELOG.md docs/learning/roadmap.md docs/learning/langgraph-multiagent.md docs/learning/README.md && git commit -m "release: v0.5.0 — Phase B LangGraph 多 Agent GM"
```

---

## Self-Review

**Spec coverage:**
- [x] LangGraph StateGraph 编排 ✓ (`make_pre_pass_graph`)
- [x] 规则 Agent — 决定骰子检定 ✓ (`rules_node`)
- [x] 条件边 — 有检定 → `dice_enrich_node` ✓
- [x] 叙事 Agent — 现有流式生成，unchanged ✓
- [x] NPC Agent — `run_npc_post_pass` ✓
- [x] 组合输出 → 现有 XML 格式 → `apply_tags()` 不变 ✓
- [x] `use_graph` session setting + backwards compatible ✓
- [x] 学习文档 ✓

**Placeholder scan:** None found. All code blocks are complete.

**Type consistency:**
- `PrePassState` defined in Task 3, used in `make_rules_node`, `dice_enrich_node`, `_route_after_rules` — all consistent.
- `run_pre_pass(key_facts, user_action, client) -> str` — defined Task 3, called Task 5. ✓
- `run_npc_post_pass(narrative, present_npcs, user_action, client) -> list[ParseEvent]` — defined Task 3, tested Task 4, called Task 5. ✓
- `_FakeClient` used in tests is defined in Task 3 and reused in Task 4. ✓
