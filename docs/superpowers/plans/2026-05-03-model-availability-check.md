# Model Availability Check Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When an Ollama model (narrative model or `nomic-embed-text`) is not running, warn the user immediately — in the wizard setup step, when entering a game session, and with a fix button in the archive (SessionsView) that swaps the model config inline.

**Architecture:** New backend endpoint `GET /model_configs/{cfg_id}/check` calls `OllamaClient.list_models()` (already implemented) and returns `{narrative_ok, embed_ok, missing}`. Frontend adds a `useModelCheck` composable that calls this endpoint reactively. GameView shows a dismissable warning banner on mount. WizardView shows inline status when a model is selected in step 0. SessionsView adds a model-status badge per session row and a "修改模型" button that opens the existing `sessionsApi.updateGmModel()` flow.

**Tech Stack:** FastAPI (existing), `OllamaClient.list_models()` (already exists), Vue 3 Composition API, `modelsApi` (existing), `sessionsApi.updateGmModel()` (already exists).

**Pre-existing:** `PATCH /sessions/{id}/gm_model` and `sessionsApi.updateGmModel()` already exist — no new backend for that.

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Modify | `backend/src/dzmm/api/routes_models.py` | Add `GET /{cfg_id}/check` endpoint |
| Create | `backend/tests/test_model_check.py` | Tests for the check endpoint |
| Modify | `frontend/src/api/models.ts` | Add `check(cfgId)` API call, `ModelCheckResult` type |
| Create | `frontend/src/composables/useModelCheck.ts` | Reactive composable wrapping the check API |
| Modify | `frontend/src/views/GameView.vue` | Add model warning banner on session entry |
| Modify | `frontend/src/views/WizardView.vue` | Add inline model status in step 0 model selects |
| Modify | `frontend/src/views/SessionsView.vue` | Add model status badge + "修改" dialog per session row |

---

## Task 1: Backend `GET /model_configs/{cfg_id}/check`

**Files:**
- Modify: `backend/src/dzmm/api/routes_models.py`
- Create: `backend/tests/test_model_check.py`

- [ ] **Step 1: Write failing test**

Create `backend/tests/test_model_check.py`:

```python
"""Tests for GET /model_configs/{cfg_id}/check endpoint."""
import pytest
from unittest.mock import AsyncMock, patch
from httpx import AsyncClient
from dzmm.app import create_app
from dzmm.db.base import get_engine, init_db, async_session
from dzmm.config import DEFAULT_DB_URL


@pytest.fixture
async def client_with_ollama_cfg(tmp_path):
    """Create a test app + one Ollama ModelConfig row."""
    engine = get_engine(f"sqlite+aiosqlite:///{tmp_path}/test.db")
    await init_db(engine)
    maker = async_session(engine)
    async with maker() as s:
        from dzmm.db.models import ModelConfig
        cfg = ModelConfig(
            name="local",
            type="ollama",
            base_url="http://localhost:11434",
            model_name="qwen2.5:7b",
        )
        s.add(cfg)
        await s.commit()
        await s.refresh(cfg)
        cfg_id = cfg.id
    app = create_app(engine)
    async with AsyncClient(app=app, base_url="http://test") as ac:
        yield ac, cfg_id
    await engine.dispose()


@pytest.mark.asyncio
async def test_check_returns_both_ok_when_models_present(client_with_ollama_cfg):
    ac, cfg_id = client_with_ollama_cfg
    with patch("dzmm.api.routes_models.build_client") as mock_build:
        mock_client = AsyncMock()
        mock_client.list_models = AsyncMock(return_value=["qwen2.5:7b", "nomic-embed-text:latest"])
        mock_build.return_value = mock_client
        resp = await ac.get(f"/model_configs/{cfg_id}/check")
    assert resp.status_code == 200
    data = resp.json()
    assert data["narrative_ok"] is True
    assert data["embed_ok"] is True
    assert data["missing"] == []


@pytest.mark.asyncio
async def test_check_reports_missing_embed_model(client_with_ollama_cfg):
    ac, cfg_id = client_with_ollama_cfg
    with patch("dzmm.api.routes_models.build_client") as mock_build:
        mock_client = AsyncMock()
        mock_client.list_models = AsyncMock(return_value=["qwen2.5:7b"])
        mock_build.return_value = mock_client
        resp = await ac.get(f"/model_configs/{cfg_id}/check")
    assert resp.status_code == 200
    data = resp.json()
    assert data["narrative_ok"] is True
    assert data["embed_ok"] is False
    assert "nomic-embed-text" in data["missing"]


@pytest.mark.asyncio
async def test_check_reports_missing_narrative_model(client_with_ollama_cfg):
    ac, cfg_id = client_with_ollama_cfg
    with patch("dzmm.api.routes_models.build_client") as mock_build:
        mock_client = AsyncMock()
        mock_client.list_models = AsyncMock(return_value=["nomic-embed-text:latest"])
        mock_build.return_value = mock_client
        resp = await ac.get(f"/model_configs/{cfg_id}/check")
    assert resp.status_code == 200
    data = resp.json()
    assert data["narrative_ok"] is False
    assert "qwen2.5:7b" in data["missing"]


@pytest.mark.asyncio
async def test_check_non_ollama_returns_null_embed(tmp_path):
    engine = get_engine(f"sqlite+aiosqlite:///{tmp_path}/test2.db")
    await init_db(engine)
    maker = async_session(engine)
    async with maker() as s:
        from dzmm.db.models import ModelConfig
        cfg = ModelConfig(
            name="openai",
            type="openai_compat",
            base_url="https://api.openai.com/v1",
            model_name="gpt-4o-mini",
        )
        s.add(cfg)
        await s.commit()
        await s.refresh(cfg)
        cfg_id = cfg.id
    app = create_app(engine)
    async with AsyncClient(app=app, base_url="http://test") as ac:
        with patch("dzmm.api.routes_models.build_client") as mock_build:
            mock_client = AsyncMock()
            mock_client.health_check = AsyncMock(return_value=(True, "ok"))
            mock_build.return_value = mock_client
            resp = await ac.get(f"/model_configs/{cfg_id}/check")
    assert resp.status_code == 200
    data = resp.json()
    assert data["narrative_ok"] is True
    assert data["embed_ok"] is None  # non-Ollama: not applicable
    await engine.dispose()
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd /Users/norman/development/dzmm/backend && python -m pytest tests/test_model_check.py::test_check_returns_both_ok_when_models_present -v 2>&1 | tail -5
```

Expected: 404 (endpoint not yet defined) or ImportError.

- [ ] **Step 3: Add `GET /{cfg_id}/check` to `routes_models.py`**

Read `backend/src/dzmm/api/routes_models.py`. After the `test_model_config` endpoint (after line ~57), insert:

```python
_EMBED_MODEL = "nomic-embed-text"


@router.get("/{cfg_id}/check")
async def check_model_config(cfg_id: int, s: AsyncSession = Depends(get_session_dep)):
    """Check if the configured model (and embed model) are available in Ollama.

    Returns:
      narrative_ok: whether the narrative model responds
      embed_ok: whether nomic-embed-text is pulled (None for non-Ollama configs)
      missing: list of model names that need to be pulled
    """
    cfg = await s.get(ModelConfig, cfg_id)
    if cfg is None:
        raise HTTPException(404, "config not found")
    client = build_client(cfg)

    if cfg.type != "ollama":
        ok, _ = await client.health_check()
        return {"narrative_ok": ok, "embed_ok": None, "missing": []}

    # Ollama: check both narrative model and embed model
    try:
        available = await client.list_models()
    except Exception:
        return {"narrative_ok": False, "embed_ok": False, "missing": [cfg.model_name, _EMBED_MODEL]}

    # Ollama model names can include tags like "qwen2.5:7b" or "qwen2.5:latest"
    # Match by stripping the tag for a "starts with" check
    def _model_available(target: str, available_list: list[str]) -> bool:
        base = target.split(":")[0].lower()
        return any(m.lower().startswith(base) for m in available_list)

    narrative_ok = _model_available(cfg.model_name, available)
    embed_ok = _model_available(_EMBED_MODEL, available)

    missing = []
    if not narrative_ok:
        missing.append(cfg.model_name)
    if not embed_ok:
        missing.append(_EMBED_MODEL)

    return {"narrative_ok": narrative_ok, "embed_ok": embed_ok, "missing": missing}
```

