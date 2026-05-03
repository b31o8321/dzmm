# TRPG 剧情推进改善 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 解决三个相互关联的 TRPG 体验问题：场景锁死（一个场景绕来绕去出不来）、宏观剧情停滞（第一幕永远演不完）、规则不可见（玩家感受不到骰点的权重和风险）。

**Architecture:** 
(A) 在 Session 上追踪 `scene_turn_count`（当前场景已过回合数），注入 `_build_key_facts` 形成递进式"场景强推"压力；location_enter 时重置为 1。
(B) 收紧主线事件 `event_complete` 的提示文案，要求 GM 演出核心内容后立即 emit 进度标记，不等叙事结束。
(C) 扩展 `<dice>` 标签，增加 `success` / `fail` 属性说明结果分支；前端在骰点面板渲染成带颜色的结果提示。

**Tech Stack:** Python/SQLAlchemy (backend), Vue 3 + TypeScript (frontend), pytest (tests)

---

## 文件结构

| 文件 | 变更内容 |
|------|---------|
| `backend/src/dzmm/db/models.py` | Session 新增 `scene_turn_count` 字段 |
| `backend/src/dzmm/db/base.py` | 新增 `_V030_MIGRATIONS` + 在 `init_db` 中执行 |
| `backend/src/dzmm/service/game.py` | 新增 `_update_scene_turn_count`；`run_turn` 调用它；`_build_key_facts` 注入场景压力 + 收紧 event_complete 强推 |
| `backend/src/dzmm/prompts/gm_template.py` | 更新 `standard` 规则中 `<dice>` 标签格式，要求填写 `success` / `fail` |
| `frontend/src/composables/useGameState.ts` | Dice 类型增加 `success?` / `fail?` 字段 |
| `frontend/src/composables/useGameTurn.ts` | dice 标签处理：透传 `attrs.success` / `attrs.fail` |
| `frontend/src/components/StatePanel.vue` | 骰点列表渲染成功/失败分支文本 |
| `backend/tests/test_scene_turn_budget.py` | 新建：测试计数器增/减/重置和 key_facts 注入 |

---

## Task 1: Session DB — scene_turn_count 字段 + V030 迁移

**Files:**
- Modify: `backend/src/dzmm/db/models.py`
- Modify: `backend/src/dzmm/db/base.py`

- [ ] **Step 1: 在 Session 类中添加 `scene_turn_count` 字段**

在 `backend/src/dzmm/db/models.py` 的 Session 类中，找到 `doom_score` 字段后面，添加：

```python
    doom_score: Mapped[int] = mapped_column(Integer, default=0)  # v0.2.5
    scene_turn_count: Mapped[int] = mapped_column(Integer, default=0)  # v0.3.0: turns elapsed in current scene/location
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None))
```

- [ ] **Step 2: 添加 V030 迁移**

在 `backend/src/dzmm/db/base.py` 中，找到 `_V029_MIGRATIONS` 定义之后，添加：

```python
_V030_MIGRATIONS: dict[str, list[tuple[str, str]]] = {
    "sessions": [
        ("scene_turn_count", "scene_turn_count INTEGER NOT NULL DEFAULT 0"),
    ],
}
```

- [ ] **Step 3: 在 `init_db` 中执行迁移**

在 `init_db` 函数中，找到 `_V029_MIGRATIONS` 的循环之后，添加：

```python
        for table, cols in _V030_MIGRATIONS.items():
            await conn.run_sync(_add_missing_columns_sync, table, cols)
```

- [ ] **Step 4: 运行现有测试，确认迁移不破坏任何东西**

```bash
cd /Users/norman/development/dzmm
python -m pytest backend/tests/test_db_models.py backend/tests/test_state_apply.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/src/dzmm/db/models.py backend/src/dzmm/db/base.py
git commit -m "feat(db): v0.3.0 — add scene_turn_count to Session"
```

---

## Task 2: game.py — 场景计数器更新逻辑 + 测试

**Files:**
- Modify: `backend/src/dzmm/service/game.py`
- Create: `backend/tests/test_scene_turn_budget.py`

- [ ] **Step 1: 编写失败测试（三个测试用例）**

新建 `backend/tests/test_scene_turn_budget.py`：

