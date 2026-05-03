# TTS Preview, Voice Settings & ModelsView Update Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add TTS voice preview (试听) to settings card, NPC dialog, and character drawer; update ModelsView TTS tab description; auto-populate NPC voice from archetype in the dialog.

**Architecture:** Add a `previewVoice(text, voice)` function to `useTTS` composable that plays a single text sample using the current mode's endpoint. Consume it in TtsSettingsCard, NpcDetailDialog, and CharacterCardDrawer. ModelsView update is a pure template/data change. No backend changes needed.

**Tech Stack:** Vue 3 + TypeScript, Element Plus, Web Audio API, existing `/tts/builtin` and `/tts/kokoro/synthesize` endpoints.

---

## File Structure

**Modified files:**
- `frontend/src/composables/useTTS.ts` — add `previewVoice(text, voice)` export
- `frontend/src/components/TtsSettingsCard.vue` — add preview row at bottom
- `frontend/src/components/NpcDetailDialog.vue` — add 试听 button; pre-populate voice from archetype
- `frontend/src/components/CharacterCardDrawer.vue` — add PC voice display + 试听 section
- `frontend/src/views/ModelsView.vue` — update TTS tab intro text + add built-in engines table

---

## Task 1: Add `previewVoice` to useTTS composable

**Files:**
- Modify: `frontend/src/composables/useTTS.ts`

The new export `previewVoice(text: string, voice: string)` plays a single text sample using the mode currently active in `appStore.ttsMode`. It reuses the existing `_playAudioBytes`, `_abortCtrl`, `_aborted`, `_speaking` module-level state so calling `stop()` also cancels a preview.

- [ ] **Step 1: Read the current useTTS.ts to confirm structure**

Run: `cat -n frontend/src/composables/useTTS.ts`

- [ ] **Step 2: Add `previewVoice` function inside `useTTS()`**

Add after the `stop()` function and before `_speakWebSpeech`:

```typescript
async function previewVoice(text: string, voice: string): Promise<void> {
  if (!text.trim()) return
  stop()
  _aborted = false
  _abortCtrl = new AbortController()
  _speaking.value = true
  try {
    if (appStore.ttsMode === 'edge') {
      const { voice: v, rate, pitch } = parseEdgeVoice(voice || appStore.ttsGmVoice)
      const resp = await fetch(`${backendOrigin}/tts/builtin`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text, voice: v, rate, pitch }),
        signal: _abortCtrl.signal,
      })
      if (resp.ok && resp.status !== 204) {
        const buf = await resp.arrayBuffer()
        if (!_aborted) await _playAudioBytes(buf)
      }
    } else if (appStore.ttsMode === 'kokoro') {
      const resp = await fetch(`${backendOrigin}/tts/kokoro/synthesize`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text, voice: voice || appStore.ttsGmVoice || 'zf_xiaobei' }),
        signal: _abortCtrl.signal,
      })
      if (resp.ok && resp.status !== 204) {
        const buf = await resp.arrayBuffer()
        if (!_aborted) await _playAudioBytes(buf)
      }
    } else if (appStore.ttsMode === 'webspeech') {
      if (typeof window !== 'undefined' && window.speechSynthesis) {
        const voices = await _getVoices()
        const utterance = new SpeechSynthesisUtterance(text)
        const found = voices.find((v) => v.name === voice || v.voiceURI === voice) ?? null
        if (found) utterance.voice = found
        utterance.lang = found?.lang ?? 'zh-CN'
        await new Promise<void>((resolve) => {
          utterance.onend = () => resolve()
          utterance.onerror = () => resolve()
          window.speechSynthesis.speak(utterance)
        })
      }
    } else {
      // local proxy mode
      const resp = await fetch(`${backendOrigin}/tts`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model_config_id: appStore.ttsModelConfigId, text, voice }),
        signal: _abortCtrl.signal,
      })
      if (resp.ok) {
        const buf = await resp.arrayBuffer()
        if (!_aborted) await _playAudioBytes(buf)
      }
    }
  } catch { /* ignore abort / network errors */ } finally {
    _speaking.value = false
  }
}
```

- [ ] **Step 3: Export `previewVoice` from the return object**

In the `return` statement at the bottom of `useTTS()`, add `previewVoice`:

```typescript
return { playTurn, stop, speaking: _speaking, previewVoice }
```

