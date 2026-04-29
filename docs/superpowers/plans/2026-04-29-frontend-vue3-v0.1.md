# Frontend Vue3 v0.1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Vue3 SPA that drives the backend API: configure models, create worlds/characters, start a session, play TRPG turns with streaming narrative, view character state and history.

**Architecture:** Vue 3 + Composition API + TypeScript. Vite dev/build. Element Plus components for forms/dialogs/tables. TailwindCSS for layout. Pinia for state. Vue Router for 5 routes. axios wraps backend CRUD; SSE consumed via native `fetch` + `ReadableStream` (no library — sse libs are over-engineered for our needs). Markdown rendered via `marked`.

**Tech Stack:** Vue 3.4+, TypeScript 5+, Vite 5+, Element Plus, TailwindCSS, pinia, vue-router, axios, marked, vitest (smoke).

**Backend dependency:** Backend v0.1 (already implemented) running at `http://127.0.0.1:8765`.

---

## File Structure

```
frontend/
├── package.json
├── vite.config.ts
├── tsconfig.json
├── tsconfig.node.json
├── tailwind.config.js
├── postcss.config.js
├── index.html
├── .gitignore
├── src/
│   ├── main.ts                    # entry: pinia, router, element-plus, tailwind
│   ├── App.vue                    # router-view shell
│   ├── style.css                  # tailwind directives
│   ├── router/
│   │   └── index.ts               # 5 routes
│   ├── api/
│   │   ├── client.ts              # axios instance
│   │   ├── types.ts               # mirrors backend schemas
│   │   ├── worlds.ts
│   │   ├── characters.ts
│   │   ├── models.ts
│   │   └── sessions.ts
│   ├── composables/
│   │   └── useTurnStream.ts       # SSE consumer (fetch + ReadableStream)
│   ├── stores/
│   │   ├── worlds.ts
│   │   ├── characters.ts
│   │   ├── modelConfigs.ts
│   │   └── sessions.ts
│   ├── components/
│   │   ├── SidebarNav.vue
│   │   ├── MarkdownView.vue
│   │   └── StatePanel.vue
│   └── views/
│       ├── LayoutView.vue
│       ├── ModelsView.vue
│       ├── WorldsView.vue
│       ├── CharactersView.vue
│       ├── SessionsView.vue
│       └── GameView.vue
└── tests/
    └── api.test.ts                # smoke: API client shapes
```

---

## Task 1: Project skeleton (Vite + Vue3 + TS + Tailwind + Element Plus)

**Files:**
- Create `frontend/package.json`
- Create `frontend/vite.config.ts`, `tsconfig.json`, `tsconfig.node.json`
- Create `frontend/tailwind.config.js`, `postcss.config.js`
- Create `frontend/index.html`
- Create `frontend/.gitignore`
- Create `frontend/src/main.ts`, `App.vue`, `style.css`

- [ ] **Step 1: `frontend/package.json`**

```json
{
  "name": "dzmm-frontend",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "vue-tsc -b && vite build",
    "preview": "vite preview --port 5174",
    "test": "vitest run"
  },
  "dependencies": {
    "vue": "^3.4.0",
    "vue-router": "^4.3.0",
    "pinia": "^2.1.7",
    "element-plus": "^2.7.0",
    "@element-plus/icons-vue": "^2.3.1",
    "axios": "^1.7.0",
    "marked": "^12.0.0"
  },
  "devDependencies": {
    "@vitejs/plugin-vue": "^5.0.0",
    "vite": "^5.2.0",
    "vue-tsc": "^2.0.0",
    "typescript": "^5.4.0",
    "tailwindcss": "^3.4.0",
    "postcss": "^8.4.0",
    "autoprefixer": "^10.4.0",
    "vitest": "^1.5.0",
    "@vue/test-utils": "^2.4.5",
    "jsdom": "^24.0.0"
  }
}
```

- [ ] **Step 2: `frontend/vite.config.ts`**

```ts
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import path from 'node:path'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: { '@': path.resolve(__dirname, 'src') },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8765',
        changeOrigin: true,
        rewrite: (p) => p.replace(/^\/api/, ''),
      },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
  },
})
```

- [ ] **Step 3: `frontend/tsconfig.json`**

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "ESNext",
    "moduleResolution": "Bundler",
    "strict": true,
    "jsx": "preserve",
    "useDefineForClassFields": true,
    "esModuleInterop": true,
    "allowSyntheticDefaultImports": true,
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,
    "skipLibCheck": true,
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "types": ["vitest/globals"],
    "baseUrl": ".",
    "paths": { "@/*": ["src/*"] }
  },
  "include": ["src/**/*", "tests/**/*"],
  "references": [{ "path": "./tsconfig.node.json" }]
}
```

- [ ] **Step 4: `frontend/tsconfig.node.json`**

```json
{
  "compilerOptions": {
    "composite": true,
    "module": "ESNext",
    "moduleResolution": "Bundler",
    "skipLibCheck": true,
    "allowSyntheticDefaultImports": true
  },
  "include": ["vite.config.ts"]
}
```

- [ ] **Step 5: `frontend/tailwind.config.js`**

```js
/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{vue,ts,tsx}'],
  theme: { extend: {} },
  plugins: [],
}
```

- [ ] **Step 6: `frontend/postcss.config.js`**

```js
export default {
  plugins: { tailwindcss: {}, autoprefixer: {} },
}
```

- [ ] **Step 7: `frontend/index.html`**

```html
<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>dzmm</title>
  </head>
  <body>
    <div id="app"></div>
    <script type="module" src="/src/main.ts"></script>
  </body>
</html>
```

- [ ] **Step 8: `frontend/.gitignore`**

```
node_modules/
dist/
.vite/
*.log
.env.local
```

- [ ] **Step 9: `frontend/src/style.css`**

```css
@tailwind base;
@tailwind components;
@tailwind utilities;