- [ ] **Step 4: Run tests**

```bash
cd /Users/norman/development/dzmm/backend && python -m pytest tests/test_model_check.py -v
```

Expected: all 4 pass.

- [ ] **Step 5: Run full suite**

```bash
cd /Users/norman/development/dzmm/backend && python -m pytest tests/ -x --ignore=tests/test_ollama.py --ignore=tests/test_openai_compat.py -q 2>&1 | tail -5
```

- [ ] **Step 6: Commit**

```bash
cd /Users/norman/development/dzmm && git add backend/src/dzmm/api/routes_models.py backend/tests/test_model_check.py && git commit -m "feat(models): add GET /model_configs/{id}/check for Ollama model availability"
```

---

## Task 2: Frontend API + composable

**Files:**
- Modify: `frontend/src/api/models.ts`
- Create: `frontend/src/composables/useModelCheck.ts`

- [ ] **Step 1: Add `check` to `frontend/src/api/models.ts`**

Read the current file. Add the `ModelCheckResult` interface and `check` method:

```typescript
export interface ModelCheckResult {
  narrative_ok: boolean
  embed_ok: boolean | null   // null = not applicable (non-Ollama)
  missing: string[]
}

// Inside modelsApi object, add:
check: (id: number) =>
  api.get<ModelCheckResult>(`/model_configs/${id}/check`).then((r) => r.data),
```

Full new `frontend/src/api/models.ts`:

```typescript
import { api } from './client'
import type { ModelConfig, ModelConfigIn } from './types'

export interface ModelCheckResult {
  narrative_ok: boolean
  embed_ok: boolean | null
  missing: string[]
}

export const modelsApi = {
  list: () => api.get<ModelConfig[]>('/model_configs').then((r) => r.data),
  create: (body: ModelConfigIn) =>
    api.post<ModelConfig>('/model_configs', body).then((r) => r.data),
  update: (id: number, body: ModelConfigIn) =>
    api.put<ModelConfig>(`/model_configs/${id}`, body).then((r) => r.data),
  remove: (id: number) => api.delete(`/model_configs/${id}`).then(() => undefined),
  test: (id: number) =>
    api.post<{ ok: boolean; info: string }>(`/model_configs/${id}/test`).then((r) => r.data),
  check: (id: number) =>
    api.get<ModelCheckResult>(`/model_configs/${id}/check`).then((r) => r.data),
}
```

- [ ] **Step 2: Create `frontend/src/composables/useModelCheck.ts`**

```typescript
import { ref, computed, watch } from 'vue'
import type { Ref } from 'vue'
import { modelsApi } from '@/api/models'
import type { ModelCheckResult } from '@/api/models'

export function useModelCheck(cfgId: Ref<number | null | undefined>) {
  const result = ref<ModelCheckResult | null>(null)
  const checking = ref(false)
  const error = ref(false)

  async function check() {
    const id = cfgId.value
    if (!id) {
      result.value = null
      return
    }
    checking.value = true
    error.value = false
    try {
      result.value = await modelsApi.check(id)
    } catch {
      error.value = true
      result.value = null
    } finally {
      checking.value = false
    }
  }

  // Re-check whenever the config id changes
  watch(cfgId, () => check(), { immediate: true })

  // isOk: true only when both narrative and (if applicable) embed are available
  const isOk = computed(() => {
    if (!result.value) return null  // null = unknown (still checking or error)
    const embedOk = result.value.embed_ok ?? true  // null = not applicable → treat as ok
    return result.value.narrative_ok && embedOk
  })

  // Human-readable pull commands for missing models
  const pullCommands = computed<string[]>(() =>
    (result.value?.missing ?? []).map((m) => `ollama pull ${m}`)
  )

  return { result, checking, error, isOk, pullCommands, check }
}
```