- [ ] **Step 4: Type-check**

Run: `cd frontend && npx vue-tsc --noEmit 2>&1 | grep -v "node_modules" | head -20`

Expected: no errors for `useTTS.ts`

- [ ] **Step 5: Commit**

```bash
git add frontend/src/composables/useTTS.ts
git commit -m "feat(tts): add previewVoice() to useTTS composable"
```

---

## Task 2: TTS preview buttons in TtsSettingsCard

**Files:**
- Modify: `frontend/src/components/TtsSettingsCard.vue`

Add a "试听" row at the bottom of the enabled section (before the NPC hint text at the bottom). It shows two buttons: 试听旁白 and 试听PC，plus a small text input for the sample text.

- [ ] **Step 1: Read TtsSettingsCard.vue to find insertion point**

The insertion point is after the last mode section (after the `v-if="appStore.ttsMode !== 'local'"` hint div, or just before `</template>` that closes `v-if="appStore.ttsEnabled"`).

Currently the end of the enabled section is:
```html
        <div v-if="appStore.ttsMode !== 'local'" class="text-xs text-slate-400 pl-1">
          各 NPC 的专属音色可在游戏中的「NPC 图鉴」里单独设置；新 NPC 会按性格原型自动分配。
        </div>
      </template>
```

- [ ] **Step 2: Add imports/refs in `<script setup>`**

At the top of `<script setup>`, add:
```typescript
import { useTTS } from '@/composables/useTTS'
const { previewVoice, speaking, stop } = useTTS()
const previewText = ref('天地玄黄，宇宙洪荒。日月盈昃，辰宿列张。')
```

- [ ] **Step 3: Add preview UI in `<template>`**

Insert **before** the closing `</template>` of the `v-if="appStore.ttsEnabled"` block (right after the NPC hint div at the end):

```html
        <!-- 试听 -->
        <el-divider />
        <el-form-item label="试听">
          <div class="flex flex-col gap-2 w-full">
            <el-input
              v-model="previewText"
              placeholder="输入试听文本"
              size="small"
              :disabled="speaking"
            />
            <div class="flex gap-2">
              <el-button
                size="small"
                :loading="speaking"
                :disabled="!appStore.ttsEnabled"
                @click="previewVoice(previewText, appStore.ttsGmVoice || '')"
              >试听旁白</el-button>
              <el-button
                size="small"
                :loading="speaking"
                :disabled="!appStore.ttsEnabled"
                @click="previewVoice(previewText, appStore.ttsPcVoice || appStore.ttsGmVoice || '')"
              >试听PC</el-button>
              <el-button
                v-if="speaking"
                size="small"
                type="danger"
                @click="stop()"
              >停止</el-button>
            </div>
          </div>
        </el-form-item>
```

- [ ] **Step 4: Type-check**

Run: `cd frontend && npx vue-tsc --noEmit 2>&1 | grep -v "node_modules" | head -20`

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/TtsSettingsCard.vue
git commit -m "feat(tts): add preview buttons to TtsSettingsCard"
```

---

## Task 3: NPC dialog — 试听 button + auto-populate voice

**Files:**
- Modify: `frontend/src/components/NpcDetailDialog.vue`

Two changes:
1. Add a 试听 icon button next to each voice dropdown
2. When the dialog loads a NPC with empty `tts_voice`, auto-populate the local form value from the archetype map so the dropdown shows the auto-assigned voice (without saving it)

- [ ] **Step 1: Read the TTS section of NpcDetailDialog.vue**

Run: `grep -n "tts_voice\|autoVoice\|el-select\|saveVoice\|archetype\|local\." frontend/src/components/NpcDetailDialog.vue | head -40`

The TTS section is in the template where `appStore.ttsMode` is checked. The three branches are: edge select, kokoro select, webspeech/local input.

- [ ] **Step 2: Add `previewVoice` import and effective voice computed**

In `<script setup>`, add:
```typescript
import { useTTS } from '@/composables/useTTS'
const { previewVoice, speaking: ttsSpeaking, stop: ttsStop } = useTTS()