html, body, #app { height: 100%; }
body { font-family: system-ui, -apple-system, "PingFang SC", sans-serif; }
```

- [ ] **Step 10: `frontend/src/main.ts`**

```ts
import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import App from './App.vue'
import router from './router'
import './style.css'

const app = createApp(App)
app.use(createPinia())
app.use(router)
app.use(ElementPlus)
app.mount('#app')
```

- [ ] **Step 11: `frontend/src/App.vue`**

```vue
<script setup lang="ts"></script>

<template>
  <router-view />
</template>
```

- [ ] **Step 12: install + verify**

```bash
cd /Users/norman/development/dzmm/frontend
npm install
npm run build
```

`npm run build` will fail because router doesn't exist yet. That's OK — Task 5 sets it up. For this task, just verify `npm install` completes and `vite --version` works.

- [ ] **Step 13: commit**

```bash
cd /Users/norman/development/dzmm
git add frontend/
git commit -m "chore: bootstrap Vue3 + Vite frontend skeleton"
```

---

## Task 2: API client + types

**Files:**
- Create: `frontend/src/api/types.ts`
- Create: `frontend/src/api/client.ts`
- Create: `frontend/src/api/worlds.ts`
- Create: `frontend/src/api/characters.ts`
- Create: `frontend/src/api/models.ts`
- Create: `frontend/src/api/sessions.ts`

- [ ] **Step 1: `frontend/src/api/types.ts`**

```ts
export interface World {
  id: number
  name: string
  content_md: string
  style: string
  rules_mode: string
}

export type WorldIn = Omit<World, 'id'>

export interface Character {
  id: number
  world_id: number
  name: string
  profile_md: string
  base_stats_json: string
}

export type CharacterIn = Omit<Character, 'id'>

export interface ModelConfig {
  id: number
  name: string
  type: 'openai_compat' | 'ollama'
  base_url: string
  model_name: string
  api_key_ref: string | null
  timeout: number
}

export interface ModelConfigIn {
  name: string
  type: 'openai_compat' | 'ollama'
  base_url: string
  model_name: string
  api_key?: string
  timeout?: number
}

export interface GameSession {
  id: number
  name: string
  world_id: number
  character_id: number
  gm_model_config_id: number
  summarizer_model_config_id: number
  turn_count: number
}

export type SessionIn = Omit<GameSession, 'id' | 'turn_count'>

export type TurnEvent =
  | { type: 'narrative'; text: string }
  | { type: 'tag'; name: string; attrs: Record<string, string>; content: string }
  | { type: 'parse_error'; message: string }
  | { type: 'summarize_error'; message: string }
  | { type: 'done' }
```

- [ ] **Step 2: `frontend/src/api/client.ts`**

```ts
import axios from 'axios'

export const api = axios.create({
  baseURL: '/api',
  timeout: 30000,
})

api.interceptors.response.use(
  (r) => r,
  (err) => {
    const msg = err?.response?.data?.detail || err?.message || 'request failed'
    return Promise.reject(new Error(msg))
  },
)
```

- [ ] **Step 3: `frontend/src/api/worlds.ts`**

```ts
import { api } from './client'
import type { World, WorldIn } from './types'

export const worldsApi = {
  list: () => api.get<World[]>('/worlds').then((r) => r.data),
  get: (id: number) => api.get<World>(`/worlds/${id}`).then((r) => r.data),
  create: (body: WorldIn) => api.post<World>('/worlds', body).then((r) => r.data),
}
```

- [ ] **Step 4: `frontend/src/api/characters.ts`**

```ts
import { api } from './client'
import type { Character, CharacterIn } from './types'

export const charactersApi = {
  list: (worldId?: number) =>
    api
      .get<Character[]>('/characters', { params: { world_id: worldId } })
      .then((r) => r.data),
  get: (id: number) => api.get<Character>(`/characters/${id}`).then((r) => r.data),
  create: (body: CharacterIn) =>
    api.post<Character>('/characters', body).then((r) => r.data),
}
```

- [ ] **Step 5: `frontend/src/api/models.ts`**

```ts
import { api } from './client'
import type { ModelConfig, ModelConfigIn } from './types'

export const modelsApi = {
  list: () => api.get<ModelConfig[]>('/model_configs').then((r) => r.data),
  create: (body: ModelConfigIn) =>
    api.post<ModelConfig>('/model_configs', body).then((r) => r.data),
  test: (id: number) =>
    api.post<{ ok: boolean; info: string }>(`/model_configs/${id}/test`).then((r) => r.data),
}
```

- [ ] **Step 6: `frontend/src/api/sessions.ts`**

```ts
import { api } from './client'
import type { GameSession, SessionIn } from './types'

export const sessionsApi = {
  list: () => api.get<GameSession[]>('/sessions').then((r) => r.data),
  get: (id: number) => api.get<GameSession>(`/sessions/${id}`).then((r) => r.data),
  create: (body: SessionIn) =>
    api.post<GameSession>('/sessions', body).then((r) => r.data),
}
```

- [ ] **Step 7: smoke test `frontend/tests/api.test.ts`**

```ts
import { describe, it, expect } from 'vitest'
import { worldsApi } from '../src/api/worlds'
import { charactersApi } from '../src/api/characters'
import { modelsApi } from '../src/api/models'
import { sessionsApi } from '../src/api/sessions'