```python
import json
import pytest
from sqlalchemy import select

from dzmm.db.base import init_db, get_engine, async_session
from dzmm.db.models import (
    Character, CharState, ModelConfig, Session as GameSession, World, Location,
)
from dzmm.models.client import GenerationParams, Message, ModelClient, StreamChunk, TokenUsage
from dzmm.parsing.events import NarrativeDelta, TagComplete
from dzmm.service.game import run_turn, SCENE_SOFT_PRESSURE_TURNS, _build_key_facts


class FakeClient(ModelClient):
    name = "fake"
    def __init__(self, output: str):
        self.output = output
    async def stream(self, messages, params):
        for ch in self.output:
            yield StreamChunk(delta=ch)
        yield StreamChunk(delta="", finish_reason="stop",
                          usage=TokenUsage(input_tokens=5, output_tokens=10))


@pytest.fixture
async def seeded(tmp_path):
    engine = get_engine(f"sqlite+aiosqlite:///{tmp_path}/t.db")
    await init_db(engine)
    SM = async_session(engine)
    async with SM() as s:
        world = World(name="W", content_md="x", style="dark",
                      rules_json='{"mode":"light"}')
        char = Character(world=world, name="Riku", profile_md="黑客",
                         base_stats_json='{"hp":20}')
        cfg = ModelConfig(name="m", type="ollama",
                          base_url="http://localhost:11434", model_name="q")
        s.add_all([world, char, cfg])
        await s.flush()
        sess = GameSession(name="run", world_id=world.id, character_id=char.id,
                           gm_model_config_id=cfg.id, summarizer_model_config_id=cfg.id)
        s.add(sess)
        await s.flush()
        s.add(CharState(session_id=sess.id, stats_json='{"hp":20}', inventory_json="[]"))
        await s.commit()
        yield SM, sess.id
    await engine.dispose()


async def test_scene_turn_count_increments_without_location_change(seeded):
    """scene_turn_count += 1 each turn when no location_enter tag is emitted."""
    SM, sid = seeded
    client = FakeClient("<narrative>test</narrative>")
    async with SM() as s:
        async for _ in run_turn(s, sid, "环顾", client):
            pass
        await s.commit()
    async with SM() as s:
        sess = await s.get(GameSession, sid)
        assert sess.scene_turn_count == 1

    # Second turn — should reach 2
    client2 = FakeClient("<narrative>test2</narrative>")
    async with SM() as s:
        async for _ in run_turn(s, sid, "等待", client2):
            pass
        await s.commit()
    async with SM() as s:
        sess = await s.get(GameSession, sid)
        assert sess.scene_turn_count == 2


async def test_scene_turn_count_resets_on_location_enter(seeded):
    """scene_turn_count resets to 1 when GM emits <location_enter>."""
    SM, sid = seeded
    # Preset to 5 to simulate a stuck scene
    async with SM() as s:
        sess = await s.get(GameSession, sid)
        sess.scene_turn_count = 5
        await s.commit()

    output = '<narrative>走进酒馆。</narrative><location_enter name="酒馆" description="热闹"/>'
    client = FakeClient(output)
    async with SM() as s:
        async for _ in run_turn(s, sid, "进入酒馆", client):
            pass
        await s.commit()

    async with SM() as s:
        sess = await s.get(GameSession, sid)
        assert sess.scene_turn_count == 1


async def test_scene_pressure_appears_in_key_facts_above_threshold(seeded):
    """_build_key_facts injects scene pressure when scene_turn_count >= SCENE_SOFT_PRESSURE_TURNS."""
    SM, sid = seeded
    async with SM() as s:
        sess = await s.get(GameSession, sid)
        sess.scene_turn_count = SCENE_SOFT_PRESSURE_TURNS
        s.add(Location(session_id=sid, name="酒馆", description="",
                       first_visited_turn=1, last_visited_turn=4, is_current=True))
        await s.commit()
    async with SM() as s:
        kf = await _build_key_facts(s, sid, current_turn=5)
    assert "场景时间提醒" in kf or "场景强推" in kf


async def test_scene_pressure_absent_below_threshold(seeded):
    """No scene pressure injected when scene_turn_count < SCENE_SOFT_PRESSURE_TURNS."""
    SM, sid = seeded
    async with SM() as s:
        sess = await s.get(GameSession, sid)
        sess.scene_turn_count = 2
        s.add(Location(session_id=sid, name="酒馆", description="",
                       first_visited_turn=1, last_visited_turn=2, is_current=True))
        await s.commit()
    async with SM() as s:
        kf = await _build_key_facts(s, sid, current_turn=3)
    assert "场景时间提醒" not in kf
    assert "场景强推" not in kf
```