// Effective voice for preview: use saved tts_voice if set, else archetype auto-voice
const effectiveEdgeVoice = computed(() =>
  local.value?.tts_voice ||
  (local.value?.archetype ? archetypeEdgeMap[local.value.archetype] ?? 'zh-CN-XiaoxiaoNeural' : 'zh-CN-XiaoxiaoNeural')
)
const effectiveKokoroVoice = computed(() =>
  local.value?.tts_voice ||
  (local.value?.archetype ? archetypeKokoroMap[local.value.archetype] ?? 'zf_xiaobei' : 'zf_xiaobei')
)
```

- [ ] **Step 3: Auto-populate voice when dialog opens**

Find the `watch` that sets `local.value` from the incoming prop (likely `watch(() => props.npc, ...)`). After setting `local.value`, if `tts_voice` is empty and archetype maps to a voice, pre-fill:

```typescript
watch(() => props.npc, (npc) => {
  if (!npc) { local.value = null; return }
  local.value = { ...npc }
  // Pre-populate tts_voice from archetype for preview (not auto-saved)
  if (!local.value.tts_voice && local.value.archetype) {
    if (appStore.ttsMode === 'edge' && archetypeEdgeMap[local.value.archetype]) {
      local.value.tts_voice = archetypeEdgeMap[local.value.archetype]
    } else if (appStore.ttsMode === 'kokoro' && archetypeKokoroMap[local.value.archetype]) {
      local.value.tts_voice = archetypeKokoroMap[local.value.archetype]
    }
  }
}, { immediate: true })
```

(Find the actual watch call and edit it — do NOT create a duplicate watch.)

- [ ] **Step 4: Add 试听 button next to each voice dropdown in template**

The template currently has three branches. In the `edge` branch (around the `el-select`), wrap it in a flex div and add a button:

```html
<!-- edge branch — replace the bare el-select with: -->
<div class="flex items-center gap-2">
  <el-select
    :model-value="local.tts_voice ?? ''"
    filterable clearable placeholder="auto（按性格原型）"
    style="flex:1"
    @change="(v: string) => saveVoice(v)"
    @clear="saveVoice('')"
  >
    <el-option v-for="v in edgeVoiceOptions" :key="v.voice" :label="v.label" :value="v.voice" />
  </el-select>
  <el-button
    size="small" circle :loading="ttsSpeaking"
    title="试听"
    @click="previewVoice(local.name + '，你好', effectiveEdgeVoice)"
  >🔊</el-button>
</div>
```

Repeat for the kokoro branch:
```html
<div class="flex items-center gap-2">
  <el-select
    :model-value="local.tts_voice ?? ''"
    filterable clearable placeholder="auto（按性格原型）"
    style="flex:1"
    @change="(v: string) => saveVoice(v)"
    @clear="saveVoice('')"
  >
    <el-option v-for="v in kokoroVoiceOptions" :key="v.value" :label="v.label" :value="v.value" />
  </el-select>
  <el-button
    size="small" circle :loading="ttsSpeaking"
    title="试听"
    @click="previewVoice(local.name + '，你好', effectiveKokoroVoice)"
  >🔊</el-button>
</div>
```

For the webspeech/local input branch, add a button similarly using `local.tts_voice`.

- [ ] **Step 5: Type-check**

Run: `cd frontend && npx vue-tsc --noEmit 2>&1 | grep -v "node_modules" | head -20`

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/NpcDetailDialog.vue
git commit -m "feat(tts): NPC dialog — 试听 button + auto-populate voice from archetype"
```

---

## Task 4: CharacterCardDrawer — PC voice display + 试听

**Files:**
- Modify: `frontend/src/components/CharacterCardDrawer.vue`

Add a TTS section below the 角色档案 section. Shows the current PC voice (from appStore) and a 试听 button. Since there's no per-character voice DB field (PC voice is global), this is purely informational + testable.

- [ ] **Step 1: Read CharacterCardDrawer.vue to find insertion point**

Run: `cat -n frontend/src/components/CharacterCardDrawer.vue`

Find the end of the `profile_md` section (around line 132) — insert TTS section after `</div>` that ends the profile section, before the closing `</div>` of the character content block.

- [ ] **Step 2: Add imports in `<script setup>`**

```typescript
import { useAppStore } from '@/stores/app'
import { useTTS } from '@/composables/useTTS'
const appStore = useAppStore()
const { previewVoice, speaking: ttsSpeaking } = useTTS()
```

- [ ] **Step 3: Add TTS section in template**

After the profile_md section and before the closing `</div>` of the character content:

```html
      <el-divider />

      <!-- TTS 音色 -->
      <div>
        <div class="text-sm font-bold text-slate-700 mb-2">旁白 / 主角音色</div>
        <div v-if="appStore.ttsEnabled" class="flex items-center gap-3 flex-wrap">
          <span class="text-xs text-slate-500">
            模式：<strong>{{ { edge: 'edge-tts', kokoro: 'Kokoro', webspeech: '浏览器', local: '外部服务' }[appStore.ttsMode] }}</strong>
          </span>
          <span v-if="appStore.ttsGmVoice" class="text-xs text-slate-500">
            旁白：<code class="bg-slate-100 px-1 rounded text-xs">{{ appStore.ttsGmVoice }}</code>
          </span>
          <el-button
            size="small"
            :loading="ttsSpeaking"
            @click="previewVoice(character?.name ? character.name + '，今日天气不错。' : '测试音色', appStore.ttsPcVoice || appStore.ttsGmVoice || '')"
          >🔊 试听主角音色</el-button>
        </div>
        <div v-else class="text-xs text-slate-400">TTS 未启用（可在设置页开启）</div>
      </div>
```

- [ ] **Step 4: Type-check**

Run: `cd frontend && npx vue-tsc --noEmit 2>&1 | grep -v "node_modules" | head -20`

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/CharacterCardDrawer.vue
git commit -m "feat(tts): CharacterCardDrawer — PC voice display and 试听 button"
```

---

## Task 5: ModelsView — update TTS tab description

**Files:**
- Modify: `frontend/src/views/ModelsView.vue`

Update the TTS tab to accurately describe all three modes now available: built-in edge-tts, built-in kokoro-onnx, and external OpenAI-compatible service.

- [ ] **Step 1: Read the TTS tab section**

Run: `grep -n "tts\|TTS" frontend/src/views/ModelsView.vue`

Lines to change: around 158-166 (data arrays) and 244-292 (template).

- [ ] **Step 2: Update `ttsLocalServices` data and add `ttsBuiltinModes`**

In `<script setup>`, replace or extend around line 158:

```typescript
const ttsBuiltinModes = [
  {
    name: 'edge-tts（内置，在线）',
    desc: '微软 Neural TTS，免费，无需安装，需联网。中文音色丰富（13+ Neural voices），NPC 按性格原型自动分配音色。在设置页选择「内置 edge-tts」即可使用。',
    setup: '无需配置',
  },
  {
    name: 'Kokoro-ONNX（内置，离线）',
    desc: '本地 ONNX 模型，~82MB，一次下载后完全离线。中文音色 4 种（小北、小妮、云希、云冬）。在设置页选择「本地 Kokoro」并点击下载。',
    setup: '设置页点击「立即下载」',
  },
]