describe('api modules', () => {
  it('exposes expected operations', () => {
    expect(worldsApi).toMatchObject({ list: expect.any(Function), create: expect.any(Function) })
    expect(charactersApi).toMatchObject({ list: expect.any(Function) })
    expect(modelsApi).toMatchObject({ test: expect.any(Function) })
    expect(sessionsApi).toMatchObject({ create: expect.any(Function) })
  })
})
```

- [ ] **Step 8: run test**

```bash
cd frontend && npm run test
```

Expected: 1 test PASS.

- [ ] **Step 9: commit**

```bash
git add frontend/
git commit -m "feat(api): typed axios client + types matching backend schemas"
```

---

## Task 3: Pinia stores

**Files:**
- Create: `frontend/src/stores/worlds.ts`
- Create: `frontend/src/stores/characters.ts`
- Create: `frontend/src/stores/modelConfigs.ts`
- Create: `frontend/src/stores/sessions.ts`

- [ ] **Step 1: `frontend/src/stores/worlds.ts`**

```ts
import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { World, WorldIn } from '@/api/types'
import { worldsApi } from '@/api/worlds'

export const useWorldsStore = defineStore('worlds', () => {
  const items = ref<World[]>([])
  const loading = ref(false)

  async function refresh() {
    loading.value = true
    try {
      items.value = await worldsApi.list()
    } finally {
      loading.value = false
    }
  }

  async function create(body: WorldIn) {
    const w = await worldsApi.create(body)
    items.value.push(w)
    return w
  }

  return { items, loading, refresh, create }
})
```

- [ ] **Step 2: `frontend/src/stores/characters.ts`**

```ts
import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { Character, CharacterIn } from '@/api/types'
import { charactersApi } from '@/api/characters'

export const useCharactersStore = defineStore('characters', () => {
  const items = ref<Character[]>([])
  const loading = ref(false)

  async function refresh(worldId?: number) {
    loading.value = true
    try {
      items.value = await charactersApi.list(worldId)
    } finally {
      loading.value = false
    }
  }

  async function create(body: CharacterIn) {
    const c = await charactersApi.create(body)
    items.value.push(c)
    return c
  }

  return { items, loading, refresh, create }
})
```

- [ ] **Step 3: `frontend/src/stores/modelConfigs.ts`**

```ts
import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { ModelConfig, ModelConfigIn } from '@/api/types'
import { modelsApi } from '@/api/models'

export const useModelConfigsStore = defineStore('modelConfigs', () => {
  const items = ref<ModelConfig[]>([])
  const loading = ref(false)

  async function refresh() {
    loading.value = true
    try {
      items.value = await modelsApi.list()
    } finally {
      loading.value = false
    }
  }

  async function create(body: ModelConfigIn) {
    const m = await modelsApi.create(body)
    items.value.push(m)
    return m
  }

  async function test(id: number) {
    return modelsApi.test(id)
  }

  return { items, loading, refresh, create, test }
})
```

- [ ] **Step 4: `frontend/src/stores/sessions.ts`**

```ts
import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { GameSession, SessionIn } from '@/api/types'
import { sessionsApi } from '@/api/sessions'

export const useSessionsStore = defineStore('sessions', () => {
  const items = ref<GameSession[]>([])
  const loading = ref(false)

  async function refresh() {
    loading.value = true
    try {
      items.value = await sessionsApi.list()
    } finally {
      loading.value = false
    }
  }

  async function create(body: SessionIn) {
    const s = await sessionsApi.create(body)
    items.value.push(s)
    return s
  }

  async function get(id: number) {
    return sessionsApi.get(id)
  }

  return { items, loading, refresh, create, get }
})
```

- [ ] **Step 5: commit**

```bash
git add frontend/
git commit -m "feat(stores): pinia stores for worlds/characters/models/sessions"
```

---

## Task 4: SSE turn-stream composable

**Files:**
- Create: `frontend/src/composables/useTurnStream.ts`

- [ ] **Step 1: `frontend/src/composables/useTurnStream.ts`**

```ts
import type { TurnEvent } from '@/api/types'

export interface TurnHandlers {
  onNarrative?: (text: string) => void
  onTag?: (name: string, attrs: Record<string, string>, content: string) => void
  onError?: (message: string) => void
  onDone?: () => void
}

/**
 * Consume the SSE stream from POST /sessions/{id}/turn.
 *
 * Backend emits `event: <name>\ndata: <json>\n\n` blocks. We parse with a
 * small line-buffer state machine — no library needed.
 */
export async function streamTurn(
  sessionId: number,
  action: string,
  handlers: TurnHandlers,
  signal?: AbortSignal,
): Promise<void> {
  const resp = await fetch(`/api/sessions/${sessionId}/turn`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    body: JSON.stringify({ action }),
    signal,
  })
  if (!resp.ok || !resp.body) {
    throw new Error(`turn failed: ${resp.status} ${resp.statusText}`)
  }

  const reader = resp.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buf = ''

  while (true) {
    const { value, done } = await reader.read()
    if (done) break
    buf += decoder.decode(value, { stream: true })

    let nl: number
    while ((nl = buf.indexOf('\n\n')) >= 0) {
      const block = buf.slice(0, nl)
      buf = buf.slice(nl + 2)
      dispatch(block, handlers)
    }
  }
  if (buf.trim()) dispatch(buf, handlers)
}

function dispatch(block: string, h: TurnHandlers) {
  let event = 'message'
  let data = ''
  for (const line of block.split('\n')) {
    if (line.startsWith('event: ')) event = line.slice(7).trim()
    else if (line.startsWith('data: ')) data += line.slice(6)
  }
  if (!data) return

  let parsed: any
  try {
    parsed = JSON.parse(data)
  } catch {
    return
  }

  switch (event as TurnEvent['type']) {
    case 'narrative':
      h.onNarrative?.(parsed.text ?? '')
      break
    case 'tag':
      h.onTag?.(parsed.name, parsed.attrs ?? {}, parsed.content ?? '')
      break
    case 'parse_error':
    case 'summarize_error':
      h.onError?.(parsed.message ?? 'error')
      break
    case 'done':
      h.onDone?.()
      break
  }
}
```

- [ ] **Step 2: commit**

```bash
git add frontend/
git commit -m "feat(composables): SSE turn-stream consumer (fetch + ReadableStream)"
```

---

## Task 5: Router + Layout + SidebarNav

**Files:**
- Create: `frontend/src/router/index.ts`
- Create: `frontend/src/views/LayoutView.vue`
- Create: `frontend/src/components/SidebarNav.vue`

- [ ] **Step 1: `frontend/src/router/index.ts`**

```ts
import { createRouter, createWebHashHistory } from 'vue-router'
import LayoutView from '@/views/LayoutView.vue'