- [ ] **Step 2: 运行测试，确认失败（SCENE_SOFT_PRESSURE_TURNS 未定义）**

```bash
cd /Users/norman/development/dzmm
python -m pytest backend/tests/test_scene_turn_budget.py -q
```

Expected: FAIL — `ImportError: cannot import name 'SCENE_SOFT_PRESSURE_TURNS' from 'dzmm.service.game'`

- [ ] **Step 3: 在 game.py 中添加常量 + `_update_scene_turn_count` 函数**

在 `backend/src/dzmm/service/game.py` 文件中，找到 `RECENT_WINDOW_*` 常量定义的附近，添加新常量和辅助函数：

```python
# Scene pacing constants — turns before scene-exit pressure kicks in.
# Soft pressure (⏰ reminder) starts at SCENE_SOFT_PRESSURE_TURNS.
# Hard pressure (🚨 forced exit) starts at SCENE_HARD_EXIT_TURNS.
SCENE_SOFT_PRESSURE_TURNS = 4
SCENE_HARD_EXIT_TURNS = 7


def _update_scene_turn_count(sess, completed_tags: list) -> None:
    """After apply_tags, update sess.scene_turn_count.
    Reset to 1 if a location_enter tag was emitted this turn (new scene),
    otherwise increment by 1."""
    location_entered = any(
        getattr(t, "name", None) == "location_enter" for t in completed_tags
    )
    if location_entered:
        sess.scene_turn_count = 1
    else:
        sess.scene_turn_count = (sess.scene_turn_count or 0) + 1
```

- [ ] **Step 4: 在 `run_turn` 中调用 `_update_scene_turn_count`**

在 `run_turn` 函数中，找到 `await apply_tags(...)` 调用之后（在 `sess.turn_count = next_turn` 之前），添加调用：

```python
    await apply_tags(
        session,
        session_id,
        next_turn,
        completed_tags,
    )

    _update_scene_turn_count(sess, completed_tags)   # <-- 新增这行

    sess.turn_count = next_turn
    sess.last_played = datetime.now(UTC).replace(tzinfo=None)
```

- [ ] **Step 5: 运行测试确认通过**

```bash
cd /Users/norman/development/dzmm
python -m pytest backend/tests/test_scene_turn_budget.py -q
```

Expected: 4 passed (前两个 run_turn 测试 + 后两个 key_facts 测试会在 Task 3 后全部通过；此时至少前两个通过，后两个仍 fail — 那是 Task 3 的事）

- [ ] **Step 6: Commit**

```bash
git add backend/src/dzmm/service/game.py backend/tests/test_scene_turn_budget.py
git commit -m "feat(game): scene_turn_count — increment/reset counter in run_turn"
```

---

## Task 3: game.py — _build_key_facts 场景压力注入

**Files:**
- Modify: `backend/src/dzmm/service/game.py`

- [ ] **Step 1: 在 `_build_key_facts` 中注入场景压力**

在 `_build_key_facts` 函数中，找到当前地点 (`current_loc`) 的块末尾（`parts.append("\n".join(loc_lines))` 之后），添加：

```python
    # v0.3.0 — Scene turn pressure. When the session has been at the same
    # location for many turns, inject an escalating directive to force scene
    # closure. Hard cap at SCENE_HARD_EXIT_TURNS prevents indefinite loops.
    if current_loc is not None and sess is not None:
        stc = sess.scene_turn_count or 0
        if stc >= SCENE_HARD_EXIT_TURNS:
            parts.append(
                f"\n## 🚨 场景强推（已在「{current_loc.name}」滞留 {stc} 回合）\n"
                "**本回合必须结束当前场景**，选择以下任一方式立即执行：\n"
                "(a) 用一个环境事件强制打断（有人闯入 / 危险爆发 / 时限耗尽），PC **必须** 离开；\n"
                "(b) 揭示足以让 PC 立刻行动的决定性信息，随后 emit "
                "`<location_enter name=\"新地点\" description=\"一句话\"/>` 推进；\n"
                "(c) NPC 明确宣告「此处已谈无可谈」，给出下一目的地。\n"
                "**禁止**：在此场景继续新增细节、旁支问题、模糊引导。\n"
                "强推要求立刻执行，不接受「下一回合」的推迟。"
            )
        elif stc >= SCENE_SOFT_PRESSURE_TURNS:
            parts.append(
                f"\n## ⏰ 场景时间提醒（已在「{current_loc.name}」{stc} 回合）\n"
                "本回合必须提供明确的场景推进路径之一：\n"
                "(a) 揭示让 PC 能够立刻行动的关键信息（名字/地点/方法）；\n"
                "(b) NPC 主动改变立场或给出具体让步；\n"
                "(c) 环境事件中断当前对话/探索节奏。\n"
                "禁止「碎片化喂养」——把本可一回合说清的内容再拆分。"
            )
