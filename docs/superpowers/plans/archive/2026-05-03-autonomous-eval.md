# Phase C: 自主 Agent 自动评测 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an autonomous evaluation framework with a Player Agent (generates actions) and a Judge Agent (LLM-as-Judge scoring), orchestrated by a runner that plays N turns and compares single GM vs multi-agent GM quality.

**Architecture:** `eval/player_agent.py` generates player actions from session history using an LLM. `eval/judge_agent.py` scores every 10 turns on 4 dimensions (plot speed, rule violations, RP immersion, dice accuracy) using JSON output. `eval/runner.py` calls `run_turn()` directly, orchestrates turns, and persists `EvalScore` entries to the existing `feedbacks` DB table. `eval/cli.py` is the entry point that takes an existing session ID, runs evaluation, and generates a Markdown report.

**Tech Stack:** Existing `ModelClient`/`run_turn()` infrastructure, existing `Feedback` ORM model (`feedbacks` table), Python `argparse` for CLI, `dataclasses` for typed scores.

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `backend/src/dzmm/prompts/player_template.py` | Player agent action-generation prompt |
| Create | `backend/src/dzmm/prompts/judge_template.py` | Judge agent scoring prompt (JSON output) |
| Create | `backend/src/dzmm/eval/__init__.py` | Package marker |
| Create | `backend/src/dzmm/eval/player_agent.py` | `generate_player_action()` |
| Create | `backend/src/dzmm/eval/judge_agent.py` | `EvalScore`, `judge_session()` |
| Create | `backend/src/dzmm/eval/runner.py` | `EvalConfig`, `run_eval()` |
| Create | `backend/src/dzmm/eval/report.py` | `generate_report()` |
| Create | `backend/src/dzmm/eval/cli.py` | CLI entry point |
| Create | `backend/tests/test_eval.py` | Unit tests for all eval components |
| Modify | `backend/pyproject.toml` | Bump version 0.5.0 → 0.6.0 |
| Modify | `CHANGELOG.md` | Add v0.6.0 entry |
| Modify | `docs/learning/roadmap.md` | Mark Phase C complete |
| Create | `docs/learning/agent-eval.md` | Phase C learning doc |
| Modify | `docs/learning/README.md` | Add agent-eval.md to index |

---

## Task 1: Create prompt templates

**Files:**
- Create: `backend/src/dzmm/prompts/player_template.py`
- Create: `backend/src/dzmm/prompts/judge_template.py`

- [ ] **Step 1: Write failing import test**

Create `backend/tests/test_eval.py`:

```python
"""Tests for Phase C autonomous evaluation agents."""
import json
import pytest
from dzmm.models.client import GenerationParams, ModelClient, StreamChunk, TokenUsage
from dzmm.prompts.player_template import build_player_messages
from dzmm.prompts.judge_template import build_judge_messages


class _FakeClient(ModelClient):
    name = "fake"

    def __init__(self, response: str):
        self._response = response

    async def stream(self, messages, params):  # noqa: ARG002
        yield StreamChunk(delta=self._response, finish_reason="stop")

    async def complete(self, messages, params):  # noqa: ARG002
        return self._response, TokenUsage()


def test_build_player_messages_includes_history():
    msgs = build_player_messages(
        character_name="林峰",
        character_md="林峰，一名侦探，沉默寡言。",
        recent_history=[("我走进房间", "你看到一具尸体倒在地板上，窗户半开。")],
    )
    assert len(msgs) == 1
    assert msgs[0].role == "user"
    assert "林峰" in msgs[0].content
    assert "尸体" in msgs[0].content


def test_build_judge_messages_includes_history():
    msgs = build_judge_messages(
        world_summary="维多利亚时代的伦敦，充满迷雾和阴谋。",
        recent_history=[("我检查现场", "你发现了一枚奇怪的徽章。")],
        n_turns=1,
    )
    assert len(msgs) == 1
    assert msgs[0].role == "user"
    assert "维多利亚" in msgs[0].content
    assert "plot_speed" in msgs[0].content
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd /Users/norman/development/dzmm/backend && python -m pytest tests/test_eval.py::test_build_player_messages_includes_history -v 2>&1 | tail -5
```

Expected: `ImportError`.

- [ ] **Step 3: Create player_template.py**

Create `backend/src/dzmm/prompts/player_template.py`:

```python
from dzmm.models.client import Message

_TEMPLATE = """你是一名 TRPG 玩家 Agent，正在扮演角色 {character_name}。
根据最近的对话历史，决定你的下一个行动。

# 角色简介
{character_md}

# 最近对话（旧→新）
{recent_history}

# 行动要求
- 直接输出玩家行动（1-2 句话，第一人称）
- 行动要符合角色性格和当前情境
- 可以选择：探索/对话/战斗/使用物品/调查/等待 等类型
- 不要重复刚刚做过的行动
- 只输出行动本身，不要任何前缀或解释

输出："""


def build_player_messages(
    character_name: str,
    character_md: str,
    recent_history: list[tuple[str, str]],  # list of (player_action, gm_response)
) -> list[Message]:
    history_text = "\n\n".join(
        f"[玩家] {action}\n[GM] {response}"
        for action, response in recent_history[-5:]  # Last 5 exchanges
    ) or "（游戏刚开始）"

    return [
        Message(
            role="user",
            content=_TEMPLATE.format(
                character_name=character_name.strip() or "玩家",
                character_md=character_md.strip() or "（未设定）",
                recent_history=history_text,
            ),
        )
    ]
```

- [ ] **Step 4: Create judge_template.py**

Create `backend/src/dzmm/prompts/judge_template.py`:

