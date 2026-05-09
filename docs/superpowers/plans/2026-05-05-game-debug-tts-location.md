# Game Debug / TTS Speaker Filter / Location Enhancement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Five features: (3) TTS per-speaker on/off in game page; (4) debug viewer for per-turn LLM prompt + response; (5) wizard character prompt always includes starting currency; (6) location panel shows NPCs present; (8) debug stats editor for doom/PC stats/turn counts.

**Architecture:** Backend adds one column (`messages.prompt_json`), two endpoints (`GET /messages/{id}/debug`, `PATCH /sessions/{id}/debug_state`), and a `debug_mode` session setting. Frontend adds speaker-filter logic in `useTTS`, a new `DebugPanel.vue` component, per-turn debug buttons in `MessageList`, and richer location content in `StatePanel`. The existing debug store (Konami toggle) gates all debug UI.

**Tech Stack:** Vue 3 + TypeScript + Element Plus; FastAPI + SQLAlchemy + SQLite; Pinia stores (`useAppStore`, `useDebugStore`).

---

## File Structure

**Modified:**
- `frontend/src/stores/app.ts` — three new TTS speaker filter refs + save
- `frontend/src/composables/useTTS.ts` — accept + apply speaker filter in `playTurn`
- `frontend/src/views/GameView.vue` — TTS filter popover; DebugPanel wiring
- `frontend/src/components/game/MessageList.vue` — debug button per assistant turn
- `frontend/src/components/StatePanel.vue` — NPCs at current location section
- `frontend/src/api/sessions.ts` — `messageDebug()`, `patchDebugState()`, `patchSettings()`
- `backend/src/dzmm/db/models.py` — `prompt_json` on `Message`
- `backend/src/dzmm/db/base.py` — `_V031_MIGRATIONS`
- `backend/src/dzmm/service/game.py` — populate `prompt_json` + `_debug_prompt_json` local
- `backend/src/dzmm/api/routes_sessions/turn.py` — emit `assistant_msg_id` in `done` event
- `backend/src/dzmm/api/routes_sessions/messages.py` — `GET /{session_id}/messages/{msg_id}/debug`
- `backend/src/dzmm/api/routes_sessions/base.py` — `debug_mode` in settings PATCH; `PATCH /{id}/debug_state`
- `backend/src/dzmm/prompts/wizard_character.py` — currency requirement

**Created:**
- `frontend/src/components/game/DebugPanel.vue`

---

## Task 1: TTS Per-Speaker Filter

**Files:**
- Modify: `frontend/src/stores/app.ts`
- Modify: `frontend/src/composables/useTTS.ts`
- Modify: `frontend/src/views/GameView.vue`

- [ ] **Step 1: Add three refs to `app.ts`**

After `const ttsDirectUrl = ref(...)` (around line 62), add:

```typescript
const ttsNarratorEnabled = ref(loadTtsSetting('narrator_enabled', true))
const ttsPcEnabled = ref(loadTtsSetting('pc_enabled', true))
const ttsNpcEnabled = ref(loadTtsSetting('npc_enabled', true))
```

Inside `saveTtsSettings()`, after the existing `localStorage.setItem` calls, add:
```typescript
localStorage.setItem('dzmm.tts.narrator_enabled', ttsNarratorEnabled.value ? '1' : '0')
localStorage.setItem('dzmm.tts.pc_enabled', ttsPcEnabled.value ? '1' : '0')
localStorage.setItem('dzmm.tts.npc_enabled', ttsNpcEnabled.value ? '1' : '0')
```

In `return { ... }`, add:
```typescript
ttsNarratorEnabled,
ttsPcEnabled,
ttsNpcEnabled,
```

- [ ] **Step 2: Add `TtsSpeakerFilter` interface and update `playTurn` in `useTTS.ts`**

After the `TtsVoiceMap` interface (line 6), add:

```typescript
export interface TtsSpeakerFilter {
  narratorEnabled: boolean
  pcEnabled: boolean
  npcEnabled: boolean
}
```

Change the `playTurn` signature to:
```typescript
async function playTurn(
  rawContent: string | undefined,
  voiceMap: TtsVoiceMap,
  filter?: TtsSpeakerFilter,
): Promise<void>
```