```

- [ ] **Step 2: 运行全部 scene_turn_budget 测试**

```bash
cd /Users/norman/development/dzmm
python -m pytest backend/tests/test_scene_turn_budget.py -v
```

Expected: 4 passed.

- [ ] **Step 3: 跑完整 backend 测试套件确认无回归**

```bash
cd /Users/norman/development/dzmm
python -m pytest backend/tests/ -q
```

Expected: all existing tests pass (only new tests added).

- [ ] **Step 4: Commit**

```bash
git add backend/src/dzmm/service/game.py
git commit -m "feat(game): scene pressure injection in key_facts (v0.3.0)"
```

---

## Task 4: game.py — 收紧 event_complete 强推提示

**Files:**
- Modify: `backend/src/dzmm/service/game.py`

场景锁死的另一个原因是：GM 收到"演这个主线事件"的指令后，会把事件分拆成多回合叙事，只在最后一回合才 emit `event_complete`。这让 `turns_since_progress` 保持高位，强推机制一直循环触发。修复：明确告诉 GM「演出核心内容后立刻 emit，event_complete 不是结束信号」。

- [ ] **Step 1: 定位并更新 `_build_key_facts` 中的强推文案**

在 `_build_key_facts` 函数中，找到生成强推文本的 `parts.append(...)` 块（约包含「操作步骤」「1. 无论 PC 当前...」「2. 在 narrative...」「3. 演完后立即...」）。

将现有文本替换为：

```python
                        parts.append(
                            f"## {urgency}（已 {turns_since_progress} 回合无主线进展）\n"
                            f"**本回合必须完成主线事件**：「{_render_event(next_event)}」\n\n"
                            f"操作步骤（严格按顺序）：\n"
                            f"1. 立刻安排 NPC 或环境事件将 PC 引向该主线事件（1-2 句即可）\n"
                            f"2. 在 narrative 中演出该事件的核心一幕（≤150 字，抓住最戏剧性的瞬间）\n"
                            f"3. **核心一幕演完后，立刻输出以下 tag（在当前回合任意位置均可，无需等叙事结束）**：\n"
                            f"```\n{emit_tag}\n```\n"
                            f"4. emit 完成后可继续补充叙事细节或 choices，但 event_complete 不能推到下回合\n\n"
                            f"⚠️ 误区纠正：event_complete 是**进度标记**，不是叙事终止符。"
                            f"你不需要等「整个事件叙事结束」才 emit——演出核心即标记完成。\n"
                            f"**如本回合未 emit 该 tag，系统视为未完成，下回合继续强推。**"
                        )
```

- [ ] **Step 2: 运行 gm_template 测试 + 全套测试**

```bash
cd /Users/norman/development/dzmm
python -m pytest backend/tests/test_gm_template.py backend/tests/test_game_service.py -q
```

Expected: all pass.

- [ ] **Step 3: Commit**

```bash
git add backend/src/dzmm/service/game.py
git commit -m "fix(prompt): event_complete is a progress marker, not narrative end — emit immediately"
```

---

## Task 5: gm_template — dice 标签 success/fail 属性

**Files:**
- Modify: `backend/src/dzmm/prompts/gm_template.py`

- [ ] **Step 1: 更新 `standard` 规则模式中的 dice 说明**

在 `backend/src/dzmm/prompts/gm_template.py` 中，找到 `_RULES_DESCRIPTIONS["standard"]` 字符串，将其中的 `<dice>` 标签描述更新为：

```python
    "standard": (
        "标准：d20 技能检定。"
        "对任何不确定结果的行动（攻击、潜行、说服、感知、技术操作等），"
        "必须先输出 `<dice skill=\"技能名\" target=\"DC值\" "
        "success=\"成功后会发生什么（一句话）\" "
        "fail=\"失败后会发生什么（一句话）\">` 标签描述判定，"
        "然后在 <narrative> 中根据结果叙事。"
        "DC 参考：8=轻松，12=普通，15=困难，18=非常困难，20=极难。"
        "d20 大于等于 DC 算成功，d20=20 大成功，d20=1 大失败。"
        "success 和 fail 属性用玩家能理解的游戏语言写，"
        "例如：success=\"说服守卫放行\" fail=\"守卫警觉，叫来同伴\"。"
    ),