```python
from dzmm.models.client import Message

_TEMPLATE = """你是 TRPG 质量评审 Agent。评估以下游戏对话（最近 {n_turns} 回合）的质量。

# 世界观摘要
{world_summary}

# 最近对话记录
{recent_history}

# 评分维度
1. **剧情推进速度**（plot_speed, 0-10）：主线事件是否有推进？每2-3回合是否有明显进展？
2. **铁律违反次数**（rule_violations, 整数）：GM 明显规则违反次数（0=完美）
3. **RP 沉浸感**（rp_immersion, 0-10）：叙事是否生动？NPC 是否有个性？
4. **骰子规则准确性**（dice_accuracy, 0-10）：骰子判定是否合理？失败是否有实质后果？（无骰子记 7）

# 输出格式（严格 JSON，不要其他内容）
{{
  "plot_speed": 数字,
  "rule_violations": 整数,
  "rp_immersion": 数字,
  "dice_accuracy": 数字,
  "reasoning": "一句话总体评价（50字以内）"
}}"""


def build_judge_messages(
    world_summary: str,
    recent_history: list[tuple[str, str]],  # list of (player_action, gm_response)
    n_turns: int,
) -> list[Message]:
    history_text = "\n\n".join(
        f"[回合 {i+1}]\n玩家：{action}\nGM：{response[:300]}{'...' if len(response) > 300 else ''}"
        for i, (action, response) in enumerate(recent_history)
    ) or "（无对话记录）"

    return [
        Message(
            role="user",
            content=_TEMPLATE.format(
                world_summary=(world_summary or "（未提供）")[:500],
                recent_history=history_text,
                n_turns=n_turns,
            ),
        )
    ]
```

- [ ] **Step 5: Run template tests**

```bash
cd /Users/norman/development/dzmm/backend && python -m pytest tests/test_eval.py::test_build_player_messages_includes_history tests/test_eval.py::test_build_judge_messages_includes_history -v
```

Expected: both pass.

- [ ] **Step 6: Commit**

```bash
cd /Users/norman/development/dzmm && git add backend/src/dzmm/prompts/player_template.py backend/src/dzmm/prompts/judge_template.py backend/tests/test_eval.py && git commit -m "feat(eval): add player_template + judge_template for Phase C autonomous eval"
```

---

## Task 2: Create player_agent.py and judge_agent.py

**Files:**
- Create: `backend/src/dzmm/eval/__init__.py`
- Create: `backend/src/dzmm/eval/player_agent.py`
- Create: `backend/src/dzmm/eval/judge_agent.py`
- Modify: `backend/tests/test_eval.py`

- [ ] **Step 1: Write failing tests**

Append to `backend/tests/test_eval.py`:

```python
from dzmm.eval.player_agent import generate_player_action
from dzmm.eval.judge_agent import EvalScore, judge_session


def _fake_message(role: str, content: str, turn: int = 1):
    """Build a minimal dict that mimics the Message ORM fields we need."""
    class _Msg:
        pass
    m = _Msg()
    m.role = role
    m.content = content
    m.turn = turn
    return m


@pytest.mark.asyncio
async def test_generate_player_action_returns_nonempty_string():
    client = _FakeClient("我小心翼翼地推开门，走进了房间。")
    msgs = [
        _fake_message("user", "我走进酒馆"),
        _fake_message("assistant", "你看到一个昏暗的大厅，几个陌生人坐在角落。"),
    ]
    action = await generate_player_action(
        messages=msgs,
        character_md="林峰，侦探，谨慎。",
        character_name="林峰",
        client=client,
    )
    assert isinstance(action, str)
    assert len(action) > 0
    assert "推开门" in action


@pytest.mark.asyncio
async def test_judge_session_parses_valid_json():
    valid_json = json.dumps({
        "plot_speed": 7,
        "rule_violations": 1,
        "rp_immersion": 8,
        "dice_accuracy": 9,
        "reasoning": "剧情推进顺畅。",
    })
    client = _FakeClient(valid_json)
    msgs = [
        _fake_message("user", "我检查现场", turn=1),
        _fake_message("assistant", "你发现了一枚徽章。", turn=1),
    ]
    score = await judge_session(
        messages=msgs,
        world_summary="维多利亚伦敦",
        session_id=1,
        turn=10,
        config_name="single_gm",
        client=client,
    )
    assert isinstance(score, EvalScore)
    assert score.plot_speed == 7
    assert score.rule_violations == 1
    assert score.rp_immersion == 8
    assert score.dice_accuracy == 9
    assert score.session_id == 1
    assert score.turn == 10
    assert score.config_name == "single_gm"


@pytest.mark.asyncio
async def test_judge_session_handles_malformed_json():
    """judge_session should return a default score (5.0 all dims) on parse failure."""
    client = _FakeClient("这是一个非 JSON 回复，无法解析。")
    msgs = [_fake_message("user", "行动", turn=1)]
    score = await judge_session(
        messages=msgs,
        world_summary="",
        session_id=2,
        turn=5,
        config_name="test",
        client=client,
    )
    assert isinstance(score, EvalScore)
    assert score.plot_speed == 5.0
    assert score.rule_violations == 0
    assert "parse" in score.reasoning.lower() or score.reasoning != ""


@pytest.mark.asyncio
async def test_eval_score_overall_property():
    score = EvalScore(
        session_id=1, turn=10, config_name="test",
        plot_speed=8.0, rule_violations=0,
        rp_immersion=7.0, dice_accuracy=9.0,
        reasoning="good",
    )
    # overall = (plot_speed + (10 - violations*2) + rp_immersion + dice_accuracy) / 4
    expected = (8.0 + 10.0 + 7.0 + 9.0) / 4
    assert abs(score.overall - expected) < 0.01
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd /Users/norman/development/dzmm/backend && python -m pytest tests/test_eval.py::test_generate_player_action_returns_nonempty_string -v 2>&1 | tail -5
```