After `let segments = parseSegments(rawContent)` (currently `const segments`), add:
```typescript
let segments = parseSegments(rawContent)
if (filter) {
  segments = segments.filter((seg) => {
    if (seg.speaker === 'narrator') return filter.narratorEnabled
    if (seg.speaker === 'pc') return filter.pcEnabled
    return filter.npcEnabled
  })
}
```

Change `const segments = parseSegments(rawContent)` → `let segments = parseSegments(rawContent)` in `playTurn`.

- [ ] **Step 3: Pass filter from `GameView.vue`**

Add import of `TtsSpeakerFilter`:
```typescript
import { useTTS, type TtsVoiceMap, type TtsSpeakerFilter } from '@/composables/useTTS'
```

In `onTurnDone`, replace the `playTurn` calls with:
```typescript
const filter: TtsSpeakerFilter = {
  narratorEnabled: appStore.ttsNarratorEnabled,
  pcEnabled: appStore.ttsPcEnabled,
  npcEnabled: appStore.ttsNpcEnabled,
}
sessionsApi.npcs(sessionId).then((npcList) => {
  playTurn(raw, buildVoiceMap(npcList), filter)
}).catch(() => {
  playTurn(raw, buildVoiceMap([]), filter)
})
```

- [ ] **Step 4: Add TTS speaker-filter popover in `GameView.vue`**

Find the area near the TTS speaking indicator (search for `v-if="appStore.ttsEnabled && speaking"`). Just before that block, add a permanent TTS settings popover that is visible whenever TTS is enabled:

```html
<!-- TTS speaker filter — visible when TTS enabled -->
<template v-if="appStore.ttsEnabled">
  <el-popover placement="bottom-end" :width="180" trigger="click">
    <template #reference>
      <button class="text-slate-400 hover:text-slate-600 text-sm px-1" title="语音设置">🔊</button>
    </template>
    <div class="text-sm space-y-2">
      <div class="font-medium text-slate-600 text-xs mb-1">播放语音</div>
      <div class="flex items-center justify-between">
        <span class="text-slate-700">旁白</span>
        <el-switch size="small" v-model="appStore.ttsNarratorEnabled" @change="appStore.saveTtsSettings()" />
      </div>
      <div class="flex items-center justify-between">
        <span class="text-slate-700">PC 行动</span>
        <el-switch size="small" v-model="appStore.ttsPcEnabled" @change="appStore.saveTtsSettings()" />
      </div>
      <div class="flex items-center justify-between">
        <span class="text-slate-700">NPC 对话</span>
        <el-switch size="small" v-model="appStore.ttsNpcEnabled" @change="appStore.saveTtsSettings()" />
      </div>
    </div>
  </el-popover>
</template>
```

- [ ] **Step 5: Build and verify**

```bash
cd /Users/norman/development/dzmm/frontend && npm run build 2>&1 | tail -5
```
Expected: `✓ built in X.XXs`

- [ ] **Step 6: Commit**

```bash
cd /Users/norman/development/dzmm && git add frontend/src/stores/app.ts frontend/src/composables/useTTS.ts frontend/src/views/GameView.vue
git commit -m "feat(tts): per-speaker filter (narrator/PC/NPC toggles) with popover UI"
```

---

## Task 2: Debug LLM Prompt Viewer

When debug mode is on (Konami code), capture the full prompt sent to the LLM and show it alongside the raw response in a per-turn dialog.

**Files:**
- Modify: `backend/src/dzmm/db/models.py`
- Modify: `backend/src/dzmm/db/base.py`
- Modify: `backend/src/dzmm/api/routes_sessions/base.py`
- Modify: `backend/src/dzmm/service/game.py`
- Modify: `backend/src/dzmm/api/routes_sessions/turn.py`
- Modify: `backend/src/dzmm/api/routes_sessions/messages.py`
- Modify: `frontend/src/api/sessions.ts`
- Modify: `frontend/src/components/game/MessageList.vue`

- [ ] **Step 1: Add `prompt_json` to `Message` model**