- [ ] **Step 3: Verify TypeScript compiles**

```bash
cd /Users/norman/development/dzmm/frontend && npx vue-tsc --noEmit 2>&1 | grep -E "error|Error" | head -10
```

Expected: no errors related to the new files.

- [ ] **Step 4: Commit**

```bash
cd /Users/norman/development/dzmm && git add frontend/src/api/models.ts frontend/src/composables/useModelCheck.ts && git commit -m "feat(frontend): add ModelCheckResult type, modelsApi.check(), useModelCheck composable"
```

---

## Task 3: GameView warning banner

**Files:**
- Modify: `frontend/src/views/GameView.vue`

Context: When the user enters a session (GameView mounts), we check if the session's GM model config is reachable. If not, show a top-of-page warning banner with the missing models and their pull commands. The banner is dismissable.

- [ ] **Step 1: Read the top of `frontend/src/views/GameView.vue`**

Run:
```bash
head -80 /Users/norman/development/dzmm/frontend/src/views/GameView.vue
```

This tells you where the `<script setup>` ends and `<template>` begins, and how `sessionId` / `session` are loaded.

- [ ] **Step 2: Add model check to `<script setup>` in `GameView.vue`**

Find where `session` data is loaded (look for `sessionsApi` or `useGameState`). Add after the existing imports:

```typescript
import { ref, computed, watch } from 'vue'
import { useModelCheck } from '@/composables/useModelCheck'
```

Then after the session is loaded (where `session.value` is available), add:

```typescript
// Model availability check
const gmCfgId = computed(() => session.value?.gm_model_config_id ?? null)
const { isOk: modelOk, pullCommands, checking: modelChecking } = useModelCheck(gmCfgId)
const modelBannerDismissed = ref(false)
const showModelBanner = computed(
  () => modelOk.value === false && !modelBannerDismissed.value
)
```

- [ ] **Step 3: Add warning banner to `<template>` in `GameView.vue`**

Find the top of the main content area in the template (after `<div class="...">` wrapping the game layout). Insert the banner as the first child:

```html
<!-- Model availability warning -->
<div
  v-if="showModelBanner"
  class="mx-4 mt-3 p-3 bg-amber-50 border border-amber-300 rounded-lg flex items-start gap-3 text-sm"
>
  <span class="text-amber-600 text-lg leading-none mt-0.5">⚠️</span>
  <div class="flex-1">
    <div class="font-semibold text-amber-800">模型不可用</div>
    <div class="text-amber-700 mt-0.5">
      以下模型未运行，游戏可能无法正常工作：
    </div>
    <div class="mt-1 space-y-0.5">
      <div
        v-for="cmd in pullCommands"
        :key="cmd"
        class="font-mono text-xs bg-amber-100 text-amber-900 px-2 py-1 rounded select-all"
      >{{ cmd }}</div>
    </div>
    <div class="mt-1.5 text-amber-600 text-xs">
      在终端运行以上命令后，刷新页面。或前往
      <router-link to="/sessions" class="underline font-medium">存档列表</router-link>
      更换模型。
    </div>
  </div>
  <button
    class="text-amber-500 hover:text-amber-700 text-lg leading-none"
    @click="modelBannerDismissed = true"
    title="关闭"
  >✕</button>
</div>
```

- [ ] **Step 4: Start dev server and verify**

```bash
cd /Users/norman/development/dzmm && npm --prefix frontend run dev &
```

Open a session in the browser. The banner should not appear if Ollama is running correctly. To test the warning: temporarily change the model config's base_url to an invalid port in the DB.

