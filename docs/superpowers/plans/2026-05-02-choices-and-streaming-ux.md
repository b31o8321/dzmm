# Choices Enhancement & Streaming UX Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** (1) Make GM choices drive plot branches / failure stakes. (2) Eliminate white screen during LLM thinking with a "PC 行动中" card showing recent clues. (3) Fix dialogue rendering before narrative finishes streaming. (4) Throttle plot_event spam — only importance≥2 enters the threads list, max 1 per turn. (5) Collapse the top nav overflow into a "···" dropdown.

**Architecture:** Six independent tasks — (1) prompt: strengthen `<choices>` rules; (2) prompt: risk-differentiate `suggest_actions`; (3) streaming: buffer `<say>`/`<pc_action>` until onDone; (4) UX: "PC 行动中" loading card in `MessageList.vue`; (5) prompt+frontend: throttle `<plot_event>` emission + filter importance=1 client-side + collapse threads list after 5; (6) header nav: collapse secondary links into an `el-dropdown`.

**Tech Stack:** Python (FastAPI backend), Vue 3 + TypeScript (frontend), Element Plus

---

## File Map

| File | Change |
|------|--------|
| `backend/src/dzmm/prompts/gm_template.py` | Choices format + iron law 5 + plot_event throttle rule |
| `backend/src/dzmm/api/routes_sessions/suggest.py` | Risk-differentiated suggestion prompt |
| `backend/tests/test_gm_template.py` | Tests for new choices + plot_event rules |
| `frontend/src/composables/useGameTurn.ts` | Buffer say/pc_action; filter importance=1 plot_events |
| `frontend/src/components/game/MessageList.vue` | Loading card with recent plot_events |
| `frontend/src/components/StatePanel.vue` | Collapse threads list after 5 items |
| `frontend/src/views/GameView.vue` | Pass `sending` to MessageList; collapse top nav into "···" dropdown |

---

### Task 1: Strengthen `<choices>` format in gm_template.py

**Files:**
- Modify: `backend/src/dzmm/prompts/gm_template.py` (choices section ~line 230 and iron law 5 ~line 88)
- Test: `backend/tests/test_gm_template.py`

Context: `gm_template.py` has a `_TEMPLATE` string with a `<choices>` format section (around line 230), iron law #5 (around line 89) that prohibits repeating choices, and "附加规则 - NPC主动性" (~line 106). This task makes choices consequence-driven AND forces NPC proactive turns to advance plot (not just set atmosphere).

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_gm_template.py` (at the end of the file):

```python
def test_choices_require_risk_differentiation():
    """Each choices block must now instruct GM to cover different risk axes
    and include at least one option with explicit consequence hint."""
    from dzmm.prompts.gm_template import build_gm_messages
    msgs = build_gm_messages(
        world_md="x", character_md="y", live_state={},
        rules_mode="light", style="dark",
        story_summary="", key_facts="",
        recent_messages=[], current_action="x",
    )
    sys = msgs[0].content
    assert "风险" in sys or "代价" in sys or "后果" in sys
    assert "高风险" in sys or "低风险" in sys or "风险档" in sys
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/norman/development/dzmm/.claude/worktrees/v0.2.5-gameplay-quality/backend
python -m pytest tests/test_gm_template.py::test_choices_require_risk_differentiation -v
```

Expected: FAIL (the words aren't in the template yet)

- [ ] **Step 3: Update `<choices>` format doc in `gm_template.py`**

Find the `<choices>` section around line 230. Replace:

```
<choices>
可选。给玩家 3 个启发性方向（不限制其自由输入）：
- 选项一
- 选项二
- 选项三
</choices>
```

With:

```
<choices>
给玩家 3 个方向（不限制其自由输入）。三选一必须覆盖不同风险档：
① 至少一个直接推进当前 main_event 进度（高风险/高回报方向）
② 至少一个外交/社交路线（不同侧面切入）
③ 至少一个稳妥选项（低风险但可能放弃线索/时间）
每个选项后用括号标注潜在后果方向，例如：
- 强行撬开保险箱（可能触发警报）
- 说服 Mara 告知密码（需要情商，失败会让她起疑）
- 先撤退，等待时机（保留安全，但损失一条线索）
</choices>
```

- [ ] **Step 4: Strengthen NPC 主动性 rule in `gm_template.py`**

Find the "附加规则" section containing `NPC 主动性` (~line 106):

```
- **NPC 主动性**：每 2-3 回合至少一个 NPC（优先 pinned 或 emotion≥50 的）主动做一件事，不等 PC 触发。
```

Replace with:

```python
"- **NPC 主动性**：每 2-3 回合至少一个 NPC（优先 pinned 或 emotion≥50 的）主动做一件事，不等 PC 触发。\n"
"  NPC 主动行为必须产生一个 PC 可响应的外部变化（新信息/威胁/机会/求助），\n"
"  禁止只渲染情绪或氛围（「她叹了口气」不算主动行为）。\n"
"  emit 对应 `<plot_event>` 或 `<npc_update>` 标记该变化。\n"
```

- [ ] **Step 5: Update iron law 5 in `gm_template.py`**

Find iron law 5 (around line 88-90). After the existing sentence "choices 与上回合重复 ≥80% = 失败，必须重新设计。" add:

```
   三个选项必须覆盖至少两种风险档（高风险/高回报 vs 低风险/低回报），
   禁止三个都是「安全探索」或「继续等待」之类的低代价同质选项。