In `backend/src/dzmm/db/models.py`, in the `Message` class after `parts_json`:

```python
prompt_json: Mapped[str] = mapped_column(Text, default="")  # full prompt, set when debug_mode=true
```

- [ ] **Step 2: DB migration for `prompt_json`**

In `backend/src/dzmm/db/base.py`, after `_V030_MIGRATIONS` dict, add:

```python
_V031_MIGRATIONS: dict[str, list[tuple[str, str]]] = {
    "messages": [
        ("prompt_json", "prompt_json TEXT NOT NULL DEFAULT ''"),
    ],
}
```

At the end of `init_db()`, after the `_V030_MIGRATIONS` loop, add:

```python
for table, cols in _V031_MIGRATIONS.items():
    await conn.run_sync(_add_missing_columns_sync, table, cols)
```

- [ ] **Step 3: Add `debug_mode` to settings PATCH**

In `backend/src/dzmm/api/routes_sessions/base.py`, extend `PatchSettingsRequest`:

```python
class PatchSettingsRequest(BaseModel):
    narrative_polish: bool | None = None
    director_pass: bool | None = None
    debug_mode: bool | None = None
```

In `patch_session_settings`, after the `director_pass` block, add:

```python
if body.debug_mode is not None:
    settings["debug_mode"] = body.debug_mode
```

- [ ] **Step 4: Capture prompt in `game.py` when `debug_mode` is active**

In `backend/src/dzmm/service/game.py`, after `msgs = build_gm_messages(...)` (find this call around the `action_with_reminder` usage), add:

```python
_debug_prompt_json = ""
if settings.get("debug_mode"):
    _debug_prompt_json = json.dumps(
        [{"role": m.role, "content": m.content} for m in msgs],
        ensure_ascii=False,
    )
```

In the `session.add(MessageRow(...))` for the assistant message, add `prompt_json=_debug_prompt_json`:

```python
session.add(MessageRow(
    session_id=session_id, role="assistant", content=full_output, turn=next_turn,
    tokens_in=usage.input_tokens, tokens_out=usage.output_tokens,
    events_json=json.dumps(events_payload, ensure_ascii=False),
    prompt_json=_debug_prompt_json,
))
```

- [ ] **Step 5: Emit `assistant_msg_id` in the `done` SSE event**

In `backend/src/dzmm/api/routes_sessions/turn.py`, replace the final `done` yield (line ~232) with:

```python
# Query the just-committed assistant message ID so the frontend can
# use it for debug lookups without a separate messages fetch.
async with session_maker() as _s2:
    _last_id = (
        await _s2.execute(
            select(MessageRow.id)
            .where(
                MessageRow.session_id == session_id,
                MessageRow.role == "assistant",
            )
            .order_by(MessageRow.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
yield {"event": "done", "data": json.dumps({"assistant_msg_id": _last_id})}
```

- [ ] **Step 6: Add `msgId` to `Turn` interface and populate it in `useGameTurn.ts`**

In `frontend/src/composables/useGameTurn.ts`, find the `Turn` interface and add:

```typescript
export interface Turn {
  action: string
  narrative: string
  choices: string[]
  events: TurnEvent[]
  turn: number
  rawContent?: string
  msgId?: number       // assistant message DB id, populated from 'done' event
}
```

In the `onDone` handler (the `done` SSE event handler in `streamTurn`), capture the msg id. In `useGameTurn.ts`, find where `onDone` is called (around the `done` event dispatch in `streamTurn` composable). The `onDone` receives the full turn object — the `done` event data now contains `{assistant_msg_id}`.

Find in `frontend/src/api/sessions.ts` the `streamTurn` function and locate where it handles the `done` event:

```typescript
// In streamTurn, find the done event handler and update:
} else if (block.event === 'done') {
  const doneData = JSON.parse(block.data || '{}')
  handlers.onDone?.(doneData)
}
```

Then in `useGameTurn.ts`'s `streamTurn` call, update `onDone`:

```typescript
onDone: (doneData?: { assistant_msg_id?: number }) => {
  if (doneData?.assistant_msg_id) {
    turn.msgId = doneData.assistant_msg_id
  }
  turnCount.value += 1
  // ... rest of onDone handler
```