(If the dev server can't run in this environment, skip to the TypeScript check.)

```bash
cd /Users/norman/development/dzmm/frontend && npx vue-tsc --noEmit 2>&1 | grep "error" | head -10
```

Expected: no new TypeScript errors.

- [ ] **Step 5: Commit**

```bash
cd /Users/norman/development/dzmm && git add frontend/src/views/GameView.vue && git commit -m "feat(game): show model availability warning banner on session entry"
```

---

## Task 4: WizardView inline model status

**Files:**
- Modify: `frontend/src/views/WizardView.vue`

Context: In step 0, the user selects three model configs (wizard, GM, summarizer). After each selection, show a small status indicator — ✓ green if both models are available, ✗ red if not, with the pull command shown inline. This gives early feedback before wasting time on a 5-step wizard.

- [ ] **Step 1: Add model check composables to `<script setup>` in `WizardView.vue`**

Read `frontend/src/views/WizardView.vue` lines 1–50 (script imports). Then add:

```typescript
import { useModelCheck } from '@/composables/useModelCheck'
import { computed } from 'vue'

// Model availability checks for wizard + GM model selects
const wizardCfgId = computed(() => state.wizard_model_config_id)
const gmWizardCfgId = computed(() => state.gm_model_config_id)

const {
  isOk: wizardModelOk, pullCommands: wizardPullCmds, checking: wizardChecking,
} = useModelCheck(wizardCfgId)
const {
  isOk: gmModelOk, pullCommands: gmPullCmds, checking: gmChecking,
} = useModelCheck(gmWizardCfgId)
```

- [ ] **Step 2: Add inline status below each model selector in the template**

In the step 0 section of the template (around line ~606 of WizardView.vue), find the "向导用模型" `<el-select>` and its hint `<div class="text-xs...">`. After that hint div, add:

```html
<!-- Wizard model status -->
<div v-if="state.wizard_model_config_id" class="mt-1.5 text-xs flex items-center gap-1.5">
  <span v-if="wizardChecking" class="text-slate-400">检查中…</span>
  <span v-else-if="wizardModelOk === true" class="text-green-600">✓ 模型在线</span>
  <span v-else-if="wizardModelOk === false" class="text-red-600 space-y-0.5">
    <span>✗ 模型不可用</span>
    <div v-for="cmd in wizardPullCmds" :key="cmd" class="font-mono bg-red-50 text-red-800 px-1.5 py-0.5 rounded">{{ cmd }}</div>
  </span>
</div>
```

Find the "跑团 GM 模型" `<el-select>` and its hint. After that hint, add:

```html
<!-- GM model status -->
<div v-if="state.gm_model_config_id" class="mt-1.5 text-xs flex items-center gap-1.5">
  <span v-if="gmChecking" class="text-slate-400">检查中…</span>
  <span v-else-if="gmModelOk === true" class="text-green-600">✓ 模型在线（含 nomic-embed-text）</span>
  <span v-else-if="gmModelOk === false" class="text-red-600">
    <span>✗ 缺少以下模型：</span>
    <div v-for="cmd in gmPullCmds" :key="cmd" class="font-mono bg-red-50 text-red-800 px-1.5 py-0.5 rounded mt-0.5">{{ cmd }}</div>
  </span>
</div>
```

- [ ] **Step 3: TypeScript check**

```bash
cd /Users/norman/development/dzmm/frontend && npx vue-tsc --noEmit 2>&1 | grep "error" | head -10
```

Expected: no errors.

- [ ] **Step 4: Commit**

```bash
cd /Users/norman/development/dzmm && git add frontend/src/views/WizardView.vue && git commit -m "feat(wizard): show inline model availability status in setup step"
```

---

## Task 5: SessionsView model status badge + inline fix dialog

**Files:**
- Modify: `frontend/src/views/SessionsView.vue`

Context: Each session row shows its GM model name. Add a "检测" button that runs a check and shows the result inline. Add a "修改" button that opens a small dialog with a model config dropdown (calls the existing `sessionsApi.updateGmModel()` which hits the already-implemented `PATCH /sessions/{id}/gm_model`).

- [ ] **Step 1: Read `SessionsView.vue` imports and session table template**

```bash
head -60 /Users/norman/development/dzmm/frontend/src/views/SessionsView.vue
grep -n "turn_count\|session\.id\|el-table\|<td\|gm_model\|model" /Users/norman/development/dzmm/frontend/src/views/SessionsView.vue | head -30
```

This shows what data is available per session row and where the table columns are.

- [ ] **Step 2: Add model-check state and the fix dialog logic to `<script setup>`**

Read the current `<script setup>` in `SessionsView.vue`. Add:

```typescript
import { ref, reactive } from 'vue'
import { modelsApi } from '@/api/models'
import type { ModelCheckResult } from '@/api/models'
import { sessionsApi } from '@/api/sessions'
import { useModelConfigsStore } from '@/stores/modelConfigs'

const modelConfigsStore = useModelConfigsStore()

// Per-session model check results (keyed by session id)
const modelCheckResults = reactive<Record<number, ModelCheckResult | 'checking' | 'error'>>({})

async function checkSessionModel(session: GameSession) {
  modelCheckResults[session.id] = 'checking'
  try {
    const result = await modelsApi.check(session.gm_model_config_id)
    modelCheckResults[session.id] = result
  } catch {
    modelCheckResults[session.id] = 'error'
  }
}

// Fix model dialog
const fixModelDialog = reactive({
  visible: false,
  sessionId: 0,
  selectedCfgId: 0,
  saving: false,
})

function openFixModel(session: GameSession) {
  fixModelDialog.sessionId = session.id
  fixModelDialog.selectedCfgId = session.gm_model_config_id
  fixModelDialog.visible = true
  fixModelDialog.saving = false
}

async function saveFixModel() {
  fixModelDialog.saving = true
  try {
    await sessionsApi.updateGmModel(fixModelDialog.sessionId, fixModelDialog.selectedCfgId)
    // Refresh the session in the store
    await sessionsStore.fetchAll()
    fixModelDialog.visible = false
    ElMessage.success('模型已更新')
  } catch {
    ElMessage.error('更新失败，请重试')
  } finally {
    fixModelDialog.saving = false
  }
}
```

Note: `ElMessage` is already imported in `SessionsView.vue`. `sessionsStore` already exists. Check that `modelsApi` and `modelConfigsStore` are not already imported before adding them.

- [ ] **Step 3: Add model status column and buttons to the sessions table**

Find the `<el-table-column>` block that renders session rows in the template. Add a new column after the existing ones (before the actions column):

```html
<!-- GM 模型状态 -->
<el-table-column label="GM 模型" min-width="160">
  <template #default="{ row }">
    <div class="flex items-center gap-1.5 text-sm">
      <!-- Model name -->
      <span class="text-slate-600 text-xs truncate max-w-[80px]" :title="modelConfigsStore.nameById(row.gm_model_config_id)">
        {{ modelConfigsStore.nameById(row.gm_model_config_id) || '未设置' }}
      </span>

      <!-- Check status badge -->
      <template v-if="modelCheckResults[row.id]">
        <span v-if="modelCheckResults[row.id] === 'checking'" class="text-slate-400 text-xs">…</span>
        <span
          v-else-if="modelCheckResults[row.id] === 'error'"
          class="text-orange-500 text-xs"
          title="检测失败"
        >⚠️</span>
        <span
          v-else-if="(modelCheckResults[row.id] as ModelCheckResult).narrative_ok && ((modelCheckResults[row.id] as ModelCheckResult).embed_ok ?? true)"
          class="text-green-600 text-xs"
          title="模型在线"
        >✓</span>
        <span
          v-else
          class="text-red-500 text-xs cursor-pointer"
          :title="'缺少：' + (modelCheckResults[row.id] as ModelCheckResult).missing.join(', ')"
        >✗</span>
      </template>

      <!-- Buttons -->
      <el-button size="small" text @click="checkSessionModel(row)" :loading="modelCheckResults[row.id] === 'checking'">
        检测
      </el-button>
      <el-button size="small" text type="primary" @click="openFixModel(row)">
        修改
      </el-button>
    </div>
  </template>
</el-table-column>
```

- [ ] **Step 4: Add the fix model dialog**

Find where other dialogs are defined in the template (e.g., the delete confirmation dialog). Add before `</template>`:

```html
<!-- Fix model config dialog -->
<el-dialog v-model="fixModelDialog.visible" title="修改 GM 模型" width="420px">
  <div class="space-y-3">
    <div class="text-sm text-slate-600">为该存档选择新的 GM 模型配置：</div>
    <el-select v-model="fixModelDialog.selectedCfgId" class="w-full">
      <el-option
        v-for="cfg in modelConfigsStore.items"
        :key="cfg.id"
        :label="`${cfg.name} (${cfg.model_name})`"
        :value="cfg.id"
      />
    </el-select>
    <div class="text-xs text-slate-400">
      切换后立即生效，下次回合开始使用新模型。
    </div>
  </div>
  <template #footer>
    <el-button @click="fixModelDialog.visible = false">取消</el-button>
    <el-button type="primary" :loading="fixModelDialog.saving" @click="saveFixModel">
      保存
    </el-button>
  </template>
</el-dialog>
```

- [ ] **Step 5: Add `nameById` helper to `modelConfigsStore` if it doesn't exist**

Check `frontend/src/stores/modelConfigs.ts`:

```bash
grep -n "nameById\|items\|getters" /Users/norman/development/dzmm/frontend/src/stores/modelConfigs.ts
```

If `nameById` doesn't exist, add to the store:

```typescript
// In the store definition, add a getter:
const nameById = (id: number): string => {
  return items.value.find((m) => m.id === id)?.name ?? ''
}
// Return it in the store return object
return { ..., nameById }
```

- [ ] **Step 6: TypeScript check**

```bash
cd /Users/norman/development/dzmm/frontend && npx vue-tsc --noEmit 2>&1 | grep "error" | head -15
```

Fix any TypeScript errors before committing. Common issues:
- `ModelCheckResult` needs to be imported in SessionsView — already done in step 2
- `sessionsStore` might need explicit type — check existing usage pattern in SessionsView

- [ ] **Step 7: Run full backend test suite one final time**

```bash
cd /Users/norman/development/dzmm/backend && python -m pytest tests/ --ignore=tests/test_ollama.py --ignore=tests/test_openai_compat.py -q 2>&1 | tail -5
```

- [ ] **Step 8: Commit and push**

```bash
cd /Users/norman/development/dzmm && git add frontend/src/views/SessionsView.vue frontend/src/stores/modelConfigs.ts && git commit -m "feat(sessions): add GM model status check + inline model switch dialog"
git push
```

---

## Self-Review

**Spec coverage:**
- [x] 引导里（Wizard setup step 0）：选模型后显示在线状态 + pull 命令 ✓ Task 4
- [x] 开始游戏的检查：GameView mount 时 check，不可用则 banner ✓ Task 3
- [x] 提示 nomic-embed-text 缺失：check endpoint 同时检查叙事模型和 embed 模型 ✓ Task 1
- [x] 存档页面能修改模型：SessionsView "修改" 按钮 → dialog → `updateGmModel()` ✓ Task 5
- [x] 叙事模型不可用提示：`narrative_ok` flag ✓ Task 1

**Placeholder scan:** None found.

**Type consistency:**
- `ModelCheckResult` — defined Task 2 (`models.ts`), used in Task 2 composable, Task 3, Task 5. ✓
- `useModelCheck(cfgId: Ref<number|null|undefined>)` — returns `{isOk, pullCommands, checking, result, check}`. Used in Task 3 and Task 4. ✓
- `modelsApi.check(id)` — added Task 2, called in composable (Task 2) and SessionsView direct call (Task 5). ✓
- `sessionsApi.updateGmModel(sessionId, gmModelConfigId)` — pre-existing, called Task 5. ✓