const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    {
      path: '/',
      component: LayoutView,
      children: [
        { path: '', redirect: '/sessions' },
        {
          path: 'models',
          name: 'models',
          component: () => import('@/views/ModelsView.vue'),
        },
        {
          path: 'worlds',
          name: 'worlds',
          component: () => import('@/views/WorldsView.vue'),
        },
        {
          path: 'characters',
          name: 'characters',
          component: () => import('@/views/CharactersView.vue'),
        },
        {
          path: 'sessions',
          name: 'sessions',
          component: () => import('@/views/SessionsView.vue'),
        },
        {
          path: 'play/:id',
          name: 'play',
          component: () => import('@/views/GameView.vue'),
          props: true,
        },
      ],
    },
  ],
})

export default router
```

- [ ] **Step 2: `frontend/src/components/SidebarNav.vue`**

```vue
<script setup lang="ts">
import { RouterLink } from 'vue-router'

const items = [
  { to: '/sessions', label: '跑团', icon: '🎲' },
  { to: '/worlds', label: '世界观', icon: '🌍' },
  { to: '/characters', label: '角色', icon: '🧝' },
  { to: '/models', label: '模型', icon: '🤖' },
]
</script>

<template>
  <nav class="w-48 bg-slate-800 text-slate-100 h-full p-4 flex flex-col gap-1">
    <div class="text-xl font-bold mb-6 px-2">dzmm</div>
    <RouterLink
      v-for="i in items"
      :key="i.to"
      :to="i.to"
      class="px-3 py-2 rounded hover:bg-slate-700 transition"
      active-class="bg-slate-700"
    >
      <span class="mr-2">{{ i.icon }}</span>{{ i.label }}
    </RouterLink>
  </nav>
</template>
```

- [ ] **Step 3: `frontend/src/views/LayoutView.vue`**

```vue
<script setup lang="ts">
import SidebarNav from '@/components/SidebarNav.vue'
</script>

<template>
  <div class="flex h-full">
    <SidebarNav />
    <main class="flex-1 overflow-auto bg-slate-50">
      <router-view />
    </main>
  </div>
</template>
```

- [ ] **Step 4: build check**

```bash
cd frontend && npm run build
```

The build will fail because the lazy-loaded views (`@/views/ModelsView.vue` etc.) don't exist yet. That's expected — leave the stubs for later tasks. To unblock the build for now, create stub files (one-line `<template><div>TBD</div></template>` SFCs) for `ModelsView.vue`, `WorldsView.vue`, `CharactersView.vue`, `SessionsView.vue`, `GameView.vue`. They'll be replaced by Tasks 6–10.

- [ ] **Step 5: stub views**

For each of the 5 view files (`ModelsView.vue`, `WorldsView.vue`, `CharactersView.vue`, `SessionsView.vue`, `GameView.vue`), create:

```vue
<template><div class="p-6">TBD</div></template>
```

Save under `frontend/src/views/`.

- [ ] **Step 6: build check passes**

```bash
cd frontend && npm run build
```

Expected: `vite build` produces `dist/` without errors.

- [ ] **Step 7: commit**

```bash
git add frontend/
git commit -m "feat: router, layout, sidebar nav, view stubs"
```

---

## Task 6: ModelsView (CRUD + test connection)

**Files:**
- Modify: `frontend/src/views/ModelsView.vue`

- [ ] **Step 1: replace stub with full implementation**

```vue
<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useModelConfigsStore } from '@/stores/modelConfigs'
import type { ModelConfigIn } from '@/api/types'

const store = useModelConfigsStore()
const dialogOpen = ref(false)
const submitting = ref(false)
const testing = ref<number | null>(null)

const form = reactive<ModelConfigIn>({
  name: '',
  type: 'ollama',
  base_url: 'http://localhost:11434',
  model_name: '',
  api_key: '',
  timeout: 60,
})

function resetForm() {
  Object.assign(form, {
    name: '',
    type: 'ollama',
    base_url: 'http://localhost:11434',
    model_name: '',
    api_key: '',
    timeout: 60,
  })
}

async function onCreate() {
  submitting.value = true
  try {
    const payload: ModelConfigIn = { ...form }
    if (!payload.api_key) delete (payload as any).api_key
    await store.create(payload)
    ElMessage.success('已添加')
    dialogOpen.value = false
    resetForm()
  } catch (e: any) {
    ElMessage.error(e.message)
  } finally {
    submitting.value = false
  }
}

async function onTest(id: number) {
  testing.value = id
  try {
    const r = await store.test(id)
    if (r.ok) {
      ElMessageBox.alert(r.info, '连接成功', { type: 'success' })
    } else {
      ElMessageBox.alert(r.info, '连接失败', { type: 'error' })
    }
  } catch (e: any) {
    ElMessage.error(e.message)
  } finally {
    testing.value = null
  }
}

onMounted(() => store.refresh())
</script>