Find the exact `onDone` wiring in `useGameTurn.ts` (the `streamTurn(sessionId, userAction, { ..., onDone: () => { ... } })` call) and add the msg id capture.

- [ ] **Step 7: Add debug endpoint in `messages.py`**

In `backend/src/dzmm/api/routes_sessions/messages.py`, add at the end:

```python
@router.get("/{session_id}/messages/{msg_id}/debug")
async def get_message_debug(
    session_id: int,
    msg_id: int,
    s: AsyncSession = Depends(get_session_dep),
):
    msg = await s.get(MessageRow, msg_id)
    if msg is None or msg.session_id != session_id:
        raise HTTPException(404, "message not found")
    return {
        "id": msg.id,
        "turn": msg.turn,
        "prompt_json": msg.prompt_json or "",
        "content": msg.content,
        "tokens_in": msg.tokens_in,
        "tokens_out": msg.tokens_out,
    }
```

- [ ] **Step 8: Add API client methods in `sessions.ts`**

In `frontend/src/api/sessions.ts`, add to `sessionsApi`:

```typescript
messageDebug: (sessionId: number, msgId: number) =>
  api
    .get<{
      id: number
      turn: number
      prompt_json: string
      content: string
      tokens_in: number
      tokens_out: number
    }>(`/sessions/${sessionId}/messages/${msgId}/debug`)
    .then((r) => r.data),

patchSettings: (
  sessionId: number,
  settings: { debug_mode?: boolean; narrative_polish?: boolean; director_pass?: boolean },
) => api.patch(`/sessions/${sessionId}/settings`, settings).then((r) => r.data),
```

- [ ] **Step 9: Add debug button + dialog to `MessageList.vue`**

Add imports:
```typescript
import { ref } from 'vue'
import { useDebugStore } from '@/stores/debug'
import { sessionsApi } from '@/api/sessions'
```

Add props for sessionId:
```typescript
const props = defineProps<{
  turns: Turn[]
  sending: boolean
  currentTurn: Turn | null
  sessionId: number
}>()
```

Add state and handler:
```typescript
const debug = useDebugStore()
const debugDialogOpen = ref(false)
interface DebugInfo { prompt: object[]; response: string; tokensIn: number; tokensOut: number }
const debugInfo = ref<DebugInfo | null>(null)

async function openDebug(turn: Turn) {
  if (!turn.msgId) return
  const d = await sessionsApi.messageDebug(props.sessionId, turn.msgId)
  debugInfo.value = {
    prompt: d.prompt_json ? JSON.parse(d.prompt_json) : [],
    response: d.content,
    tokensIn: d.tokens_in,
    tokensOut: d.tokens_out,
  }
  debugDialogOpen.value = true
}
```

In the template, inside each assistant turn card, add the debug button (visible only when `debug.enabled && t.msgId`):

```html
<button
  v-if="debug.enabled && t.msgId"
  class="text-xs text-slate-400 hover:text-slate-600 ml-1"
  title="查看LLM原始数据"
  @click="openDebug(t)"
>
  🐛
</button>
```

Add a dialog at the bottom of the template:
```html
<el-dialog
  v-model="debugDialogOpen"
  title="LLM 原始数据"
  width="80%"
  class="debug-dialog"
>
  <div v-if="debugInfo" class="space-y-4 text-xs font-mono">
    <div>
      <div class="font-bold text-slate-600 mb-1">
        发送给 LLM（{{ debugInfo.tokensIn }} tokens in）
      </div>
      <div class="bg-slate-50 border rounded p-2 max-h-64 overflow-auto whitespace-pre-wrap">
        <template v-if="debugInfo.prompt.length">
          <div
            v-for="(msg, i) in debugInfo.prompt"
            :key="i"
            class="mb-2 border-b border-slate-200 pb-2"
          >
            <span class="font-bold" :class="msg.role === 'system' ? 'text-purple-600' : msg.role === 'user' ? 'text-blue-600' : 'text-green-600'">
              [{{ msg.role }}]
            </span>
            {{ msg.content }}
          </div>
        </template>
        <span v-else class="text-slate-400">未记录（需开启 debug_mode 会话设置）</span>
      </div>
    </div>
    <div>
      <div class="font-bold text-slate-600 mb-1">
        LLM 返回（{{ debugInfo.tokensOut }} tokens out）
      </div>
      <div class="bg-slate-50 border rounded p-2 max-h-64 overflow-auto whitespace-pre-wrap">
        {{ debugInfo.response }}
      </div>
    </div>
  </div>
</el-dialog>
```