```

The full rule 5 should now read:

```python
"5. **世界每回合必须前进**：每回合必须发生外部世界变化（地点/新信息/新 NPC/时间/\n"
"   物品/plot_event 之一）。choices 与上回合重复 ≥80% = 失败，必须重新设计。\n"
"   三个选项必须覆盖至少两种风险档（高风险/高回报 vs 低风险/低回报），\n"
"   禁止三个都是「安全探索」或「继续等待」之类的低代价同质选项。\n"
"   禁止「PC 思考 → NPC 模糊回应 → 同样三选一」超过 2 回合。\n"
```

- [ ] **Step 6: Run tests**

```bash
cd /Users/norman/development/dzmm/.claude/worktrees/v0.2.5-gameplay-quality/backend
python -m pytest tests/test_gm_template.py -v
```

Expected: all pass (including the new test)

- [ ] **Step 7: Commit**

```bash
git add backend/src/dzmm/prompts/gm_template.py backend/tests/test_gm_template.py
git commit -m "feat(prompt): choices risk tiers + NPC proactive turns must advance plot"
```

---

### Task 2: Risk-differentiated suggest_actions endpoint

**Files:**
- Modify: `backend/src/dzmm/api/routes_sessions/suggest.py`

Context: `suggest_actions` generates the 3 footer suggestion buttons. Current prompt produces generic 12-char hints with no consequence direction. We need suggestions to be risk-differentiated and include brief consequence hints.

No backend test needed for this (it calls an LLM; we trust the prompt change).

- [ ] **Step 1: Replace the system prompt in `suggest.py`**

Open `backend/src/dzmm/api/routes_sessions/suggest.py`. Replace the `messages` list (lines 35-48):

```python
    messages = [
        {
            "role": "system",
            "content": (
                "你是 TRPG 助手，根据当前场景和玩家目标，给出 3 个行动建议。\n"
                "规则：\n"
                "- 每条不超过 16 个汉字（含括号内的后果提示）\n"
                "- 三个建议必须覆盖不同风险档：至少一个高风险高回报、至少一个低风险稳进\n"
                "- 至少一个直接推进当前目标或主线剧情\n"
                "- 可选：在行动后用括号标注关键后果，例如「强攻（可能暴露）」\n"
                "- 只输出 3 行，每行一个，不加序号不加解释"
            ),
        },
        {
            "role": "user",
            "content": f"当前场景：{narrative_snippet}\n当前目标：{goals_text}",
        },
    ]
```

Also increase `max_tokens` from 80 to 120 (括号后果提示需要更多 token):

```python
        async for ch in client.stream(
            messages, GenerationParams(max_tokens=120, temperature=0.8)
        ):
```

- [ ] **Step 2: Run existing tests (no new test)**

```bash
cd /Users/norman/development/dzmm/.claude/worktrees/v0.2.5-gameplay-quality/backend
python -m pytest tests/ -v -k "not ollama"
```

Expected: all pass

- [ ] **Step 3: Commit**

```bash
git add backend/src/dzmm/api/routes_sessions/suggest.py
git commit -m "feat(suggest): risk-differentiated action suggestions with consequence hints"
```

---

### Task 3: Buffer say/pc_action tags — fix dialogue appearing before narrative

**Files:**
- Modify: `frontend/src/composables/useGameTurn.ts`

Context: During streaming, `onTag` for `<say>`/`<pc_action>` immediately appends to `turn.rawContent`. `MessageList.displayParts()` then renders the dialogue bubble while the narrative is still streaming, causing NPC lines to appear before the scene text finishes. Fix: buffer those tags inside `sendAction` scope; flush them to `rawContent` inside `onDone`.

- [ ] **Step 1: Add `sayBuffer` inside `sendAction` in `useGameTurn.ts`**

In `sendAction`, right after the `turn` reactive object is created (after line `currentTurn.value = turn`), add:

```typescript
const sayBuffer: string[] = []
```

- [ ] **Step 2: Change `onTag` say/pc_action handlers to push to buffer instead of rawContent**

Find (inside the `onTag` callback):

```typescript
          if (name === 'say') {
            const speakerAttr = attrs.speaker ? ` speaker="${attrs.speaker}"` : ''
            turn.rawContent =
              (turn.rawContent ?? '') + `<say${speakerAttr}>${content}</say>`
          } else if (name === 'pc_action') {
            turn.rawContent = (turn.rawContent ?? '') + `<pc_action>${content}</pc_action>`
          }
```

Replace with:

```typescript
          if (name === 'say') {
            const speakerAttr = attrs.speaker ? ` speaker="${attrs.speaker}"` : ''
            sayBuffer.push(`<say${speakerAttr}>${content}</say>`)
          } else if (name === 'pc_action') {
            sayBuffer.push(`<pc_action>${content}</pc_action>`)
          }