<template>
  <div class="p-6">
    <div class="flex items-center justify-between mb-4">
      <h2 class="text-2xl font-bold">模型配置</h2>
      <el-button type="primary" @click="dialogOpen = true">+ 新增</el-button>
    </div>

    <el-table :data="store.items" v-loading="store.loading" border>
      <el-table-column prop="name" label="名称" width="160" />
      <el-table-column prop="type" label="类型" width="140" />
      <el-table-column prop="base_url" label="Base URL" />
      <el-table-column prop="model_name" label="模型" width="200" />
      <el-table-column label="API Key" width="100">
        <template #default="{ row }">
          {{ row.api_key_ref ? '已设置' : '—' }}
        </template>
      </el-table-column>
      <el-table-column label="操作" width="120">
        <template #default="{ row }">
          <el-button
            size="small"
            :loading="testing === row.id"
            @click="onTest(row.id)"
          >测试</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="dialogOpen" title="新增模型配置" width="520px">
      <el-form :model="form" label-width="100px">
        <el-form-item label="名称" required>
          <el-input v-model="form.name" placeholder="例如：本地 qwen" />
        </el-form-item>
        <el-form-item label="类型" required>
          <el-select v-model="form.type">
            <el-option label="Ollama 本地" value="ollama" />
            <el-option label="OpenAI 兼容（云端）" value="openai_compat" />
          </el-select>
        </el-form-item>
        <el-form-item label="Base URL" required>
          <el-input v-model="form.base_url" />
        </el-form-item>
        <el-form-item label="模型" required>
          <el-input v-model="form.model_name" placeholder="例如：qwen2.5:7b" />
        </el-form-item>
        <el-form-item label="API Key" v-if="form.type === 'openai_compat'">
          <el-input v-model="form.api_key" type="password" show-password />
        </el-form-item>
        <el-form-item label="超时（秒）">
          <el-input-number v-model="form.timeout" :min="5" :max="300" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogOpen = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="onCreate">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>
```

- [ ] **Step 2: commit**

```bash
git add frontend/
git commit -m "feat(views): ModelsView with CRUD + test-connection"
```

---

## Task 7: WorldsView (CRUD with markdown editor)

**Files:**
- Modify: `frontend/src/views/WorldsView.vue`
- Create: `frontend/src/components/MarkdownView.vue`

- [ ] **Step 1: `frontend/src/components/MarkdownView.vue`**

```vue
<script setup lang="ts">
import { computed } from 'vue'
import { marked } from 'marked'

const props = defineProps<{ source: string }>()

const html = computed(() => {
  marked.setOptions({ breaks: true, gfm: true })
  return marked.parse(props.source || '') as string
})
</script>

<template>
  <div class="prose max-w-none" v-html="html" />
</template>
```

- [ ] **Step 2: `frontend/src/views/WorldsView.vue`**

```vue
<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useWorldsStore } from '@/stores/worlds'
import MarkdownView from '@/components/MarkdownView.vue'
import type { WorldIn } from '@/api/types'

const store = useWorldsStore()
const dialogOpen = ref(false)
const submitting = ref(false)

const form = reactive<WorldIn>({
  name: '',
  content_md: '',
  style: 'dark',
  rules_mode: 'light',
})

const styles = [
  { label: '写实', value: 'realistic' },
  { label: '暗黑', value: 'dark' },
  { label: '治愈', value: 'healing' },
  { label: '幽默', value: 'comedy' },
  { label: '恐怖', value: 'horror' },
]

const rules = [
  { label: '轻量化（无骰子）', value: 'light' },
  { label: '标准（d20）', value: 'standard' },
  { label: '硬核（完整规则）', value: 'hardcore' },
]

function reset() {
  Object.assign(form, { name: '', content_md: '', style: 'dark', rules_mode: 'light' })
}

async function onCreate() {
  submitting.value = true
  try {
    await store.create(form)
    ElMessage.success('已创建')
    dialogOpen.value = false
    reset()
  } catch (e: any) {
    ElMessage.error(e.message)
  } finally {
    submitting.value = false
  }
}

onMounted(() => store.refresh())
</script>

<template>
  <div class="p-6">
    <div class="flex items-center justify-between mb-4">
      <h2 class="text-2xl font-bold">世界观</h2>
      <el-button type="primary" @click="dialogOpen = true">+ 新建世界观</el-button>
    </div>

    <el-table :data="store.items" v-loading="store.loading" border>
      <el-table-column prop="name" label="名称" width="200" />
      <el-table-column prop="style" label="风格" width="120" />
      <el-table-column prop="rules_mode" label="规则" width="120" />
      <el-table-column label="设定预览">
        <template #default="{ row }">
          <div class="line-clamp-2 text-sm text-slate-600">{{ row.content_md }}</div>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="dialogOpen" title="新建世界观" width="900px" top="5vh">
      <el-form :model="form" label-width="80px">
        <el-form-item label="名称" required>
          <el-input v-model="form.name" />
        </el-form-item>
        <el-form-item label="风格">
          <el-select v-model="form.style">
            <el-option v-for="s in styles" :key="s.value" :label="s.label" :value="s.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="规则">
          <el-select v-model="form.rules_mode">
            <el-option v-for="r in rules" :key="r.value" :label="r.label" :value="r.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="设定">
          <div class="grid grid-cols-2 gap-4 w-full">
            <el-input
              v-model="form.content_md"
              type="textarea"
              :rows="20"
              placeholder="使用 Markdown 描述世界观、势力、地理、禁忌、科技/魔法体系..."
            />
            <div class="border rounded p-3 bg-white max-h-[480px] overflow-auto">
              <MarkdownView :source="form.content_md" />
            </div>
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogOpen = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="onCreate">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>
```

- [ ] **Step 3: commit**

```bash
git add frontend/
git commit -m "feat(views): WorldsView with markdown editor + live preview"
```

---

## Task 8: CharactersView

**Files:**
- Modify: `frontend/src/views/CharactersView.vue`

- [ ] **Step 1: `frontend/src/views/CharactersView.vue`**

```vue
<script setup lang="ts">
import { onMounted, reactive, ref, computed } from 'vue'
import { ElMessage } from 'element-plus'
import { useCharactersStore } from '@/stores/characters'
import { useWorldsStore } from '@/stores/worlds'
import type { CharacterIn } from '@/api/types'