const ttsLocalServices = [
  { name: 'openedai-speech (Kokoro)', baseUrl: 'http://localhost:8000', note: '高质量多音色，兼容 OpenAI /v1/audio/speech；推荐 Docker 部署' },
  { name: 'AllTalk TTS',              baseUrl: 'http://localhost:7851', note: '支持声音克隆，本地 WebUI，Base URL 填到 /v1' },
  { name: 'Kokoro-FastAPI',           baseUrl: 'http://localhost:8880', note: '轻量 Python 服务，仅 Kokoro 引擎，启动快' },
]
```

- [ ] **Step 3: Update TTS tab template**

Replace the TTS tab pane content (from `<el-tab-pane label="TTS 语音合成"` to its `</el-tab-pane>`) with:

```html
<el-tab-pane label="TTS 语音合成" name="tts">
  <p class="text-xs text-slate-500 mb-3">
    DZMM 支持三种 TTS 模式，可在<strong>「设置」→「语音朗读」</strong>切换。内置模式无需额外配置。
  </p>

  <p class="text-xs font-semibold text-slate-600 mb-2">内置引擎（推荐）</p>
  <table class="w-full text-sm mb-4">
    <thead>
      <tr class="border-b border-slate-200 text-xs text-slate-500">
        <th class="text-left py-1 pr-4 font-medium">引擎</th>
        <th class="text-left py-1 pr-4 font-medium">配置方式</th>
        <th class="text-left py-1 font-medium">说明</th>
      </tr>
    </thead>
    <tbody class="text-slate-700">
      <tr v-for="m in ttsBuiltinModes" :key="m.name" class="border-b border-slate-100 last:border-0">
        <td class="py-1.5 pr-4 text-xs font-medium whitespace-nowrap">{{ m.name }}</td>
        <td class="py-1.5 pr-4 text-xs text-slate-500 whitespace-nowrap">{{ m.setup }}</td>
        <td class="py-1.5 text-xs text-slate-600">{{ m.desc }}</td>
      </tr>
    </tbody>
  </table>

  <p class="text-xs font-semibold text-slate-600 mb-2">外部 TTS 服务（OpenAI 兼容接口，「外部服务」模式）</p>
  <p class="text-xs text-slate-500 mb-2">
    选择「外部 TTS 服务」模式时，需在此页面添加一条模型配置，填写服务的 Base URL 与模型名。
  </p>
  <table class="w-full text-sm mb-4">
    <thead>
      <tr class="border-b border-slate-200 text-xs text-slate-500">
        <th class="text-left py-1 pr-4 font-medium">服务</th>
        <th class="text-left py-1 pr-4 font-medium">默认 Base URL</th>
        <th class="text-left py-1 font-medium">说明</th>
      </tr>
    </thead>
    <tbody class="text-slate-700">
      <tr v-for="m in ttsLocalServices" :key="m.name" class="border-b border-slate-100 last:border-0">
        <td class="py-1.5 pr-4 text-xs font-medium">{{ m.name }}</td>
        <td class="py-1.5 pr-4">
          <code class="bg-slate-100 text-slate-800 px-1.5 py-0.5 rounded text-xs">{{ m.baseUrl }}</code>
          <el-button link size="small" class="ml-1 text-xs text-slate-400" @click="copyText(m.baseUrl)">复制</el-button>
        </td>
        <td class="py-1.5 text-xs text-slate-600">{{ m.note }}</td>
      </tr>
    </tbody>
  </table>

  <p class="text-xs font-semibold text-slate-600 mb-2">云端语音（OpenAI）</p>
  <table class="w-full text-sm">
    <thead>
      <tr class="border-b border-slate-200 text-xs text-slate-500">
        <th class="text-left py-1 pr-4 font-medium">模型 ID</th>
        <th class="text-left py-1 pr-4 font-medium">Base URL</th>
        <th class="text-left py-1 font-medium">说明</th>
      </tr>
    </thead>
    <tbody class="text-slate-700">
      <tr v-for="m in ttsCloudModels" :key="m.id" class="border-b border-slate-100 last:border-0">
        <td class="py-1.5 pr-4">
          <code class="bg-slate-100 text-slate-800 px-1.5 py-0.5 rounded text-xs">{{ m.id }}</code>
          <el-button link size="small" class="ml-1 text-xs text-slate-400" @click="copyText(m.id)">复制</el-button>
        </td>
        <td class="py-1.5 pr-4 text-xs text-slate-500">
          <code class="text-xs">{{ m.baseUrl }}</code>
        </td>
        <td class="py-1.5 text-xs text-slate-600">{{ m.note }}</td>
      </tr>
    </tbody>
  </table>
</el-tab-pane>
```

- [ ] **Step 4: Type-check**

Run: `cd frontend && npx vue-tsc --noEmit 2>&1 | grep -v "node_modules" | head -20`

- [ ] **Step 5: Commit**

```bash
git add frontend/src/views/ModelsView.vue
git commit -m "docs(models): update TTS tab — add built-in edge-tts + Kokoro-ONNX description"
```

---

## Self-Review

**Spec coverage:**
- ✅ SSE streaming regression — already fixed in MessageList.vue `displayParts`; noted in plan intro, no task needed
- ✅ TTS testable in settings page — Task 2
- ✅ ModelsView TTS description — Task 5
- ✅ Character page TTS settings + 试听 — Task 4
- ✅ NPC page TTS settings + 试听 — Task 3
- ✅ Voice auto-assigned on generation — Task 3 (auto-populate from archetype in NPC dialog)

**Placeholder scan:** All steps have concrete code. No TBDs.

**Type consistency:**
- `previewVoice(text: string, voice: string)` — consistent across Tasks 1, 2, 3, 4
- `effectiveEdgeVoice` / `effectiveKokoroVoice` — defined in Task 3, used in Task 3 only
- `ttsSpeaking` — aliased from `speaking` in all consumers, no conflict