```

- [ ] **Step 3: Flush buffer in `onDone` before building rawContent**

Find the `onDone` callback:

```typescript
        onDone: () => {
          turnCount.value += 1
          // GM may have forgotten </narrative> and embedded choices into the
          // streamed narrative buffer; recover them here.
          if (!turn.choices.length) {
            const leaked = extractChoices(turn.narrative)
            if (leaked.length) turn.choices = leaked
          }
          turn.narrative = cleanNarrative(turn.narrative)
          // Synthesize a rawContent that parseParts can chew on. We always
          // prepend the cleaned narrative (wrapped) so backwards-compat is
          // preserved when GM didn't emit any speaker tags at all.
          if (turn.narrative) {
            turn.rawContent =
              `<narrative>${turn.narrative}</narrative>` + (turn.rawContent ?? '')
          }
```

Replace the rawContent synthesis section with:

```typescript
        onDone: () => {
          turnCount.value += 1
          if (!turn.choices.length) {
            const leaked = extractChoices(turn.narrative)
            if (leaked.length) turn.choices = leaked
          }
          turn.narrative = cleanNarrative(turn.narrative)
          // Flush buffered say/pc_action tags (collected during streaming so
          // dialogue bubbles don't appear before narrative finishes).
          if (sayBuffer.length) {
            turn.rawContent = (turn.rawContent ?? '') + sayBuffer.join('')
          }
          if (turn.narrative) {
            turn.rawContent =
              `<narrative>${turn.narrative}</narrative>` + (turn.rawContent ?? '')
          }
```

- [ ] **Step 4: Verify TypeScript compiles**

```bash
cd /Users/norman/development/dzmm/.claude/worktrees/v0.2.5-gameplay-quality/frontend
npm run type-check
```

Expected: no errors

- [ ] **Step 5: Commit**

```bash
git add frontend/src/composables/useGameTurn.ts
git commit -m "fix(streaming): buffer say/pc_action tags; render after narrative finishes"
```

---

### Task 4: Loading state — "PC 行动中" card with recent clues

**Files:**
- Modify: `frontend/src/components/game/MessageList.vue`
- Modify: `frontend/src/views/GameView.vue`

Context: When the user submits an action, there's a blank white gap until the first narrative token arrives (LLM thinking time). The request: fill this with recent plot_event clues from prior turns and a "PC行动中" animation, so it feels like the character is in motion.

Design:
- `MessageList` receives a new `sending` prop (boolean)
- When the last turn has an empty narrative AND `sending` is true, replace the empty content box with a loading card
- Loading card shows: "⚔️ 行动中…" pulse text + up to 3 recent `plot_event` items from the prior turns (the `turn.events` array already stores them with `type === 'plot_event'`)
- Once `turn.narrative` gets its first character, the card disappears and normal streaming rendering takes over

- [ ] **Step 1: Update `MessageList.vue` props and add loading state**

Open `frontend/src/components/game/MessageList.vue`. Make the following changes:

**1a. Add `sending` to props:**

```typescript
const props = defineProps<{
  turns: Turn[]
  characterName?: string
  sending?: boolean
}>()
```

**1b. Add `recentPlotEvents` computed (derives from last 5 turns, excludes current empty turn):**

After the `displayParts` function, add:

```typescript
const recentPlotEvents = computed(() => {
  const events: string[] = []
  const slice = props.turns.slice(0, -1).slice(-5)  // last 5 prior turns
  for (const t of slice) {
    for (const e of t.events ?? []) {
      if (e.type === 'plot_event' && e.content) {
        events.push(e.content)
      }
    }
  }
  return events.slice(-3)  // most recent 3 plot events
})
```

**1c. Add `isLastTurnLoading` computed:**

```typescript
const isLastTurnLoading = computed(() => {
  if (!props.sending) return false
  const last = props.turns[props.turns.length - 1]
  return !!last && !last.narrative
})
```

- [ ] **Step 2: Update the template in `MessageList.vue`**

Find the `<article>` rendering block:

```html
      <div class="relative bg-white rounded shadow-sm p-4">
        <template v-if="displayParts(t).length">
          <SpeakerBubble
            v-for="(part, pi) in displayParts(t)"
            :key="pi"
            :part="part"
            :pc-name="characterName"
          />
        </template>
        <MarkdownView v-else :source="t.narrative" />
```

Replace with:

```html
      <div class="relative bg-white rounded shadow-sm p-4">
        <!-- Loading state: waiting for first LLM token -->
        <template v-if="i === turns.length - 1 && isLastTurnLoading">
          <div class="space-y-3">
            <div class="flex items-center gap-2 text-slate-500 text-sm animate-pulse">
              <span>⚔️ 行动中…</span>
            </div>
            <div v-if="recentPlotEvents.length" class="border-t pt-2 space-y-1">
              <div class="text-xs text-slate-400 mb-1">— 近期事件 —</div>
              <div
                v-for="(ev, ei) in recentPlotEvents"
                :key="ei"
                class="text-xs text-slate-500 leading-relaxed"
              >{{ ev }}</div>
            </div>
          </div>
        </template>
        <template v-else-if="displayParts(t).length">
          <SpeakerBubble
            v-for="(part, pi) in displayParts(t)"
            :key="pi"
            :part="part"
            :pc-name="characterName"
          />
        </template>
        <MarkdownView v-else :source="t.narrative" />
```

- [ ] **Step 3: Pass `sending` prop in `GameView.vue`**

Find in `GameView.vue`:

```html
      <MessageList
        :turns="turns"
        :character-name="character?.name"
        @choose="(c: string) => sendActionDirect(c)"
        @open-events="(t: Turn) => openEvents(t)"
      />
```

Replace with:

```html
      <MessageList
        :turns="turns"
        :character-name="character?.name"
        :sending="sending"
        @choose="(c: string) => sendActionDirect(c)"
        @open-events="(t: Turn) => openEvents(t)"
      />
```

- [ ] **Step 4: Verify TypeScript compiles**

```bash
cd /Users/norman/development/dzmm/.claude/worktrees/v0.2.5-gameplay-quality/frontend
npm run type-check
```

Expected: no errors

- [ ] **Step 5: Verify visually**

Start the frontend dev server and open a session. Submit an action. You should see:
- Immediately after submit: the action header appears with "⚔️ 行动中…" pulsing and up to 3 recent plot events below
- Once the first narrative token arrives, the loading state disappears and streaming text appears normally

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/game/MessageList.vue frontend/src/views/GameView.vue
git commit -m "feat(ux): show PC行动中 loading card with recent plot events during LLM thinking"
```

---

### Task 5: Throttle plot_event spam — importance≥2 only, max 1 per turn

**Files:**
- Modify: `backend/src/dzmm/prompts/gm_template.py` (`<plot_event>` format section ~line 237)
- Modify: `frontend/src/composables/useGameTurn.ts` (plot_event handler ~line 161)
- Modify: `frontend/src/components/StatePanel.vue` (threads list ~line 96)
- Test: `backend/tests/test_gm_template.py`

Context: `<plot_event>` fires too often — even importance=1 trivia makes it into the threads sidebar. `threads` in `useGameState.ts` is never trimmed. Fix on two fronts: (a) prompt constraint so GM only emits importance≥2 events, max 1 per turn; (b) frontend silently drops importance=1 that slip through; (c) sidebar collapses list after 5 items.

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_gm_template.py`:

```python
def test_plot_event_throttle_rules_present():
    """Template must instruct GM: importance=1 → don't emit; max 1 plot_event per turn."""
    from dzmm.prompts.gm_template import build_gm_messages
    msgs = build_gm_messages(
        world_md="x", character_md="y", live_state={},
        rules_mode="light", style="dark",
        story_summary="", key_facts="",
        recent_messages=[], current_action="x",
    )
    sys = msgs[0].content
    assert "importance=1" in sys or "importance=\"1\"" in sys
    assert "每回合最多" in sys or "单回合最多" in sys or "max 1" in sys.lower()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/norman/development/dzmm/.claude/worktrees/v0.2.5-gameplay-quality/backend
python -m pytest tests/test_gm_template.py::test_plot_event_throttle_rules_present -v
```

Expected: FAIL

- [ ] **Step 3: Update `<plot_event>` format doc in `gm_template.py`**

Find the `<plot_event>` section around line 237:

```
<plot_event type="new_quest|hook_introduced|hook_resolved|major_event|location_entered"
            importance="1|2|3"
            thread_id="可选，回收伏笔时填">
描述这个事件。一句话。
</plot_event>
```

Replace with:

```
<plot_event type="new_quest|hook_introduced|hook_resolved|major_event|location_entered"
            importance="2|3"
            thread_id="可选，回收伏笔时填">
描述这个事件。一句话。
</plot_event>
重要：importance=1（日常细节）不emit此标签，直接写进 narrative 即可。
每回合最多 emit 1 个 plot_event（只取最重要的那件事）。
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd /Users/norman/development/dzmm/.claude/worktrees/v0.2.5-gameplay-quality/backend
python -m pytest tests/test_gm_template.py -v
```

Expected: all pass

- [ ] **Step 5: Filter importance=1 in `useGameTurn.ts`**

Find the `plot_event` handler in the `onTag` callback (~line 161):

```typescript
          else if (name === 'plot_event') {
            let importance = 2
            const parsed = parseInt(attrs.importance ?? '2', 10)
            if (!isNaN(parsed)) importance = Math.max(1, Math.min(3, parsed))
            gs.threads.value.push({
              type: attrs.type ?? 'major_event',
              description: content.trim(),
              importance,
            })
          }
```

Replace with:

```typescript
          else if (name === 'plot_event') {
            let importance = 2
            const parsed = parseInt(attrs.importance ?? '2', 10)
            if (!isNaN(parsed)) importance = Math.max(1, Math.min(3, parsed))
            // Drop importance=1 trivia — they belong in narrative, not the sidebar.
            if (importance >= 2) {
              gs.threads.value.push({
                type: attrs.type ?? 'major_event',
                description: content.trim(),
                importance,
              })
            }
          }
```

- [ ] **Step 6: Add collapse logic to `StatePanel.vue`**

Open `frontend/src/components/StatePanel.vue`. Add after the existing `<script setup lang="ts">` imports (wherever other refs are defined):

```typescript
import { ref } from 'vue'
const threadsExpanded = ref(false)
```

Find the threads section:

```html
    <section v-if="threads.length">
      <h3 class="font-bold text-slate-700 mb-2">剧情线</h3>
      <ul class="space-y-1 text-sm">
        <li v-for="(t, i) in threads" :key="i">
          <span class="text-amber-600 mr-1">{{ '★'.repeat(t.importance) }}</span>
          <span class="text-xs text-slate-500 mr-1">[{{ t.type }}]</span>
          {{ t.description }}
        </li>
      </ul>
    </section>
```

Replace with:

```html
    <section v-if="threads.length">
      <h3 class="font-bold text-slate-700 mb-2">剧情线</h3>
      <ul class="space-y-1 text-sm">
        <li v-for="(t, i) in (threadsExpanded ? threads : threads.slice(0, 5))" :key="i">
          <span class="text-amber-600 mr-1">{{ '★'.repeat(t.importance) }}</span>
          <span class="text-xs text-slate-500 mr-1">[{{ t.type }}]</span>
          {{ t.description }}
        </li>
      </ul>
      <button
        v-if="threads.length > 5"
        type="button"
        class="mt-1 text-xs text-blue-500 hover:text-blue-700"
        @click="threadsExpanded = !threadsExpanded"
      >
        {{ threadsExpanded ? '收起' : `查看全部（${threads.length} 条）` }}
      </button>
    </section>
```

- [ ] **Step 7: Verify TypeScript compiles**

```bash
cd /Users/norman/development/dzmm/.claude/worktrees/v0.2.5-gameplay-quality/frontend
npm run type-check
```

Expected: no errors

- [ ] **Step 8: Commit**

```bash
git add backend/src/dzmm/prompts/gm_template.py backend/tests/test_gm_template.py \
        frontend/src/composables/useGameTurn.ts frontend/src/components/StatePanel.vue
git commit -m "feat(plot): throttle plot_event to importance>=2, max 1/turn; collapse sidebar after 5"
```

---

### Task 6: Collapse top nav overflow into "···" dropdown

**Files:**
- Modify: `frontend/src/views/GameView.vue` (header nav section ~line 456)

Context: The header right side has ~10 links/buttons all flat — `角色卡 / 剧本 / 任务日志 / NPC / 关系 / 编年史 / 反馈 / 模型 / 设置 / 返回存档`. On smaller screens they wrap and eat into the chat area. Keep `返回存档` and `角色卡` always visible; move everything else into an `el-dropdown` "···" menu.

No backend changes. No new tests needed (pure layout change).

- [ ] **Step 1: Replace the header nav in `GameView.vue`**

Find the header right section (from ~line 456 to ~line 503):

```html
        <div class="flex items-center gap-4">
          <button
            type="button"
            class="text-sm text-slate-500 hover:text-slate-800"
            @click="characterCardOpen = true"
          >📜 角色卡</button>
          <router-link :to="`/play/${sessionId}/screenplay`"
                       class="text-sm text-slate-500 hover:text-slate-800">
            📜 剧本
          </router-link>
          <router-link :to="`/play/${sessionId}/journal`"
                       class="text-sm text-slate-500 hover:text-slate-800">
            📖 任务日志
          </router-link>
          <router-link :to="`/play/${sessionId}/npcs`"
                       class="text-sm text-slate-500 hover:text-slate-800">
            📒 NPC
          </router-link>
          <router-link :to="`/play/${sessionId}/relations`"
                       class="text-sm text-slate-500 hover:text-slate-800">
            🔗 关系
          </router-link>
          <router-link :to="`/play/${sessionId}/chronicle`"
                       class="text-sm text-slate-500 hover:text-slate-800">
            📜 编年史
          </router-link>
          <button
            type="button"
            class="text-sm text-slate-500 hover:text-slate-800"
            @click="feedbackOpen = true"
          >💬 反馈</button>
          <button
            type="button"
            class="text-xs text-slate-400 hover:text-slate-600 shrink-0"
            @click="modelSwitchOpen = true"
            title="切换 GM 模型"
          >⚙️ 模型</button>
          <button
            type="button"
            class="text-xs text-slate-400 hover:text-slate-600 shrink-0"
            @click="settingsOpen = true"
            title="游戏设置"
          >🔧 设置</button>
          <router-link to="/sessions" class="text-sm text-slate-500 hover:text-slate-800">
            返回存档
          </router-link>
          <span class="text-xs text-slate-400 ml-2">v{{ version }}</span>
        </div>
```

Replace with:

```html
        <div class="flex items-center gap-3 shrink-0">
          <button
            type="button"
            class="text-sm text-slate-500 hover:text-slate-800"
            @click="characterCardOpen = true"
          >📜 角色卡</button>
          <el-dropdown trigger="click" placement="bottom-end">
            <button type="button"
                    class="text-sm text-slate-500 hover:text-slate-800 px-1">···</button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item>
                  <router-link :to="`/play/${sessionId}/screenplay`"
                               class="block w-full">📜 剧本</router-link>
                </el-dropdown-item>
                <el-dropdown-item>
                  <router-link :to="`/play/${sessionId}/journal`"
                               class="block w-full">📖 任务日志</router-link>
                </el-dropdown-item>
                <el-dropdown-item>
                  <router-link :to="`/play/${sessionId}/npcs`"
                               class="block w-full">📒 NPC</router-link>
                </el-dropdown-item>
                <el-dropdown-item>
                  <router-link :to="`/play/${sessionId}/relations`"
                               class="block w-full">🔗 关系</router-link>
                </el-dropdown-item>
                <el-dropdown-item>
                  <router-link :to="`/play/${sessionId}/chronicle`"
                               class="block w-full">📜 编年史</router-link>
                </el-dropdown-item>
                <el-dropdown-item divided @click="feedbackOpen = true">
                  💬 反馈
                </el-dropdown-item>
                <el-dropdown-item @click="modelSwitchOpen = true">
                  ⚙️ 模型
                </el-dropdown-item>
                <el-dropdown-item @click="settingsOpen = true">
                  🔧 设置
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
          <router-link to="/sessions" class="text-sm text-slate-500 hover:text-slate-800 shrink-0">
            返回存档
          </router-link>
          <span class="text-xs text-slate-400">v{{ version }}</span>
        </div>
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd /Users/norman/development/dzmm/.claude/worktrees/v0.2.5-gameplay-quality/frontend
npm run type-check
```

Expected: no errors

- [ ] **Step 3: Verify visually**

Start the dev server and open a session. The header should show: `[角色卡] [···▾] [返回存档] [v0.x.x]`. Clicking `···` opens a dropdown with剧本/任务日志/NPC/关系/编年史/反馈/模型/设置.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/views/GameView.vue
git commit -m "feat(nav): collapse secondary header links into ··· dropdown"
```

---

### Task 7: Doom Meter — hidden bad-ending accumulator

**Files:**
- Modify: `backend/src/dzmm/db/models.py` — add `doom_score` to Session
- Modify: `backend/src/dzmm/db/base.py` — add V026 migration
- Create: `backend/src/dzmm/service/state_apply/doom.py` — `<doom>` tag handler
- Modify: `backend/src/dzmm/service/state_apply/_impl.py` — register doom handler
- Modify: `backend/src/dzmm/prompts/gm_template.py` — add `<doom>` format + dice rule
- Modify: `backend/src/dzmm/service/game.py` — inject doom level + probability check
- Test: `backend/tests/test_state_apply.py` (or new file)

Context: There is currently no failure-ending path. Design: Session.doom_score (0-100) accumulates when GM emits `<doom delta="+N">` after dice failures/bad events; `<event_complete type="main">` auto-reduces by 10. Before building GM messages each turn, if doom≥60 a Python random check fires — on hit, inject a "坏结局触发" flag into key_facts so the GM writes `<ending type="bad">`. The `<ending>` handler already exists in `screenplay.py`.

**Doom probability thresholds:**
- 0–59: no check
- 60–79: 10% per turn
- 80–89: 25% per turn
- 90–99: 50% per turn
- 100: certain (100%)

- [ ] **Step 1: Add `doom_score` to Session model in `models.py`**

Open `backend/src/dzmm/db/models.py`. Find the Session class. After `settings_json` line, add:

```python
doom_score: Mapped[int] = mapped_column(Integer, default=0)  # v0.2.5
```

- [ ] **Step 2: Add V026 migration in `base.py`**

After the `_V025_MIGRATIONS` dict, add:

```python
_V026_MIGRATIONS: dict[str, list[tuple[str, str]]] = {
    "sessions": [
        ("doom_score", "doom_score INTEGER NOT NULL DEFAULT 0"),
    ],
}
```

And add at the end of `init_db()`:

```python
        for table, cols in _V026_MIGRATIONS.items():
            await conn.run_sync(_add_missing_columns_sync, table, cols)
```

- [ ] **Step 3: Write the failing test**

Create `backend/tests/test_doom.py`:

```python
import pytest
from sqlalchemy import select
from dzmm.db.base import init_db, get_engine, async_session
from dzmm.db.models import (
    Character, ModelConfig, Session as GameSession, World,
)
from dzmm.service.state_apply._impl import apply_tags
from dzmm.parsing.events import TagComplete


@pytest.fixture
async def db(tmp_path):
    engine = get_engine(f"sqlite+aiosqlite:///{tmp_path}/d.db")
    await init_db(engine)
    SM = async_session(engine)
    async with SM() as s:
        world = World(name="W", content_md="x", style="dark")
        char = Character(world=world, name="C", profile_md="y", base_stats_json="{}")
        cfg = ModelConfig(name="m", type="ollama", base_url="http://localhost:11434", model_name="q")
        s.add_all([world, char, cfg])
        await s.flush()
        sess = GameSession(name="r", world_id=world.id, character_id=char.id,
                           gm_model_config_id=cfg.id, summarizer_model_config_id=cfg.id)
        s.add(sess)
        await s.commit()
        yield SM, sess.id
    await engine.dispose()


async def test_doom_tag_increases_score(db):
    SM, sid = db
    async with SM() as s:
        await apply_tags(s, sid, 1, [TagComplete(name="doom", attrs={"delta": "+15"}, content="")])
        await s.commit()
    async with SM() as s:
        sess = await s.get(GameSession, sid)
        assert sess.doom_score == 15


async def test_doom_tag_decreases_score(db):
    SM, sid = db
    async with SM() as s:
        sess = await s.get(GameSession, sid)
        sess.doom_score = 30
        await s.commit()
    async with SM() as s:
        await apply_tags(s, sid, 2, [TagComplete(name="doom", attrs={"delta": "-10"}, content="")])
        await s.commit()
    async with SM() as s:
        sess = await s.get(GameSession, sid)
        assert sess.doom_score == 20


async def test_doom_score_never_below_zero(db):
    SM, sid = db
    async with SM() as s:
        await apply_tags(s, sid, 1, [TagComplete(name="doom", attrs={"delta": "-50"}, content="")])
        await s.commit()
    async with SM() as s:
        sess = await s.get(GameSession, sid)
        assert sess.doom_score == 0


async def test_doom_score_capped_at_100(db):
    SM, sid = db
    async with SM() as s:
        sess = await s.get(GameSession, sid)
        sess.doom_score = 95
        await s.commit()
    async with SM() as s:
        await apply_tags(s, sid, 1, [TagComplete(name="doom", attrs={"delta": "+20"}, content="")])
        await s.commit()
    async with SM() as s:
        sess = await s.get(GameSession, sid)
        assert sess.doom_score == 100
```

- [ ] **Step 4: Run tests to verify they fail**

```bash
cd /Users/norman/development/dzmm/.claude/worktrees/v0.2.5-gameplay-quality/backend
python -m pytest tests/test_doom.py -v
```

Expected: FAIL (doom handler doesn't exist yet)

- [ ] **Step 5: Create `doom.py` handler**

Create `backend/src/dzmm/service/state_apply/doom.py`:

```python
"""<doom delta="±N"> handler — update Session.doom_score (0-100)."""

from sqlalchemy.ext.asyncio import AsyncSession

from dzmm.db.models import Session as GameSession


async def _apply_doom(
    session: AsyncSession,
    session_id: int,
    attrs: dict[str, str],
) -> None:
    try:
        delta = int(attrs.get("delta", "0"))
    except ValueError:
        return
    if delta == 0:
        return
    sess = await session.get(GameSession, session_id)
    if sess is None:
        return
    sess.doom_score = max(0, min(100, sess.doom_score + delta))
```

- [ ] **Step 6: Register handler in `_impl.py`**

Add import at top of `backend/src/dzmm/service/state_apply/_impl.py`:

```python
from dzmm.service.state_apply.doom import _apply_doom
```

Add to `apply_tags()` dispatcher (after `elif tag.name == "ending":` block):

```python
        elif tag.name == "doom":
            await _apply_doom(session, session_id, tag.attrs)
```

- [ ] **Step 7: Run tests to verify they pass**

```bash
cd /Users/norman/development/dzmm/.claude/worktrees/v0.2.5-gameplay-quality/backend
python -m pytest tests/test_doom.py -v
```

Expected: 4/4 PASS

- [ ] **Step 8: Auto-reduce doom on main event_complete in `screenplay.py`**

Open `backend/src/dzmm/service/state_apply/screenplay.py`. Find `_apply_event_complete()`. After the XP grant block, add:

```python
    # Completing a main event reduces doom pressure.
    if type_ == "main":
        sess = await session.get(GameSession, session_id)
        if sess is not None:
            sess.doom_score = max(0, sess.doom_score - 10)
```

- [ ] **Step 9: Add `<doom>` format doc to `gm_template.py`**

In the output format section (near `<character_xp>`), add:

```
<doom delta="+5|-5|+15">
骰点后必须 emit。失败 → +5；大失败（d20=1）→ +15；大成功（d20≥DC+5）→ -5。
重大负面事件（NPC 死亡/阵营背叛/主线受损）可 emit +10~+20。
</doom>
```

- [ ] **Step 10: Inject doom level + probability trigger in `game.py`**

Open `backend/src/dzmm/service/game.py`. Add import at top:

```python
import random
```

Find the section where `key_facts` is built (around line 128), after the director pass block, before `build_gm_messages()`. Add:

```python
    # Doom meter: inject current pressure level into key_facts + maybe trigger bad ending.
    doom = sess.doom_score
    if doom > 0:
        if doom < 60:
            doom_note = f"## ⚠️ 压力值（仅GM可见）\n当前厄运值：{doom}/100（低风险，正常叙事）。"
        elif doom < 80:
            doom_note = f"## ⚠️ 压力值（仅GM可见）\n当前厄运值：{doom}/100（中等压力）。叙事基调偏阴沉，NPC 更紧张，事态更难控制。"
            if random.random() < 0.10:
                doom_note += "\n\n🔴 **坏结局触发**：本回合必须演出一个不可逆的恶化事件并 emit `<ending type=\"bad\">`。"
        elif doom < 90:
            doom_note = f"## ⚠️ 压力值（仅GM可见）\n当前厄运值：{doom}/100（高压力）。世界对PC持续恶化。"
            if random.random() < 0.25:
                doom_note += "\n\n🔴 **坏结局触发**：本回合必须演出一个不可逆的恶化事件并 emit `<ending type=\"bad\">`。"
        elif doom < 100:
            doom_note = f"## ⚠️ 压力值（仅GM可见）\n当前厄运值：{doom}/100（临界崩溃）。"
            if random.random() < 0.50:
                doom_note += "\n\n🔴 **坏结局触发**：本回合必须演出一个不可逆的恶化事件并 emit `<ending type=\"bad\">`。"
        else:
            doom_note = f"## ⚠️ 压力值（仅GM可见）\n当前厄运值：100/100。\n\n🔴 **坏结局触发**：本回合必须演出末日事件并 emit `<ending type=\"bad\">`。"
        key_facts = key_facts + "\n\n" + doom_note
```

- [ ] **Step 11: Run all backend tests**

```bash
cd /Users/norman/development/dzmm/.claude/worktrees/v0.2.5-gameplay-quality/backend
python -m pytest tests/ -v -k "not ollama"
```

Expected: all pass

- [ ] **Step 12: Commit**

```bash
git add backend/src/dzmm/db/models.py \
        backend/src/dzmm/db/base.py \
        backend/src/dzmm/service/state_apply/doom.py \
        backend/src/dzmm/service/state_apply/_impl.py \
        backend/src/dzmm/service/state_apply/screenplay.py \
        backend/src/dzmm/prompts/gm_template.py \
        backend/src/dzmm/service/game.py \
        backend/tests/test_doom.py
git commit -m "feat(doom): hidden doom meter with probabilistic bad ending trigger"
```

---

### Task 8: Footer quick-actions redesign — mode chips + remove useless fallback

**Files:**
- Modify: `frontend/src/views/GameView.vue` — replace suggestions row with 4 mode chips

Context: The current footer has a row of suggestion buttons with a hardcoded fallback `['环顾四周', '探索', '搭话']` that's always shown (even when useless) and creates a blank-looking row. Replace with 4 action-mode chips that prefill the textarea with contextual templates. API-generated suggestions still show when loaded, appended after the chips.

- [ ] **Step 1: Replace the footer suggestions section in `GameView.vue`**

Find:

```html
      <footer class="border-t bg-white p-4 space-y-2">
        <div class="flex flex-wrap gap-2">
          <el-button
            v-for="s in (suggestions.length ? suggestions : ['环顾四周', '探索', '搭话'])"
            :key="s"
            size="small"
            @click="quick(s)"
            :disabled="sending"
          >{{ s }}</el-button>
        </div>
```

Replace with:

```html
      <footer class="border-t bg-white p-4 space-y-2">
        <div class="flex flex-wrap gap-2 items-center">
          <!-- Action mode chips — prefill textarea with template -->
          <el-button size="small" :disabled="sending"
            @click="action = ''; $nextTick(() => ($el.querySelector('textarea'))?.focus())">
            ⚔️ 行动
          </el-button>
          <el-button size="small" :disabled="sending"
            @click="action = '对__说：\"'; $nextTick(() => ($el.querySelector('textarea'))?.focus())">
            💬 对话
          </el-button>
          <el-button size="small" :disabled="sending"
            @click="action = '仔细调查 '; $nextTick(() => ($el.querySelector('textarea'))?.focus())">
            🔍 调查
          </el-button>
          <el-button size="small" :disabled="sending"
            @click="action = '（用__尝试__）'; $nextTick(() => ($el.querySelector('textarea'))?.focus())">
            🎲 技能
          </el-button>
          <!-- Divider before API suggestions -->
          <span v-if="suggestions.length" class="text-slate-300 select-none">|</span>
          <!-- API-generated suggestions — only shown when loaded -->
          <el-button
            v-for="s in suggestions"
            :key="s"
            size="small"
            type="info"
            plain
            @click="quick(s)"
            :disabled="sending"
          >{{ s }}</el-button>
        </div>
```

- [ ] **Step 2: Fix `$el.querySelector` — use a template ref for the textarea instead**

The `$el.querySelector` approach in an `el-button` click handler is fragile. Add a template ref for the textarea in the script section.

Add in `<script setup>`:

```typescript
const textareaRef = ref<HTMLTextAreaElement | null>(null)

function setMode(prefix: string) {
  action.value = prefix
  nextTick(() => {
    const el = textareaRef.value
    if (el) {
      el.focus()
      el.setSelectionRange(el.value.length, el.value.length)
    }
  })
}
```

Update the `el-input` to bind the ref. Find:

```html
          <el-input
            v-model="action"
            type="textarea"
            :autosize="{ minRows: 2, maxRows: 6 }"
            placeholder="输入你的行动…（Enter 发送，Shift+Enter 换行）"
            :disabled="sending"
            @keydown="onKey"
            @compositionstart="composing = true"
            @compositionend="composing = false"
          />
```

Replace with:

```html
          <el-input
            ref="inputRef"
            v-model="action"
            type="textarea"
            :autosize="{ minRows: 2, maxRows: 6 }"
            placeholder="输入你的行动…（Enter 发送，Shift+Enter 换行）"
            :disabled="sending"
            @keydown="onKey"
            @compositionstart="composing = true"
            @compositionend="composing = false"
          />
```

Add in `<script setup>`:

```typescript
const inputRef = ref<InstanceType<typeof ElInput> | null>(null)

function setMode(prefix: string) {
  action.value = prefix
  nextTick(() => {
    const textarea = inputRef.value?.textarea
    if (textarea) {
      textarea.focus()
      textarea.setSelectionRange(prefix.length, prefix.length)
    }
  })
}
```

Update the mode chip buttons to use `setMode()`:

```html
          <el-button size="small" :disabled="sending" @click="setMode('')">
            ⚔️ 行动
          </el-button>
          <el-button size="small" :disabled="sending" @click="setMode('对__说：\"')">
            💬 对话
          </el-button>
          <el-button size="small" :disabled="sending" @click="setMode('仔细调查 ')">
            🔍 调查
          </el-button>
          <el-button size="small" :disabled="sending" @click="setMode('（用__尝试__）')">
            🎲 技能
          </el-button>
          <span v-if="suggestions.length" class="text-slate-300 select-none">|</span>
          <el-button
            v-for="s in suggestions"
            :key="s"
            size="small"
            type="info"
            plain
            @click="quick(s)"
            :disabled="sending"
          >{{ s }}</el-button>
```

Also add `ElInput` to script imports if not already present:

```typescript
import { ElMessage, ElInput } from 'element-plus'
```

- [ ] **Step 3: Verify TypeScript compiles**

```bash
cd /Users/norman/development/dzmm/.claude/worktrees/v0.2.5-gameplay-quality/frontend
npm run type-check
```

Expected: no errors

- [ ] **Step 4: Verify visually**

Start dev server. The footer should show: `[⚔️ 行动] [💬 对话] [🔍 调查] [🎲 技能]` — no blank space, no useless generic suggestions. Clicking 💬 对话 should prefill the textarea with `对__说："` and focus it.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/views/GameView.vue
git commit -m "feat(footer): replace generic suggestions with action-mode chips; no useless fallback"
```

---

### Task 9: Event keywords & completion criteria in screenplay

**Files:**
- Modify: `backend/src/dzmm/prompts/outliner_template.py` — add `keywords` + `criteria` to event schema
- Modify: `backend/src/dzmm/service/game.py` — render new fields in key_facts; backward compat for string events
- Modify: `backend/tests/test_outliner_template.py` (if exists) or new test

Context: Events in `chapters_json` are currently plain strings e.g. `"主角发现被跟踪"`. There's no guidance for GM on *when* the event is active or *when* to emit `<event_complete>`. New format adds two fields per event:
- `keywords`: 3-5 short words/phrases the GM can watch for in PC actions/NPC dialogue
- `criteria`: one concrete sentence stating the exact completion condition

The `chapters_json` column already stores arbitrary JSON, so no DB migration needed — it's a pure schema change in how the outliner generates and how `game.py` renders events. Old screenplays (string events) must still work.

- [ ] **Step 1: Write the failing test**

```bash
cd /Users/norman/development/dzmm/.claude/worktrees/v0.2.5-gameplay-quality/backend
```

Add to `backend/tests/test_outliner_template.py` (create if it doesn't exist):

```python
import json
import pytest
from dzmm.prompts.outliner_template import build_outliner_messages


def test_outliner_system_prompt_includes_keywords_and_criteria():
    """Outliner schema must instruct LLM to output keywords + criteria per event."""
    msgs = build_outliner_messages(
        world_name="W", world_md="x",
        character_name="C", character_md="y",
        genre="悬疑探案",
    )
    sys = msgs[0].content
    assert "keywords" in sys
    assert "criteria" in sys or "完成标准" in sys
```

Run:

```bash
python -m pytest tests/test_outliner_template.py::test_outliner_system_prompt_includes_keywords_and_criteria -v
```

Expected: FAIL

- [ ] **Step 2: Update outliner event schema in `outliner_template.py`**

Open `backend/src/dzmm/prompts/outliner_template.py`. Replace the current `main_events`/`optional_events` schema lines:

```python
      "main_events": ["主线事件 1（必演）", "主线事件 2（必演）"],
      "optional_events": ["分支事件 1（PC 探索才触发）", "分支事件 2"],
```

With structured event objects:

```python
      "main_events": [
        {{
          "description": "主线事件描述（20-40字）",
          "keywords": ["触发关键词1", "关键词2", "关键词3"],
          "criteria": "完成标准：具体可判断的一句话（15-25字）"
        }}
      ],
      "optional_events": [
        {{
          "description": "支线事件描述",
          "keywords": ["关键词1", "关键词2"],
          "criteria": "完成标准"
        }}
      ],
```

Also add to the design requirements section (after point 6):

```
7. 每个事件的 keywords 3-5 个（名词或动词短语，GM 在 narrative/PC行动中看到这些词时应推进该事件）
8. 每个事件的 criteria 是 15-25 字的具体条件，GM 确认满足后立即 emit <event_complete>
```

- [ ] **Step 3: Run test to verify it passes**

```bash
python -m pytest tests/test_outliner_template.py -v
```

Expected: PASS

- [ ] **Step 4: Update event rendering in `game.py` with backward compatibility**

Open `backend/src/dzmm/service/game.py`. Add a helper function near the top of `_build_key_facts()` (or as a module-level function):

```python
def _render_event(ev: str | dict) -> str:
    """Render a screenplay event (new dict format or legacy string) as GM-facing text."""
    if isinstance(ev, str):
        return ev
    desc = ev.get("description", "")
    keywords = ev.get("keywords") or []
    criteria = ev.get("criteria", "")
    parts = [desc]
    if keywords:
        parts.append(f"  关键词：{'／'.join(keywords)}")
    if criteria:
        parts.append(f"  完成标准：{criteria}")
    return "\n".join(parts)
```

Then replace the two rendering sections in `_build_key_facts()`:

Replace (main events render, ~line 595):
```python
                    sp_lines.append(f"- {flag} {ev}")
```
With:
```python
                    sp_lines.append(f"- {flag} {_render_event(ev)}")
```

Replace (optional events render, ~line 608):
```python
                    sp_lines.append(f"- {flag} {ev}")
```
With:
```python
                    sp_lines.append(f"- {flag} {_render_event(ev)}")
```

Also update the hard-push directive section (~line 665) which reads the event directly. Find:
```python
                pending_main_pairs = [
                    (i, ev) for i, ev in enumerate(main_events)
                    if i not in done_main_idxs
                ]
```
And the line that formats the directive (a few lines later, search for `next_ev` or similar). Wrap any direct `ev` string usage with `_render_event(ev)`.

- [ ] **Step 5: Run all backend tests**

```bash
cd /Users/norman/development/dzmm/.claude/worktrees/v0.2.5-gameplay-quality/backend
python -m pytest tests/ -v -k "not ollama"
```

Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add backend/src/dzmm/prompts/outliner_template.py \
        backend/src/dzmm/service/game.py \
        backend/tests/test_outliner_template.py
git commit -m "feat(screenplay): events get keywords + criteria; GM sees exact completion conditions"
```