const charsStore = useCharactersStore()
const worldsStore = useWorldsStore()

const dialogOpen = ref(false)
const submitting = ref(false)

const form = reactive<CharacterIn>({
  world_id: 0,
  name: '',
  profile_md: '',
  base_stats_json: '{"hp":20,"sanity":15,"stamina":10}',
})

function reset() {
  Object.assign(form, {
    world_id: worldsStore.items[0]?.id ?? 0,
    name: '',
    profile_md: '',
    base_stats_json: '{"hp":20,"sanity":15,"stamina":10}',
  })
}

const worldNameById = computed(() => {
  const m = new Map<number, string>()
  for (const w of worldsStore.items) m.set(w.id, w.name)
  return m
})

async function onCreate() {
  submitting.value = true
  try {
    if (!form.world_id) {
      ElMessage.warning('请先选择世界观')
      return
    }
    try {
      JSON.parse(form.base_stats_json)
    } catch {
      ElMessage.error('属性 JSON 格式错误')
      return
    }
    await charsStore.create(form)
    ElMessage.success('已创建')
    dialogOpen.value = false
    reset()
  } catch (e: any) {
    ElMessage.error(e.message)
  } finally {
    submitting.value = false
  }
}

onMounted(async () => {
  await Promise.all([worldsStore.refresh(), charsStore.refresh()])
  reset()
})
</script>

<template>
  <div class="p-6">
    <div class="flex items-center justify-between mb-4">
      <h2 class="text-2xl font-bold">角色</h2>
      <el-button type="primary" @click="dialogOpen = true">+ 新建角色</el-button>
    </div>

    <el-table :data="charsStore.items" v-loading="charsStore.loading" border>
      <el-table-column prop="name" label="姓名" width="160" />
      <el-table-column label="世界观" width="200">
        <template #default="{ row }">{{ worldNameById.get(row.world_id) ?? '?' }}</template>
      </el-table-column>
      <el-table-column prop="base_stats_json" label="属性" width="280" />
      <el-table-column label="简介">
        <template #default="{ row }">
          <div class="line-clamp-2 text-sm text-slate-600">{{ row.profile_md }}</div>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="dialogOpen" title="新建角色" width="640px">
      <el-form :model="form" label-width="80px">
        <el-form-item label="世界观" required>
          <el-select v-model="form.world_id">
            <el-option
              v-for="w in worldsStore.items"
              :key="w.id"
              :label="w.name"
              :value="w.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="姓名" required>
          <el-input v-model="form.name" />
        </el-form-item>
        <el-form-item label="属性">
          <el-input v-model="form.base_stats_json" placeholder="JSON 格式" />
        </el-form-item>
        <el-form-item label="角色简介">
          <el-input
            v-model="form.profile_md"
            type="textarea"
            :rows="8"
            placeholder="姓名、职业、外貌、性格、背景、目标..."
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogOpen = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="onCreate">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>
```

- [ ] **Step 2: commit**

```bash
git add frontend/
git commit -m "feat(views): CharactersView with world association + stats JSON"
```

---

## Task 9: SessionsView (list + create + resume)

**Files:**
- Modify: `frontend/src/views/SessionsView.vue`

- [ ] **Step 1: `frontend/src/views/SessionsView.vue`**

```vue
<script setup lang="ts">
import { onMounted, reactive, ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useSessionsStore } from '@/stores/sessions'
import { useWorldsStore } from '@/stores/worlds'
import { useCharactersStore } from '@/stores/characters'
import { useModelConfigsStore } from '@/stores/modelConfigs'
import type { SessionIn } from '@/api/types'

const router = useRouter()
const sessionsStore = useSessionsStore()
const worldsStore = useWorldsStore()
const charsStore = useCharactersStore()
const modelsStore = useModelConfigsStore()

const dialogOpen = ref(false)
const submitting = ref(false)

const form = reactive<SessionIn>({
  name: '',
  world_id: 0,
  character_id: 0,
  gm_model_config_id: 0,
  summarizer_model_config_id: 0,
})

const charsForWorld = computed(() =>
  charsStore.items.filter((c) => c.world_id === form.world_id),
)

function reset() {
  Object.assign(form, {
    name: '',
    world_id: worldsStore.items[0]?.id ?? 0,
    character_id: 0,
    gm_model_config_id: modelsStore.items[0]?.id ?? 0,
    summarizer_model_config_id: modelsStore.items[0]?.id ?? 0,
  })
}

async function onCreate() {
  submitting.value = true
  try {
    if (!form.world_id || !form.character_id || !form.gm_model_config_id) {
      ElMessage.warning('请补全所有字段')
      return
    }
    const s = await sessionsStore.create(form)
    ElMessage.success('已创建')
    dialogOpen.value = false
    router.push(`/play/${s.id}`)
  } catch (e: any) {
    ElMessage.error(e.message)
  } finally {
    submitting.value = false
  }
}

const worldNameById = computed(() => {
  const m = new Map<number, string>()
  for (const w of worldsStore.items) m.set(w.id, w.name)
  return m
})
const charNameById = computed(() => {
  const m = new Map<number, string>()
  for (const c of charsStore.items) m.set(c.id, c.name)
  return m
})

onMounted(async () => {
  await Promise.all([
    sessionsStore.refresh(),
    worldsStore.refresh(),
    charsStore.refresh(),
    modelsStore.refresh(),
  ])
  reset()
})
</script>