- [ ] **Step 10: Update `GameView.vue` to pass `sessionId` to `MessageList` and auto-enable `debug_mode` in session settings when debug store is active**

Find where `<MessageList>` is rendered in `GameView.vue` and add the `:session-id="sessionId"` prop.

Also add a watcher that syncs the frontend debug store with the session's `debug_mode` setting:
```typescript
import { watch } from 'vue'
const debug = useDebugStore()
watch(() => debug.enabled, (val) => {
  sessionsApi.patchSettings(sessionId, { debug_mode: val }).catch(() => {})
}, { immediate: true })
```

- [ ] **Step 11: Build and verify**

```bash
cd /Users/norman/development/dzmm/frontend && npm run build 2>&1 | tail -5
```
Expected: `✓ built in X.XXs`

- [ ] **Step 12: Commit**

```bash
cd /Users/norman/development/dzmm && git add \
  backend/src/dzmm/db/models.py \
  backend/src/dzmm/db/base.py \
  backend/src/dzmm/service/game.py \
  backend/src/dzmm/api/routes_sessions/turn.py \
  backend/src/dzmm/api/routes_sessions/messages.py \
  backend/src/dzmm/api/routes_sessions/base.py \
  frontend/src/api/sessions.ts \
  frontend/src/components/game/MessageList.vue \
  frontend/src/views/GameView.vue
git commit -m "feat(debug): per-turn LLM prompt/response viewer with debug_mode session setting"
```

---

## Task 3: Wizard Character — Starting Currency

The character generation prompt must always include at least one currency item in the starting inventory, making the `## 物品` section world-appropriate (coins for fantasy, cash for modern noir, credits for sci-fi).

**Files:**
- Modify: `backend/src/dzmm/prompts/wizard_character.py`

- [ ] **Step 1: Add currency constraint to the `## 物品` section**

In `backend/src/dzmm/prompts/wizard_character.py`, find `_SYSTEM` and the `## 物品` line. Change:

```python
## 物品
（3-5 件，markdown 列表 `- **物品名**：来历 / 效果 / 暗藏伏笔`）
```

To:

```python
## 物品
（3-5 件，markdown 列表 `- **物品名**：来历 / 效果 / 暗藏伏笔`）
**必须**包含 1 件「货币类物品」，如：金币 / 银两 / 港元 / 美金 / 积分卡 / 能量晶石，
数量符合世界观的贫富设定（不要过多或过少），命名贴合世界风格。
```

- [ ] **Step 2: Verify no build breakage**

```bash
cd /Users/norman/development/dzmm/frontend && npm run build 2>&1 | tail -3
```
Expected: `✓ built in X.XXs`

- [ ] **Step 3: Commit**

```bash
cd /Users/norman/development/dzmm && git add backend/src/dzmm/prompts/wizard_character.py
git commit -m "feat(wizard): character starting items always include world-appropriate currency"
```

---

## Task 4: Location Panel — NPCs Present

The location block in `StatePanel.vue` currently shows name + description + items. Add a "此处 NPC" row listing NPCs whose `current_location` matches the current location name.

**Files:**
- Modify: `frontend/src/components/StatePanel.vue`

Context: `StatePanel` already receives `npcs` prop (array with `current_location?: string | null` field, populated by `GameView.refreshNpcLocations()`). The `currentLocation` prop has `.name`.

- [ ] **Step 1: Add `npcsHere` computed property in `StatePanel.vue`**

In `<script setup>`, after the existing `props` definition, add:

```typescript
import { computed } from 'vue'

const npcsHere = computed(() => {
  if (!props.currentLocation) return []
  const locName = props.currentLocation.name.toLowerCase()
  return props.npcs.filter(
    (n) =>
      n.current_location &&
      n.current_location.toLowerCase() === locName,
  )
})
```

- [ ] **Step 2: Add NPCs-here display in the location block**

Find the location block in the template (the `<div v-if="currentLocation"...>` around line 68). After the `items` section, add:

```html
<!-- NPCs at this location -->
<div v-if="npcsHere.length" class="mt-1.5">
  <div class="text-xs font-medium text-blue-700 mb-0.5">此处人物</div>
  <ul class="space-y-0.5">
    <li
      v-for="n in npcsHere"
      :key="n.name"
      class="flex items-center gap-1.5 text-xs"
    >
      <span
        class="w-2 h-2 rounded-full flex-shrink-0"
        :class="n.favor >= 20 ? 'bg-green-400' : n.favor <= -20 ? 'bg-red-400' : 'bg-slate-300'"
      />
      <span class="text-slate-700 font-medium">{{ n.name }}</span>
      <span v-if="n.state" class="text-slate-400 truncate">· {{ n.state }}</span>
    </li>
  </ul>
</div>
```

- [ ] **Step 3: Build and verify**

```bash
cd /Users/norman/development/dzmm/frontend && npm run build 2>&1 | tail -3
```
Expected: `✓ built in X.XXs`

- [ ] **Step 4: Commit**

```bash
cd /Users/norman/development/dzmm && git add frontend/src/components/StatePanel.vue
git commit -m "feat(location): show NPCs present at current location in StatePanel"
```

---

## Task 5: Debug Stats Editor

A collapsible panel (visible only in debug mode) lets developers view and edit doom score, turn counts, and PC stats mid-session.

**Files:**
- Modify: `backend/src/dzmm/api/routes_sessions/base.py`
- Modify: `frontend/src/api/sessions.ts`
- Create: `frontend/src/components/game/DebugPanel.vue`
- Modify: `frontend/src/views/GameView.vue`

- [ ] **Step 1: Add `PATCH /sessions/{id}/debug_state` endpoint**

In `backend/src/dzmm/api/routes_sessions/base.py`, after the existing `PatchSettingsRequest` class, add:

```python
class PatchDebugStateRequest(BaseModel):
    doom_score: int | None = None          # 0-100
    turn_count: int | None = None
    scene_turn_count: int | None = None
    stats_json: str | None = None          # JSON string, e.g. '{"hp": 15}'
    inventory_json: str | None = None      # JSON string array


@router.patch("/{session_id}/debug_state", status_code=200)
async def patch_debug_state(
    session_id: int,
    body: PatchDebugStateRequest,
    s: AsyncSession = Depends(get_session_dep),
):
    """Update mutable game state for debug/testing purposes."""
    import json as _j
    sess = await s.get(GameSession, session_id)
    if sess is None:
        raise HTTPException(404, "session not found")

    if body.doom_score is not None:
        sess.doom_score = max(0, min(100, body.doom_score))
    if body.turn_count is not None:
        sess.turn_count = max(0, body.turn_count)
    if body.scene_turn_count is not None:
        sess.scene_turn_count = max(0, body.scene_turn_count)

    if body.stats_json is not None or body.inventory_json is not None:
        cs = (
            await s.execute(select(CharState).where(CharState.session_id == session_id))
        ).scalar_one_or_none()
        if cs is None:
            cs = CharState(session_id=session_id)
            s.add(cs)
        if body.stats_json is not None:
            _j.loads(body.stats_json)  # validate JSON
            cs.stats_json = body.stats_json
        if body.inventory_json is not None:
            _j.loads(body.inventory_json)  # validate JSON
            cs.inventory_json = body.inventory_json

    await s.commit()
    return {
        "doom_score": sess.doom_score,
        "turn_count": sess.turn_count,
        "scene_turn_count": sess.scene_turn_count,
    }
```

Add missing import at the top of the file:
```python
from dzmm.db.models import CharState
```

- [ ] **Step 2: Add full session debug info endpoint**

Also in `base.py`, add a GET endpoint for debug state:

```python
@router.get("/{session_id}/debug_state")
async def get_debug_state(
    session_id: int,
    s: AsyncSession = Depends(get_session_dep),
):
    import json as _j
    sess = await s.get(GameSession, session_id)
    if sess is None:
        raise HTTPException(404, "session not found")
    cs = (
        await s.execute(select(CharState).where(CharState.session_id == session_id))
    ).scalar_one_or_none()
    return {
        "doom_score": sess.doom_score,
        "turn_count": sess.turn_count,
        "scene_turn_count": sess.scene_turn_count,
        "settings": _j.loads(sess.settings_json or "{}"),
        "stats": _j.loads(cs.stats_json if cs else "{}"),
        "inventory": _j.loads(cs.inventory_json if cs else "[]"),
    }
```

- [ ] **Step 3: Add API methods in `sessions.ts`**

```typescript
debugState: (sessionId: number) =>
  api
    .get<{
      doom_score: number
      turn_count: number
      scene_turn_count: number
      settings: Record<string, unknown>
      stats: Record<string, number>
      inventory: string[]
    }>(`/sessions/${sessionId}/debug_state`)
    .then((r) => r.data),

patchDebugState: (
  sessionId: number,
  body: {
    doom_score?: number
    turn_count?: number
    scene_turn_count?: number
    stats_json?: string
    inventory_json?: string
  },
) => api.patch(`/sessions/${sessionId}/debug_state`, body).then((r) => r.data),
```

- [ ] **Step 4: Create `DebugPanel.vue`**

Create `frontend/src/components/game/DebugPanel.vue`:

```vue
<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { sessionsApi } from '@/api/sessions'
import { ElMessage } from 'element-plus'

const props = defineProps<{ sessionId: number }>()

interface DebugState {
  doom_score: number
  turn_count: number
  scene_turn_count: number
  settings: Record<string, unknown>
  stats: Record<string, number>
  inventory: string[]
}

const state = ref<DebugState | null>(null)
const saving = ref(false)

async function load() {
  try {
    state.value = await sessionsApi.debugState(props.sessionId)
  } catch (e: any) {
    ElMessage.error('加载调试状态失败: ' + (e.message ?? ''))
  }
}

async function saveDoom() {
  if (!state.value) return
  saving.value = true
  try {
    await sessionsApi.patchDebugState(props.sessionId, {
      doom_score: state.value.doom_score,
    })
    ElMessage.success('厄运值已更新')
  } catch (e: any) {
    ElMessage.error(e.message ?? '保存失败')
  } finally {
    saving.value = false
  }
}

async function saveStats() {
  if (!state.value) return
  saving.value = true
  try {
    await sessionsApi.patchDebugState(props.sessionId, {
      stats_json: JSON.stringify(state.value.stats),
      inventory_json: JSON.stringify(state.value.inventory),
    })
    ElMessage.success('数值已更新')
  } catch (e: any) {
    ElMessage.error(e.message ?? '保存失败')
  } finally {
    saving.value = false
  }
}

async function saveTurns() {
  if (!state.value) return
  saving.value = true
  try {
    await sessionsApi.patchDebugState(props.sessionId, {
      turn_count: state.value.turn_count,
      scene_turn_count: state.value.scene_turn_count,
    })
    ElMessage.success('回合数已更新')
  } catch (e: any) {
    ElMessage.error(e.message ?? '保存失败')
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="text-xs font-mono bg-yellow-50 border border-yellow-300 rounded p-3 space-y-3">
    <div class="flex items-center justify-between">
      <span class="font-bold text-yellow-800">🐛 Debug 数值编辑器</span>
      <button class="text-slate-400 hover:text-slate-600 text-xs" @click="load">↺ 刷新</button>
    </div>

    <template v-if="state">
      <!-- Doom score -->
      <div class="space-y-1">
        <div class="text-slate-600 font-medium">厄运值 (doom_score): {{ state.doom_score }}</div>
        <div class="flex gap-2 items-center">
          <el-slider
            v-model="state.doom_score"
            :min="0"
            :max="100"
            :step="5"
            size="small"
            class="flex-1"
          />
          <el-button size="small" :loading="saving" @click="saveDoom">保存</el-button>
        </div>
      </div>

      <!-- Turn counts -->
      <div class="space-y-1">
        <div class="text-slate-600 font-medium">回合计数</div>
        <div class="flex gap-2 items-center">
          <span class="text-slate-500 w-20">turn_count</span>
          <el-input-number v-model="state.turn_count" :min="0" size="small" controls-position="right" />
        </div>
        <div class="flex gap-2 items-center">
          <span class="text-slate-500 w-20">scene_turn</span>
          <el-input-number v-model="state.scene_turn_count" :min="0" size="small" controls-position="right" />
        </div>
        <el-button size="small" :loading="saving" @click="saveTurns">保存回合数</el-button>
      </div>

      <!-- PC stats -->
      <div class="space-y-1">
        <div class="text-slate-600 font-medium">PC 属性</div>
        <div
          v-for="(val, key) in state.stats"
          :key="key"
          class="flex gap-2 items-center"
        >
          <span class="text-slate-500 w-20">{{ key }}</span>
          <el-input-number
            v-model="state.stats[key]"
            size="small"
            controls-position="right"
          />
        </div>
        <el-button size="small" :loading="saving" @click="saveStats">保存属性</el-button>
      </div>

      <!-- Settings flags -->
      <div class="space-y-1">
        <div class="text-slate-600 font-medium">会话设置</div>
        <div v-for="(val, key) in state.settings" :key="key" class="text-slate-500">
          {{ key }}: <span class="text-slate-800">{{ JSON.stringify(val) }}</span>
        </div>
      </div>
    </template>

    <div v-else class="text-slate-400 italic">加载中…</div>
  </div>
</template>
```