```

- [ ] **Step 2: 同样更新 `hardcore` 规则**

找到 `_RULES_DESCRIPTIONS["hardcore"]`，在「除标准 d20 检定外」前加一句说明 dice 标签格式要求，与 standard 一致（复制相同的格式说明）：

```python
    "hardcore": (
        "硬核：完整属性消耗、判定、状态追踪。"
        "dice 标签格式同标准模式，必须包含 success 和 fail 属性说明结果分支。"
        "除标准 d20 检定外，每个行动都要核算 stamina/sanity 消耗，"
        "战斗按回合制处理，受伤要标 hp 变化。"
    ),
```

- [ ] **Step 3: 同样更新系统 prompt 中的 `<dice>` 标签文档**

在 `_SYSTEM_TEMPLATE` 中搜索 `<dice` 的注释/文档块（通常在「输出格式」或标签说明区域），找到 dice 标签的格式描述，更新为：

```
<dice skill="技能名" target="DC值" success="成功结果一句话" fail="失败结果一句话">结果文本</dice>
```

例如，将原来的：
```
<dice skill="说服" target="12">成功，守卫放行</dice>
```
更新为：
```
<dice skill="说服" target="12" success="守卫放行" fail="守卫警觉叫人">成功，守卫放行</dice>
```

若 `_SYSTEM_TEMPLATE` 中没有 dice 示例，在「## 状态标签格式」或类似区域添加 dice 的完整格式说明即可。

- [ ] **Step 4: 运行 gm_template 测试**

```bash
cd /Users/norman/development/dzmm
python -m pytest backend/tests/test_gm_template.py -q
```

Expected: all pass (gm_template 测试主要检查 prompt 能生成、不崩溃，无需验证具体内容).

- [ ] **Step 5: Commit**

```bash
git add backend/src/dzmm/prompts/gm_template.py
git commit -m "feat(prompt): dice tag adds success/fail attributes for outcome visibility"
```

---

## Task 6: Frontend — 骰点面板渲染 success/fail 分支

**Files:**
- Modify: `frontend/src/composables/useGameState.ts`
- Modify: `frontend/src/composables/useGameTurn.ts`
- Modify: `frontend/src/components/StatePanel.vue`

- [ ] **Step 1: 扩展 `useGameState.ts` 中的 dice 类型**

在 `frontend/src/composables/useGameState.ts` 中，找到：

```typescript
  const dice = ref<{ skill: string; target: string; result: string }[]>([])
```

替换为：

```typescript
  const dice = ref<{ skill: string; target: string; result: string; success?: string; fail?: string }[]>([])
```

同时找到 `pushDice` 函数（如果存在），确认其 parameter 类型也更新：

```typescript
  function pushDice(d: { skill: string; target: string; result: string; success?: string; fail?: string }) {
    dice.value.unshift(d)
    if (dice.value.length > MAX_DICE) dice.value.length = MAX_DICE
  }
```

- [ ] **Step 2: 在 `useGameTurn.ts` dice 处理中透传 success/fail**

在 `frontend/src/composables/useGameTurn.ts` 中，找到 dice 标签处理块：

```typescript
          else if (name === 'dice') {
            audio.playSfx('dice')
            gs.pushDice({
              skill: attrs.skill ?? '判定',
              target: attrs.target ?? '?',
              result: content.trim() || '?',
            })
          }
```

替换为：

```typescript
          else if (name === 'dice') {
            audio.playSfx('dice')
            gs.pushDice({
              skill: attrs.skill ?? '判定',
              target: attrs.target ?? '?',
              result: content.trim() || '?',
              success: attrs.success || undefined,
              fail: attrs.fail || undefined,
            })
          }