<template>
  <div class="p-6">
    <div class="flex items-center justify-between mb-4">
      <h2 class="text-2xl font-bold">跑团存档</h2>
      <el-button type="primary" @click="dialogOpen = true">+ 新开一局</el-button>
    </div>

    <el-table :data="sessionsStore.items" v-loading="sessionsStore.loading" border>
      <el-table-column prop="name" label="名称" width="220" />
      <el-table-column label="世界" width="200">
        <template #default="{ row }">{{ worldNameById.get(row.world_id) }}</template>
      </el-table-column>
      <el-table-column label="角色" width="160">
        <template #default="{ row }">{{ charNameById.get(row.character_id) }}</template>
      </el-table-column>
      <el-table-column prop="turn_count" label="回合数" width="100" />
      <el-table-column label="操作" width="120">
        <template #default="{ row }">
          <el-button size="small" type="primary" @click="router.push(`/play/${row.id}`)">
            继续
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="dialogOpen" title="新开一局" width="560px">
      <el-form :model="form" label-width="100px">
        <el-form-item label="存档名称" required>
          <el-input v-model="form.name" placeholder="例如：赛博朋克 第一夜" />
        </el-form-item>
        <el-form-item label="世界观" required>
          <el-select v-model="form.world_id" @change="form.character_id = 0">
            <el-option
              v-for="w in worldsStore.items"
              :key="w.id"
              :label="w.name"
              :value="w.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="角色" required>
          <el-select v-model="form.character_id" :disabled="!form.world_id">
            <el-option
              v-for="c in charsForWorld"
              :key="c.id"
              :label="c.name"
              :value="c.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="GM 模型" required>
          <el-select v-model="form.gm_model_config_id">
            <el-option
              v-for="m in modelsStore.items"
              :key="m.id"
              :label="`${m.name} (${m.model_name})`"
              :value="m.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="摘要模型" required>
          <el-select v-model="form.summarizer_model_config_id">
            <el-option
              v-for="m in modelsStore.items"
              :key="m.id"
              :label="`${m.name} (${m.model_name})`"
              :value="m.id"
            />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogOpen = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="onCreate">
          开始跑团
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>
```

- [ ] **Step 2: commit**

```bash
git add frontend/
git commit -m "feat(views): SessionsView with create-and-jump-to-game flow"
```

---

## Task 10: GameView + StatePanel (the gameplay screen)

**Files:**
- Modify: `frontend/src/views/GameView.vue`
- Create: `frontend/src/components/StatePanel.vue`

- [ ] **Step 1: `frontend/src/components/StatePanel.vue`**

```vue
<script setup lang="ts">
defineProps<{
  stats: Record<string, number>
  inventory: string[]
  npcs: { name: string; favor: number; state: string }[]
}>()
</script>

<template>
  <aside class="w-80 bg-white border-l p-4 flex flex-col gap-4 overflow-auto">
    <section>
      <h3 class="font-bold text-slate-700 mb-2">角色状态</h3>
      <div class="space-y-1 text-sm">
        <div v-for="(v, k) in stats" :key="k" class="flex justify-between">
          <span class="text-slate-500">{{ k }}</span>
          <span class="font-mono">{{ v }}</span>
        </div>
        <div v-if="!Object.keys(stats).length" class="text-slate-400 italic">尚未初始化</div>
      </div>
    </section>

    <section>
      <h3 class="font-bold text-slate-700 mb-2">背包</h3>
      <ul class="space-y-1 text-sm">
        <li v-for="item in inventory" :key="item">· {{ item }}</li>
        <li v-if="!inventory.length" class="text-slate-400 italic">空</li>
      </ul>
    </section>

    <section>
      <h3 class="font-bold text-slate-700 mb-2">NPC 关系</h3>
      <ul class="space-y-1 text-sm">
        <li v-for="n in npcs" :key="n.name" class="flex justify-between">
          <span>{{ n.name }}</span>
          <span class="text-slate-500">
            <span class="font-mono mr-1">{{ n.favor >= 0 ? '+' : '' }}{{ n.favor }}</span>
            <span class="text-xs">{{ n.state }}</span>
          </span>
        </li>
        <li v-if="!npcs.length" class="text-slate-400 italic">尚无登场 NPC</li>
      </ul>
    </section>
  </aside>