Expected: `ImportError: cannot import name 'generate_player_action'`.

- [ ] **Step 3: Create eval/__init__.py**

Create `backend/src/dzmm/eval/__init__.py` (empty file — just package marker):

```python
```

- [ ] **Step 4: Create eval/player_agent.py**

Create `backend/src/dzmm/eval/player_agent.py`:

```python
# ============================================================
# Player Agent — 自主玩家 Agent
# ============================================================
# 使用 LLM 根据对话历史自动生成玩家行动。
# 在评测框架中充当"机器玩家"，让系统无需人类就能跑完整局游戏。
# ============================================================

import logging
from dzmm.models.client import GenerationParams, ModelClient
from dzmm.prompts.player_template import build_player_messages

log = logging.getLogger(__name__)

_PLAYER_PARAMS = GenerationParams(temperature=0.8, max_tokens=100)


async def generate_player_action(
    messages: list,  # list of Message ORM objects
    character_md: str,
    character_name: str,
    client: ModelClient,
) -> str:
    """根据最近对话历史，生成下一个玩家行动。

    【学习点：LLM-as-Agent】
      这个函数把 LLM 变成了一个"自主玩家"。
      它不只是回答问题，而是根据上下文做出决策（选择行动）。
      这是 Agent 的核心：Perceive（感知历史）→ Think（LLM推理）→ Act（输出行动）。
    """
    # 把 ORM Message 对象转成 (player_action, gm_response) 元组列表
    pairs: list[tuple[str, str]] = []
    user_msg: str | None = None
    for msg in messages:
        if msg.role == "user":
            user_msg = msg.content
        elif msg.role == "assistant" and user_msg is not None:
            pairs.append((user_msg, msg.content))
            user_msg = None

    prompt_msgs = build_player_messages(
        character_name=character_name,
        character_md=character_md,
        recent_history=pairs,
    )
    try:
        action, _ = await client.complete(prompt_msgs, _PLAYER_PARAMS)
        action = action.strip()
        if not action:
            return "我四处张望，等待下一步的线索。"
        return action
    except Exception as exc:
        log.warning("player_agent failed: %s", exc)
        return "我思考了一下，决定继续观察周围的环境。"
```

- [ ] **Step 5: Create eval/judge_agent.py**

Create `backend/src/dzmm/eval/judge_agent.py`:

```python
# ============================================================
# Judge Agent — LLM-as-Judge 评审 Agent
# ============================================================
# 旁观对话并对 GM 表现打分。
# 这是"LLM-as-Judge"模式：用 LLM 评估另一个 LLM 的输出质量。
# 返回结构化的 EvalScore，方便统计和比较。
# ============================================================

import json
import logging
import re
from dataclasses import dataclass

from dzmm.models.client import GenerationParams, ModelClient
from dzmm.prompts.judge_template import build_judge_messages

log = logging.getLogger(__name__)

_JUDGE_PARAMS = GenerationParams(temperature=0.2, max_tokens=200)


@dataclass
class EvalScore:
    """单次评审结果。

    【学习点：dataclass】
      @dataclass 自动生成 __init__、__repr__、__eq__。
      Java 对比：类似 Lombok @Data 或 Java 16+ Record，
      但支持可变字段（record 是不可变的）。
    """
    session_id: int
    turn: int
    config_name: str      # "single_gm" | "multi_agent_gm" | 自定义
    plot_speed: float     # 0-10，剧情推进速度
    rule_violations: int  # 规则违反次数（越少越好）
    rp_immersion: float   # 0-10，RP 沉浸感
    dice_accuracy: float  # 0-10，骰子规则准确性
    reasoning: str        # 评审简述

    @property
    def overall(self) -> float:
        """加权综合分（满分 10）。违反每次扣 2 分，但最低 0 分。"""
        viol_penalty = max(0.0, 10.0 - self.rule_violations * 2.0)
        return (self.plot_speed + viol_penalty + self.rp_immersion + self.dice_accuracy) / 4.0


async def judge_session(
    messages: list,  # list of Message ORM objects
    world_summary: str,
    session_id: int,
    turn: int,
    config_name: str,
    client: ModelClient,
) -> EvalScore:
    """评估最近一批回合的 GM 表现，返回 EvalScore。

    【学习点：LLM-as-Judge】
      用 LLM 评估另一个 LLM 的输出。比人工评估快，比规则匹配灵活。
      关键技巧：让评审 LLM 输出结构化 JSON，方便程序解析和统计。
      鲁棒性：对 JSON 解析失败要有 fallback，不能让评测因 LLM 格式不稳定而崩溃。
    """
    # 把 ORM Message 对象转成 (player_action, gm_response) 元组列表
    pairs: list[tuple[str, str]] = []
    user_msg: str | None = None
    for msg in messages:
        if msg.role == "user":
            user_msg = msg.content
        elif msg.role == "assistant" and user_msg is not None:
            pairs.append((user_msg, msg.content))
            user_msg = None

    n_turns = len(pairs)
    prompt_msgs = build_judge_messages(
        world_summary=world_summary,
        recent_history=pairs,
        n_turns=n_turns,
    )

    raw = ""
    try:
        raw, _ = await client.complete(prompt_msgs, _JUDGE_PARAMS)
        data = _parse_judge_output(raw)
        return EvalScore(
            session_id=session_id,
            turn=turn,
            config_name=config_name,
            plot_speed=float(data.get("plot_speed", 5.0)),
            rule_violations=int(data.get("rule_violations", 0)),
            rp_immersion=float(data.get("rp_immersion", 5.0)),
            dice_accuracy=float(data.get("dice_accuracy", 7.0)),
            reasoning=str(data.get("reasoning", "")),
        )
    except Exception as exc:
        log.warning("judge_agent parse failed (turn %d): %s | raw: %.100s", turn, exc, raw)
        return EvalScore(
            session_id=session_id,
            turn=turn,
            config_name=config_name,
            plot_speed=5.0,
            rule_violations=0,
            rp_immersion=5.0,
            dice_accuracy=7.0,
            reasoning=f"parse error: {exc}",
        )


def _parse_judge_output(raw: str) -> dict:
    """三级 JSON 解析：直接解析 → 正则提取 JSON 块 → 抛出异常。"""
    # 级别 1：直接解析
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        pass
    # 级别 2：正则提取第一个 {...} 块
    m = re.search(r"\{[^{}]*\}", raw, re.DOTALL)
    if m:
        try:
            return json.loads(m.group())
        except (ValueError, TypeError):
            pass
    raise ValueError(f"no parseable JSON in judge output: {raw[:200]}")
```