```

- [ ] **Step 3: 更新 `StatePanel.vue` dice prop 类型 + 渲染模板**

在 `frontend/src/components/StatePanel.vue` 中，找到 props 定义，将 dice 类型更新：

```typescript
  dice: { skill: string; target: string; result: string; success?: string; fail?: string }[]
```

然后找到 dice 列表渲染部分：

```html
        <li v-for="(d, i) in dice" :key="i" class="text-slate-600">
          🎲 {{ d.skill }} (DC {{ d.target }}) → {{ d.result }}
        </li>
```

替换为：

```html
        <li v-for="(d, i) in dice" :key="i" class="text-slate-600">
          <div>🎲 {{ d.skill }} (DC {{ d.target }}) → <span class="font-medium">{{ d.result }}</span></div>
          <div v-if="d.success || d.fail" class="ml-5 mt-0.5 space-y-0.5">
            <div v-if="d.success" class="text-xs text-emerald-600">✓ {{ d.success }}</div>
            <div v-if="d.fail" class="text-xs text-rose-500">✗ {{ d.fail }}</div>
          </div>
        </li>
```

- [ ] **Step 4: 运行 TypeScript 类型检查**

```bash
cd /Users/norman/development/dzmm/frontend
npx vue-tsc --noEmit 2>&1 | grep -i "error\|StatePanel\|useGameState\|useGameTurn"
```

Expected: no errors.

- [ ] **Step 5: 运行 frontend build 确认无构建错误**

```bash
cd /Users/norman/development/dzmm/frontend
npm run build 2>&1 | tail -5
```

Expected: `✓ built in X.XXs`

- [ ] **Step 6: Commit**

```bash
git add frontend/src/composables/useGameState.ts frontend/src/composables/useGameTurn.ts frontend/src/components/StatePanel.vue
git commit -m "feat(ui): dice panel shows success/fail outcome branches"
```

---

## Task 7: 版本 bump + 全套测试 + tag

**Files:**
- Modify: `backend/src/dzmm/__init__.py`
- Modify: `backend/pyproject.toml`
- Modify: `frontend/package.json`
- Modify: `frontend/src-tauri/tauri.conf.json`

- [ ] **Step 1: 更新版本号为 0.3.0**

`backend/src/dzmm/__init__.py`：
```python
__version__ = "0.3.0"
```

`backend/pyproject.toml`：
```toml
version = "0.3.0"
```

`frontend/package.json`：
```json
"version": "0.3.0",
```

`frontend/src-tauri/tauri.conf.json`（找到 `"version"` 字段）：
```json
"version": "0.3.0"
```

- [ ] **Step 2: 运行全套 backend 测试**

```bash
cd /Users/norman/development/dzmm
python -m pytest backend/tests/ -q
```

Expected: all pass, including the 4 new scene_turn_budget tests.

- [ ] **Step 3: Frontend 构建**

```bash
cd /Users/norman/development/dzmm/frontend
npm run build 2>&1 | tail -5
```

Expected: `✓ built in X.XXs`

- [ ] **Step 4: Commit + tag**

```bash
git add backend/src/dzmm/__init__.py backend/pyproject.toml frontend/package.json frontend/src-tauri/tauri.conf.json
git commit -m "release: v0.3.0 — scene turn budget, event_complete prompt fix, dice outcome branches"
git tag v0.3.0
```

---

## 自检

**Spec coverage:**

| 问题 | 解决方案 | Task |
|------|---------|------|
| 场景锁死（绕来绕去出不来） | scene_turn_count + 软/硬压力注入 | 1-3 |
| 宏观剧情停滞（第一幕演不完） | event_complete 强推文案收紧，区分进度标记 vs 叙事终止 | 4 |
| 规则不可见（骰点无风险感） | dice 标签 success/fail 属性 + 前端渲染 | 5-6 |

**无占位符扫描：** 所有代码块均为完整实现，无 TBD/TODO。

**类型一致性：** Task 6 中 `dice` 类型在 `useGameState.ts`、`useGameTurn.ts`、`StatePanel.vue` 三处使用相同的 `{ skill; target; result; success?; fail? }` 结构，均包含可选的 success/fail 字段。