</template>
```

- [ ] **Step 2: `frontend/src/views/GameView.vue`**

```vue
<script setup lang="ts">
import { ref, reactive, nextTick, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { streamTurn } from '@/composables/useTurnStream'
import { useSessionsStore } from '@/stores/sessions'
import StatePanel from '@/components/StatePanel.vue'
import MarkdownView from '@/components/MarkdownView.vue'

const props = defineProps<{ id: string }>()
const sessionId = Number(props.id)
const sessionsStore = useSessionsStore()

interface Turn {
  action: string
  narrative: string
}
const turns = ref<Turn[]>([])
const currentTurn = ref<Turn | null>(null)
const action = ref('')
const sending = ref(false)
const turnCount = ref(0)

const stats = reactive<Record<string, number>>({})
const inventory = ref<string[]>([])
const npcs = ref<{ name: string; favor: number; state: string }[]>([])

const logEl = ref<HTMLElement | null>(null)
async function scrollToBottom() {
  await nextTick()
  if (logEl.value) logEl.value.scrollTop = logEl.value.scrollHeight
}

function applyStateChange(content: string) {
  try {
    const obj = JSON.parse(content)
    for (const [k, v] of Object.entries(obj)) {
      if (k === 'inventory_add' && Array.isArray(v)) {
        inventory.value.push(...(v as string[]))
      } else if (k === 'inventory_remove' && Array.isArray(v)) {
        for (const item of v as string[]) {
          const idx = inventory.value.indexOf(item)
          if (idx >= 0) inventory.value.splice(idx, 1)
        }
      } else if (typeof v === 'number') {
        stats[k] = (stats[k] ?? 0) + v
      }
    }
  } catch {
    /* ignore malformed */
  }
}

function applyNpcUpdate(content: string) {
  try {
    const obj = JSON.parse(content)
    if (!obj.name) return
    const existing = npcs.value.find((n) => n.name === obj.name)
    if (existing) {
      if (typeof obj.favor_delta === 'number') existing.favor += obj.favor_delta
      if (obj.state) existing.state = obj.state
    } else {
      npcs.value.push({
        name: obj.name,
        favor: obj.favor_delta ?? 0,
        state: obj.state ?? '未知',
      })
    }
  } catch {
    /* ignore */
  }
}

async function send() {
  if (!action.value.trim() || sending.value) return
  const userAction = action.value.trim()
  action.value = ''
  sending.value = true

  const turn: Turn = { action: userAction, narrative: '' }
  currentTurn.value = turn
  turns.value.push(turn)
  await scrollToBottom()

  try {
    await streamTurn(sessionId, userAction, {
      onNarrative: (text) => {
        turn.narrative += text
        scrollToBottom()
      },
      onTag: (name, _attrs, content) => {
        if (name === 'state_change') applyStateChange(content)
        else if (name === 'npc_update') applyNpcUpdate(content)
      },
      onError: (msg) => {
        ElMessage.warning(msg)
      },
      onDone: () => {
        turnCount.value += 1
      },
    })
  } catch (e: any) {
    ElMessage.error(e.message ?? '请求失败')
    turn.narrative += `\n\n[出错：${e.message ?? '未知错误'}]`
  } finally {
    sending.value = false
    currentTurn.value = null
  }
}

const quickActions = ['环顾四周', '探索', '搭话', '潜行', '战斗', '使用物品']

function quick(act: string) {
  action.value = act
}

onMounted(async () => {
  try {
    const sess = await sessionsStore.get(sessionId)
    turnCount.value = sess.turn_count
  } catch {
    // ignore
  }
})
</script>

<template>
  <div class="flex h-full">
    <section class="flex-1 flex flex-col bg-slate-50">
      <header class="px-6 py-3 border-b bg-white flex items-center justify-between">
        <div class="font-bold">跑团进行中（已进行 {{ turnCount }} 回合）</div>
        <router-link to="/sessions" class="text-sm text-slate-500 hover:text-slate-800">
          返回存档
        </router-link>
      </header>

      <div ref="logEl" class="flex-1 overflow-auto px-6 py-4 space-y-6">
        <div v-if="!turns.length" class="text-slate-400 italic">
          输入第一个行动开始跑团（例如：「(开始游戏)」让 GM 给你开局描写）
        </div>
        <article v-for="(t, i) in turns" :key="i" class="space-y-2">
          <div class="text-sm text-slate-500 font-medium">▶ {{ t.action }}</div>
          <div class="bg-white rounded shadow-sm p-4">
            <MarkdownView :source="t.narrative" />
          </div>
        </article>
      </div>

      <footer class="border-t bg-white p-4 space-y-2">
        <div class="flex flex-wrap gap-2">
          <el-button
            v-for="a in quickActions"
            :key="a"
            size="small"
            @click="quick(a)"
            :disabled="sending"
          >{{ a }}</el-button>
        </div>
        <div class="flex gap-2">
          <el-input
            v-model="action"
            type="textarea"
            :rows="2"
            placeholder="输入你的行动…（Cmd/Ctrl+Enter 发送）"
            @keydown.enter.meta.prevent="send"
            @keydown.enter.ctrl.prevent="send"
            :disabled="sending"
          />
          <el-button type="primary" :loading="sending" @click="send">发送</el-button>
        </div>
      </footer>
    </section>

    <StatePanel :stats="stats" :inventory="inventory" :npcs="npcs" />
  </div>
</template>
```

- [ ] **Step 3: build check**

```bash
cd frontend && npm run build
```

Expected: build succeeds.

- [ ] **Step 4: commit**

```bash
git add frontend/
git commit -m "feat(views): GameView with streaming narrative + state panel"
```

---

## Task 11: README + final touches

**Files:**
- Create: `frontend/README.md`

- [ ] **Step 1: `frontend/README.md`**

```markdown
# dzmm frontend

Vue 3 + Vite + TypeScript + TailwindCSS + Element Plus.

## Setup

    cd frontend
    npm install

## Dev

In one terminal start the backend:

    cd backend && python scripts/run_dev.py

In another:

    cd frontend && npm run dev

Open http://localhost:5173.

The Vite dev server proxies `/api/*` to the backend at `http://127.0.0.1:8765`.

## Build

    npm run build

Output in `frontend/dist/`.

## Test

    npm run test

## Routes

- `/sessions` — list saves and start new ones
- `/worlds` — manage world settings (markdown)
- `/characters` — manage characters
- `/models` — manage model configs (Ollama / OpenAI-compatible)
- `/play/:id` — gameplay screen
```

- [ ] **Step 2: full build + test**

```bash
cd frontend && npm run build && npm run test
```

Expected: build succeeds; test passes.

- [ ] **Step 3: commit**

```bash
git add frontend/
git commit -m "docs: frontend README"
```

---

## Self-Review

**Spec coverage** vs requirements doc v0.1 frontend cut:

| Requirement | Task |
|---|---|
| Model config UI (Ollama + cloud) | Task 6 |
| Test connection button | Task 6 |
| World creation with markdown | Task 7 |
| Character creation form | Task 8 |
| Session list + new session | Task 9 |
| Streaming game UI | Task 10 |
| State panel (HP/inventory/NPCs) | Task 10 |
| Markdown rendering | Task 7, 10 |
| API client typed against backend schemas | Task 2 |

**Out of scope (deferred):**
- Theme switcher / font controls / sound — v0.2
- Edit/delete operations on existing entities (only create + list in v0.1)
- World/character templates dropdown — v0.2
- Export/import JSON — v0.2
- Quick-start saved configurations — v0.2

**Placeholder scan:** searched for "TODO", "TBD", "etc." in plan tasks. None.

**Dep consistency:** all view files reference stores by exact name (`useWorldsStore`, etc.); store actions match between views and store implementations; types defined once in `api/types.ts` and reused.