- [ ] **Step 6: Run agent tests**

```bash
cd /Users/norman/development/dzmm/backend && python -m pytest tests/test_eval.py -v
```

Expected: all 6 tests pass (2 template + 4 agent).

- [ ] **Step 7: Run full test suite**

```bash
cd /Users/norman/development/dzmm/backend && python -m pytest tests/ -x --ignore=tests/test_ollama.py --ignore=tests/test_openai_compat.py -q
```

- [ ] **Step 8: Commit**

```bash
cd /Users/norman/development/dzmm && git add backend/src/dzmm/eval/ backend/tests/test_eval.py && git commit -m "feat(eval): add player_agent + judge_agent with EvalScore (Phase C)"
```

---

## Task 3: Create runner.py

**Files:**
- Create: `backend/src/dzmm/eval/runner.py`
- Modify: `backend/tests/test_eval.py`

- [ ] **Step 1: Write failing tests**

Append to `backend/tests/test_eval.py`:

```python
from dzmm.eval.runner import EvalConfig, run_eval
from dzmm.service.game import run_turn
import asyncio
import json as _json
from sqlalchemy import select as _select
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
async def test_run_eval_runs_correct_number_of_turns(tmp_path):
    """run_eval should call run_turn() once per turn and return one score per judge_every turns."""
    from unittest.mock import AsyncMock, patch, MagicMock

    turn_calls = []

    # Fake run_turn: records call, yields nothing (eval discards events)
    async def fake_run_turn(session, session_id, action, client, **kwargs):
        turn_calls.append((session_id, action))
        return
        yield  # Make it an async generator

    # Fake session_maker that returns a mock AsyncSession
    class _FakeSession:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            pass
        async def get(self, cls, pk):
            # Return minimal stubs
            if cls.__name__ == "Session":
                m = MagicMock()
                m.world_id = 1
                m.character_id = 1
                m.settings_json = "{}"
                return m
            if cls.__name__ == "Character":
                m = MagicMock()
                m.profile_md = "林峰，侦探。"
                m.name = "林峰"
                return m
            if cls.__name__ == "World":
                m = MagicMock()
                m.content_md = "维多利亚伦敦"
                return m
            return MagicMock()
        async def execute(self, stmt):
            m = MagicMock()
            m.scalars.return_value.all.return_value = []
            return m
        def add(self, obj): pass
        async def commit(self): pass

    def fake_session_maker():
        return _FakeSession()

    valid_score_json = _json.dumps({
        "plot_speed": 7, "rule_violations": 0,
        "rp_immersion": 8, "dice_accuracy": 9, "reasoning": "good",
    })
    gm_client = _FakeClient("你走进了一个昏暗的房间。")
    player_client = _FakeClient("我检查周围的环境。")
    judge_client = _FakeClient(valid_score_json)

    config = EvalConfig(
        session_id=1,
        config_name="test",
        max_turns=10,
        judge_every=5,
        use_graph=False,
    )

    with patch("dzmm.eval.runner.run_turn", fake_run_turn):
        scores = await run_eval(config, fake_session_maker, gm_client, player_client, judge_client)

    assert len(turn_calls) == 10
    assert len(scores) == 2  # judge runs at turn 5 and turn 10
    assert all(isinstance(s, EvalScore) for s in scores)
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd /Users/norman/development/dzmm/backend && python -m pytest tests/test_eval.py::test_run_eval_runs_correct_number_of_turns -v 2>&1 | tail -5
```

Expected: `ImportError`.

- [ ] **Step 3: Create eval/runner.py**

Create `backend/src/dzmm/eval/runner.py`:

```python
# ============================================================
# Evaluation Runner — 自动评测编排器
# ============================================================
# 把玩家 Agent + GM + 评审 Agent 串联成完整的自动对局。
# 每回合：玩家 Agent 生成行动 → GM 处理回合 → 每 N 回合评审一次
# 结果存入 feedbacks 表（kind="eval_score"）供后续分析。
# ============================================================

import json
import logging
from dataclasses import dataclass, field

from sqlalchemy import select

from dzmm.db.models import (
    Character,
    Feedback,
    Message as MessageRow,
    ModelConfig,
    NPC,
    Session as GameSession,
    World,
)
from dzmm.eval.judge_agent import EvalScore, judge_session
from dzmm.eval.player_agent import generate_player_action
from dzmm.models.client import GenerationParams, ModelClient
from dzmm.service.game import run_turn

log = logging.getLogger(__name__)


@dataclass
class EvalConfig:
    """评测运行配置。"""
    session_id: int
    config_name: str         # 标识符，如 "single_gm" / "multi_agent_gm"
    max_turns: int = 20      # 最多跑多少回合
    judge_every: int = 10    # 每隔多少回合评审一次
    use_graph: bool = False  # 是否启用 Phase B 多 Agent GM


async def run_eval(
    config: EvalConfig,
    session_maker,
    gm_client: ModelClient,
    player_client: ModelClient,
    judge_client: ModelClient,
) -> list[EvalScore]:
    """运行一次完整的自动评测，返回所有评分记录。

    【学习点：自主 Agent 编排】
      这是 Phase C 的核心：三个 Agent 协同工作。
      1. Player Agent：感知历史 → 决策 → 行动
      2. GM（LangGraph/单体）：处理行动，生成回应
      3. Judge Agent：每 N 回合评估质量

      与 Phase B 的 LangGraph 不同：
        Phase B = 单回合内多 Agent 协作
        Phase C = 多回合间多 Agent 轮流运行（更宏观的编排）
    """
    # 如果启用 use_graph，更新 session 设置
    if config.use_graph:
        async with session_maker() as s:
            sess = await s.get(GameSession, config.session_id)
            if sess is not None:
                settings = json.loads(sess.settings_json or "{}")
                settings["use_graph"] = True
                sess.settings_json = json.dumps(settings)
                await s.commit()

    scores: list[EvalScore] = []

    for turn_num in range(1, config.max_turns + 1):
        # ── 1. 读取最近对话和角色信息 ──────────────────────
        async with session_maker() as s:
            sess = await s.get(GameSession, config.session_id)
            if sess is None:
                log.error("session %d not found", config.session_id)
                break
            char = await s.get(Character, sess.character_id)

            recent_msgs = (
                await s.execute(
                    select(MessageRow)
                    .where(MessageRow.session_id == config.session_id)
                    .order_by(MessageRow.id.desc())
                    .limit(10)
                )
            ).scalars().all()
            recent_msgs = list(reversed(recent_msgs))

        char_md = char.profile_md if char else ""
        char_name = char.name if char else "玩家"

        # ── 2. 玩家 Agent 生成行动 ──────────────────────────
        action = await generate_player_action(
            messages=recent_msgs,
            character_md=char_md,
            character_name=char_name,
            client=player_client,
        )
        log.info("eval turn %d: player action = %s", turn_num, action[:60])

        # ── 3. GM 处理回合 ──────────────────────────────────
        # 获取 ollama_url 用于 RAG（如果配置了的话）
        async with session_maker() as s:
            sess = await s.get(GameSession, config.session_id)
            cfg = await s.get(ModelConfig, sess.gm_model_config_id) if sess else None
            ollama_url = cfg.base_url if cfg else None

        async with session_maker() as s:
            async for _ in run_turn(
                s, config.session_id, action, gm_client,
                ollama_base_url=ollama_url,
            ):
                pass  # 评测时丢弃流式事件，只关心最终 DB 状态
            await s.commit()

        # ── 4. 每 judge_every 回合评审一次 ──────────────────
        if turn_num % config.judge_every == 0:
            async with session_maker() as s:
                judge_msgs = (
                    await s.execute(
                        select(MessageRow)
                        .where(MessageRow.session_id == config.session_id)
                        .order_by(MessageRow.id.desc())
                        .limit(config.judge_every * 2)
                    )
                ).scalars().all()
                judge_msgs = list(reversed(judge_msgs))

                sess = await s.get(GameSession, config.session_id)
                world = await s.get(World, sess.world_id) if sess else None
                world_summary = (world.content_md or "")[:300] if world else ""

            score = await judge_session(
                messages=judge_msgs,
                world_summary=world_summary,
                session_id=config.session_id,
                turn=turn_num,
                config_name=config.config_name,
                client=judge_client,
            )
            scores.append(score)
            log.info(
                "eval score at turn %d: overall=%.1f (plot=%.1f, viol=%d, rp=%.1f, dice=%.1f)",
                turn_num, score.overall, score.plot_speed, score.rule_violations,
                score.rp_immersion, score.dice_accuracy,
            )

            # 持久化评分到 feedbacks 表
            async with session_maker() as s:
                s.add(Feedback(
                    session_id=config.session_id,
                    turn=turn_num,
                    kind="eval_score",
                    content=json.dumps({
                        "config_name": score.config_name,
                        "plot_speed": score.plot_speed,
                        "rule_violations": score.rule_violations,
                        "rp_immersion": score.rp_immersion,
                        "dice_accuracy": score.dice_accuracy,
                        "overall": score.overall,
                        "reasoning": score.reasoning,
                    }, ensure_ascii=False),
                ))
                await s.commit()

    return scores
```

- [ ] **Step 4: Run runner test**

```bash
cd /Users/norman/development/dzmm/backend && python -m pytest tests/test_eval.py::test_run_eval_runs_correct_number_of_turns -v
```

Expected: passes.

- [ ] **Step 5: Run all eval tests**

```bash
cd /Users/norman/development/dzmm/backend && python -m pytest tests/test_eval.py -v
```

Expected: all 7 tests pass.

- [ ] **Step 6: Commit**

```bash
cd /Users/norman/development/dzmm && git add backend/src/dzmm/eval/runner.py backend/tests/test_eval.py && git commit -m "feat(eval): add EvalConfig + run_eval() orchestrator"
```

---

## Task 4: Create report.py and cli.py

**Files:**
- Create: `backend/src/dzmm/eval/report.py`
- Create: `backend/src/dzmm/eval/cli.py`
- Modify: `backend/tests/test_eval.py`

- [ ] **Step 1: Write failing test for report**

Append to `backend/tests/test_eval.py`:

```python
from dzmm.eval.report import generate_report


def test_generate_report_contains_both_config_names():
    scores_a = [
        EvalScore(1, 10, "single_gm", 7.0, 1, 8.0, 9.0, "good"),
        EvalScore(1, 20, "single_gm", 6.0, 2, 7.0, 8.0, "ok"),
    ]
    scores_b = [
        EvalScore(2, 10, "multi_agent_gm", 8.0, 0, 9.0, 9.0, "excellent"),
        EvalScore(2, 20, "multi_agent_gm", 8.5, 0, 8.5, 9.5, "great"),
    ]
    report = generate_report(scores_a, "single_gm", scores_b, "multi_agent_gm")
    assert "single_gm" in report
    assert "multi_agent_gm" in report
    assert "plot_speed" in report.lower() or "剧情" in report
    assert isinstance(report, str)
    assert len(report) > 100


def test_generate_report_handles_empty_scores():
    report = generate_report([], "config_a", [], "config_b")
    assert isinstance(report, str)
    assert "config_a" in report or "config_b" in report
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd /Users/norman/development/dzmm/backend && python -m pytest tests/test_eval.py::test_generate_report_contains_both_config_names -v 2>&1 | tail -5
```

Expected: `ImportError`.

- [ ] **Step 3: Create eval/report.py**

Create `backend/src/dzmm/eval/report.py`:

```python
# ============================================================
# Evaluation Report Generator
# ============================================================
# 把多局 EvalScore 汇总成可读的 Markdown 对比报告。
# ============================================================

from datetime import datetime, UTC
from dzmm.eval.judge_agent import EvalScore


def _avg(scores: list[EvalScore], attr: str) -> float:
    if not scores:
        return 0.0
    return sum(getattr(s, attr) for s in scores) / len(scores)


def generate_report(
    scores_a: list[EvalScore],
    config_a_name: str,
    scores_b: list[EvalScore],
    config_b_name: str,
) -> str:
    """生成两个配置的对比 Markdown 报告。"""
    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")

    def _table_row(name: str, scores: list[EvalScore]) -> str:
        if not scores:
            return f"| {name} | N/A | N/A | N/A | N/A | N/A |"
        return (
            f"| {name} "
            f"| {_avg(scores, 'plot_speed'):.1f} "
            f"| {_avg(scores, 'rule_violations'):.1f} "
            f"| {_avg(scores, 'rp_immersion'):.1f} "
            f"| {_avg(scores, 'dice_accuracy'):.1f} "
            f"| {_avg(scores, 'overall'):.1f} |"
        )

    # Per-checkpoint detail table
    def _detail_rows(scores: list[EvalScore]) -> str:
        if not scores:
            return "（无评分记录）\n"
        rows = ["| 回合 | 剧情推进 | 规则违反 | RP沉浸感 | 骰子准确 | 综合 | 评语 |",
                "|------|----------|----------|----------|----------|------|------|"]
        for s in scores:
            rows.append(
                f"| {s.turn} | {s.plot_speed:.1f} | {s.rule_violations} "
                f"| {s.rp_immersion:.1f} | {s.dice_accuracy:.1f} "
                f"| {s.overall:.1f} | {s.reasoning[:40]} |"
            )
        return "\n".join(rows) + "\n"

    winner = "平局"
    if scores_a and scores_b:
        avg_a = _avg(scores_a, "overall")
        avg_b = _avg(scores_b, "overall")
        if avg_a > avg_b + 0.5:
            winner = f"✅ **{config_a_name}** 胜出（+{avg_a - avg_b:.1f}）"
        elif avg_b > avg_a + 0.5:
            winner = f"✅ **{config_b_name}** 胜出（+{avg_b - avg_a:.1f}）"
        else:
            winner = f"🤝 平局（差距 {abs(avg_a - avg_b):.1f}，不显著）"

    return f"""# TRPG GM 质量评测报告

生成时间：{now}

## 总结

{winner}

## 均值对比

| 配置 | 剧情推进 | 规则违反(↓) | RP沉浸感 | 骰子准确 | **综合** |
|------|----------|------------|----------|----------|---------|
{_table_row(config_a_name, scores_a)}
{_table_row(config_b_name, scores_b)}

## {config_a_name} 详细评分

{_detail_rows(scores_a)}

## {config_b_name} 详细评分

{_detail_rows(scores_b)}

---
*评分由 Judge Agent（LLM-as-Judge）自动生成，仅供参考。*
"""
```

- [ ] **Step 4: Create eval/cli.py**

Create `backend/src/dzmm/eval/cli.py`:

```python
# ============================================================
# Evaluation CLI — 自动评测命令行入口
# ============================================================
# 用法：
#   python -m dzmm.eval.cli --session-id 1 --turns 20
#   python -m dzmm.eval.cli --session-id 1 --session-id-b 2 --turns 20 --compare
# ============================================================

import argparse
import asyncio
import json
import sys
from pathlib import Path

from dzmm.config import APP_DIR
from dzmm.db.base import async_session, get_engine, init_db
from dzmm.config import DEFAULT_DB_URL
from dzmm.db.models import ModelConfig, Session as GameSession
from dzmm.eval.report import generate_report
from dzmm.eval.runner import EvalConfig, run_eval
from dzmm.models.factory import build_client


async def _main(args: argparse.Namespace) -> None:
    engine = get_engine(DEFAULT_DB_URL)
    await init_db(engine)
    session_maker = async_session(engine)

    # Load clients from the session's model configs
    async with session_maker() as s:
        sess_a = await s.get(GameSession, args.session_id)
        if sess_a is None:
            print(f"Error: session {args.session_id} not found", file=sys.stderr)
            return
        gm_cfg = await s.get(ModelConfig, sess_a.gm_model_config_id)

    gm_client = build_client(gm_cfg)
    player_client = gm_client  # Re-use GM model for player (can be changed)
    judge_client = gm_client   # Re-use GM model for judge (can be changed)

    config_a = EvalConfig(
        session_id=args.session_id,
        config_name="single_gm",
        max_turns=args.turns,
        judge_every=args.judge_every,
        use_graph=False,
    )

    print(f"Running eval on session {args.session_id} for {args.turns} turns...")
    scores_a = await run_eval(config_a, session_maker, gm_client, player_client, judge_client)
    print(f"Session A done. {len(scores_a)} evaluation checkpoints.")

    scores_b = []
    config_b_name = "multi_agent_gm"

    if args.compare and args.session_id_b:
        config_b = EvalConfig(
            session_id=args.session_id_b,
            config_name=config_b_name,
            max_turns=args.turns,
            judge_every=args.judge_every,
            use_graph=True,
        )
        print(f"Running eval on session {args.session_id_b} (multi-agent GM)...")
        scores_b = await run_eval(config_b, session_maker, gm_client, player_client, judge_client)
        print(f"Session B done. {len(scores_b)} evaluation checkpoints.")

    report = generate_report(scores_a, "single_gm", scores_b, config_b_name)
    print(report)

    # Save report to file
    out_dir = APP_DIR / "eval"
    out_dir.mkdir(exist_ok=True)
    from datetime import datetime, UTC
    ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    report_path = out_dir / f"report_{ts}.md"
    report_path.write_text(report, encoding="utf-8")
    print(f"\nReport saved to: {report_path}")

    await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="TRPG GM Autonomous Evaluation")
    parser.add_argument("--session-id", type=int, required=True, help="Session ID to evaluate")
    parser.add_argument("--session-id-b", type=int, default=None,
                        help="Second session ID for comparison (multi-agent GM)")
    parser.add_argument("--turns", type=int, default=20, help="Number of turns to run")
    parser.add_argument("--judge-every", type=int, default=10,
                        help="Run judge every N turns (default: 10)")
    parser.add_argument("--compare", action="store_true",
                        help="Compare single GM vs multi-agent GM")
    args = parser.parse_args()
    asyncio.run(_main(args))


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run all eval tests**

```bash
cd /Users/norman/development/dzmm/backend && python -m pytest tests/test_eval.py -v
```

Expected: all 9 tests pass.

- [ ] **Step 6: Run full test suite**

```bash
cd /Users/norman/development/dzmm/backend && python -m pytest tests/ -x --ignore=tests/test_ollama.py --ignore=tests/test_openai_compat.py -q
```

- [ ] **Step 7: Commit**

```bash
cd /Users/norman/development/dzmm && git add backend/src/dzmm/eval/report.py backend/src/dzmm/eval/cli.py backend/tests/test_eval.py && git commit -m "feat(eval): add generate_report() + CLI entry point for Phase C evaluation"
```

---

## Task 5: Docs, CHANGELOG, version bump to 0.6.0

**Files:**
- Modify: `backend/pyproject.toml`
- Modify: `CHANGELOG.md`
- Modify: `docs/learning/roadmap.md`
- Create: `docs/learning/agent-eval.md`
- Modify: `docs/learning/README.md`

- [ ] **Step 1: Bump version**

In `backend/pyproject.toml`, change `version = "0.5.0"` to `version = "0.6.0"`.

- [ ] **Step 2: Add CHANGELOG entry**

Prepend to `CHANGELOG.md` (before v0.5.0):

```markdown
## [v0.6.0] - 2026-05-03

**Phase C — 自主 Agent 自动评测**

玩家 Agent 自动生成行动 + 评审 Agent（LLM-as-Judge）每 10 回合打分，输出对比报告。支持单体 GM vs 多 Agent GM 质量对比。

### 新增
- **`eval/player_agent.py`** — 玩家 Agent：读取对话历史 → LLM 决策 → 输出下一步行动
- **`eval/judge_agent.py`** — 评审 Agent：LLM-as-Judge 对 4 个维度打分（剧情推进/规则违反/RP沉浸感/骰子准确性）；三级 JSON 解析 + fallback 默认分
- **`eval/runner.py`** — 评测编排器：`EvalConfig` + `run_eval()`，N 回合自动对局，评分写入 `feedbacks` 表
- **`eval/report.py`** — Markdown 对比报告生成器，均值表格 + 逐检查点详细分
- **`eval/cli.py`** — CLI 入口：`python -m dzmm.eval.cli --session-id 1 --turns 20 [--compare --session-id-b 2]`
- **报告输出** — 自动保存到 `~/.dzmm/eval/report_{timestamp}.md`

### 使用
```bash
# 单局评测
python -m dzmm.eval.cli --session-id 1 --turns 20

# 对比评测（单体 GM vs 多 Agent GM）
python -m dzmm.eval.cli --session-id 1 --session-id-b 2 --turns 20 --compare
```

```

- [ ] **Step 3: Update roadmap.md**

In `docs/learning/roadmap.md`, add under `## 已完成`:

```markdown
- **v0.6.0** — Phase C：自主 Agent 自动评测（Player Agent + Judge Agent + LLM-as-Judge）
```

- [ ] **Step 4: Create docs/learning/agent-eval.md**

Create `docs/learning/agent-eval.md`:

```markdown
# Phase C：自主 Agent 自动评测

> 本文对应 `eval/` 目录，讲解 LLM-as-Judge 评测模式和自主 Agent 编排。

---

## 1. 为什么需要自动评测

Phase B 添加了多 Agent GM，但怎么知道它比单体 GM 好？需要量化评测：

- **规则匹配**（是否遵守铁律）：过于机械，无法评估叙事质量
- **人工评测**：准确但昂贵、慢，无法大规模运行
- **LLM-as-Judge**：用 LLM 评估另一个 LLM 的输出 → 自动化、可扩展、比规则灵活

---

## 2. 三个 Agent 的分工

```
[玩家 Agent]              [评审 Agent]
  对话历史 → LLM           每 10 回合旁观评分
  → 下一步行动               plot_speed / rule_violations
                             rp_immersion / dice_accuracy
         ↕
[GM（已有系统）]
  处理行动 → 叙事 + 事件
```

---

## 3. 玩家 Agent

[`eval/player_agent.py`](https://github.com/b31o8321/dzmm/blob/main/backend/src/dzmm/eval/player_agent.py)：

```python
async def generate_player_action(messages, character_md, character_name, client):
    pairs = [(msg.content, next_msg.content) for msg, next_msg in ...]
    prompt_msgs = build_player_messages(character_name, character_md, pairs)
    action, _ = await client.complete(prompt_msgs, GenerationParams(temperature=0.8))
    return action
```

**感知（Perceive）→ 思考（Think）→ 行动（Act）** — Agent 的基本循环。
`temperature=0.8` 保证每次行动都有随机性（不会陷入重复循环）。

---

## 4. LLM-as-Judge 评审 Agent

[`eval/judge_agent.py`](https://github.com/b31o8321/dzmm/blob/main/backend/src/dzmm/eval/judge_agent.py)：

```python
@dataclass
class EvalScore:
    plot_speed: float       # 剧情推进速度 0-10
    rule_violations: int    # 铁律违反次数（越少越好）
    rp_immersion: float     # RP 沉浸感 0-10
    dice_accuracy: float    # 骰子规则准确性 0-10

    @property
    def overall(self) -> float:
        return (plot_speed + max(0, 10 - violations*2) + rp_immersion + dice_accuracy) / 4
```

评审 LLM 被要求输出严格 JSON，用三级解析保证鲁棒性：
1. 直接 `json.loads(raw)`
2. 正则提取 `{...}` 块
3. 失败 → 返回默认分（5.0）

---

## 5. 评测编排器

[`eval/runner.py`](https://github.com/b31o8321/dzmm/blob/main/backend/src/dzmm/eval/runner.py)：

```python
for turn_num in range(1, config.max_turns + 1):
    # 1. 玩家 Agent 生成行动
    action = await generate_player_action(recent_msgs, char_md, char_name, player_client)
    # 2. GM 处理回合
    async for _ in run_turn(s, session_id, action, gm_client):
        pass  # 评测时丢弃流式事件
    await s.commit()
    # 3. 每 N 回合评审
    if turn_num % config.judge_every == 0:
        score = await judge_session(...)
        scores.append(score)
```

**关键：** `async for _ in run_turn(...)` 消耗整个 async generator 但丢弃事件。
这是让 `run_turn()` 在"静默模式"下运行的惯用写法。

---

## 6. Phase A/B/C 技术对比

| | Phase A (RAG) | Phase B (LangGraph) | Phase C (Agent Eval) |
|-|---------------|---------------------|----------------------|
| 解决的问题 | 世界书太长 | 单模型能力瓶颈 | 如何量化评测质量 |
| 核心模式 | 检索增强生成 | 有状态工作流 | LLM-as-Judge + 自主 Agent |
| Agent 数量 | 1（嵌入器） | 3（规则/叙事/NPC） | 3（玩家/GM/评审） |
| 时间维度 | 单回合内 | 单回合内 | 跨多回合（宏观编排） |
| 输出形式 | 更好的 Prompt | 更好的叙事 | 量化质量报告 |
```

- [ ] **Step 5: Update docs/learning/README.md**

Read `docs/learning/README.md`, then add a reference to `agent-eval.md` in the index.

- [ ] **Step 6: Run final full test suite**

```bash
cd /Users/norman/development/dzmm/backend && python -m pytest tests/ --ignore=tests/test_ollama.py --ignore=tests/test_openai_compat.py -q
```

- [ ] **Step 7: Commit all**

```bash
cd /Users/norman/development/dzmm && git add backend/pyproject.toml CHANGELOG.md docs/learning/roadmap.md docs/learning/agent-eval.md docs/learning/README.md && git commit -m "release: v0.6.0 — Phase C 自主 Agent 自动评测"
```

---

## Self-Review

**Spec coverage:**
- [x] 玩家 Agent：`generate_player_action()` ✓
- [x] 评审 Agent：`judge_session()` + `EvalScore` ✓
- [x] 每 10 回合打分 ✓ (configurable `judge_every`)
- [x] 4 维度评分 ✓ (plot_speed, rule_violations, rp_immersion, dice_accuracy)
- [x] 结果写入 feedbacks 表 ✓ (kind="eval_score")
- [x] 输出对比报告 ✓ (`generate_report()`)
- [x] 单 GM vs 多 Agent GM 对比 ✓ (via `use_graph=False/True`)
- [x] CLI 入口 ✓

**Placeholder scan:** No TBD, TODO, or incomplete steps found.

**Type consistency:**
- `EvalScore` defined Task 2, used in Task 3 (`run_eval` returns `list[EvalScore]`) and Task 4 (`generate_report` takes `list[EvalScore]`). ✓
- `_FakeClient` defined Task 1, reused in Tasks 2/3/4 test code. ✓
- `_fake_message()` helper defined Task 2, reused in Task 3 tests. ✓
- `build_player_messages(character_name, character_md, recent_history)` — defined Task 1, called Task 2 player_agent.py. ✓
- `build_judge_messages(world_summary, recent_history, n_turns)` — defined Task 1, called Task 2 judge_agent.py. ✓