- [ ] **Step 5: Add `DebugPanel` to `GameView.vue`**

Import the component:
```typescript
import DebugPanel from '@/components/game/DebugPanel.vue'
```

Import the debug store:
```typescript
import { useDebugStore } from '@/stores/debug'
const debugStore = useDebugStore()
```

In the right-side panel area (near `<StatePanel>`), add after it:

```html
<!-- Debug stats panel — only visible in debug mode -->
<DebugPanel
  v-if="debugStore.enabled"
  :session-id="sessionId"
  class="mt-3"
/>
```

- [ ] **Step 6: Build and verify**

```bash
cd /Users/norman/development/dzmm/frontend && npm run build 2>&1 | tail -5
```
Expected: `✓ built in X.XXs`

- [ ] **Step 7: Commit**

```bash
cd /Users/norman/development/dzmm && git add \
  backend/src/dzmm/api/routes_sessions/base.py \
  frontend/src/api/sessions.ts \
  frontend/src/components/game/DebugPanel.vue \
  frontend/src/views/GameView.vue
git commit -m "feat(debug): stats editor panel (doom/turns/PC stats) + PATCH /debug_state endpoint"
```

---

## Self-Review

**Spec coverage:**
- ✅ Issue 3: TTS speaker toggles in game page (narrator/PC/NPC)
- ✅ Issue 4: Debug button per turn → dialog with prompt + raw response
- ✅ Issue 5: Starting currency in wizard character prompt
- ✅ Issue 6: Location panel shows NPCs present (uses existing `current_location` data)
- ✅ Issue 8: Debug panel with doom/turn/PC stats + save

**Placeholder scan:** All code blocks are complete. No "TBD" or "add validation" placeholders.

**Type consistency:**
- `TtsSpeakerFilter` defined in Task 1 Step 2, used in Task 1 Step 3 ✅
- `Turn.msgId?: number` added in Task 2 Step 6; used in MessageList Step 9 ✅
- `DebugState` interface defined and used in `DebugPanel.vue` only ✅
- `patchDebugState` / `debugState` / `messageDebug` defined in Task 2/5 `sessions.ts` steps ✅

**Known constraint:** The debug prompt dialog shows "未记录" until the user enables debug mode in the session (which the `watch` in GameView auto-enables when Konami code is entered). For the CURRENT session that has already run turns without debug_mode, old turns will show no prompt — only new turns after enabling will have it captured.
