<script setup lang="ts">
//
// v0.2.0 Wizard — 6-step session creation flow.
//
//   step 0: setup           (no LLM)
//   step 1: world brief     -> POST /wizard/world_brief
//   step 2: world details   -> POST /wizard/world_details
//   step 3: PC character    -> POST /wizard/character
//   step 4: pinned NPCs     -> POST /wizard/npcs
//   step 5: screenplay      -> POST /wizard/screenplay
//   step 6: review + create -> POST /wizard/finalize  -> /play/:id
//
// State is in-memory only (reactive). Refreshing the page restarts the wizard.
// Each step has 4 actions: ✏️ 编辑 / 🔄 重新生成 / ✏️ 我自己写 / ⏩ 接受
//
import { computed, onMounted, onBeforeUnmount, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import {
  ElSteps,
  ElStep,
  ElButton,
  ElInput,
  ElSelect,
  ElOption,
  ElCard,
  ElTag,
  ElCheckbox,
  ElDialog,
  ElMessage,
} from 'element-plus'
import {
  wizardApi,
  type ThemeSuggestion,
  type WorldBrief,
  type WizardNPC,
  type WizardScreenplay,
} from '@/api/wizard'
import { streamWizardStep } from '@/composables/useWizardStream'
import { KNOWN_GENRES } from '@/api/screenplay'
import { useModelConfigsStore } from '@/stores/modelConfigs'
import { useModelCheck } from '@/composables/useModelCheck'
import MarkdownView from '@/components/MarkdownView.vue'
import WizardStep from '@/components/wizard/WizardStep.vue'

const router = useRouter()
const modelsStore = useModelConfigsStore()

// ---- shared state (in-memory only) ----

interface State {
  // step 0
  wizard_model_config_id: number | null
  gm_model_config_id: number | null
  summarizer_model_config_id: number | null
  genre: string
  custom_genre: string
  theme: string
  session_name: string
  // step 1
  world_brief: WorldBrief | null
  // step 2
  world_md: string
  // step 3
  archetype: string
  character_name: string
  character_md: string
  // step 4
  npcs: WizardNPC[]
  pinned_npc_names: string[]
  // step 5
  screenplay: WizardScreenplay | null
  // debug
  raw_outputs: Record<string, string>
}

const state = reactive<State>({
  wizard_model_config_id: null,
  gm_model_config_id: null,
  summarizer_model_config_id: null,
  genre: '悬疑探案',
  custom_genre: '',
  theme: '',
  session_name: '',
  world_brief: null,
  world_md: '',
  archetype: '',
  character_name: '',
  character_md: '',
  npcs: [],
  pinned_npc_names: [],
  screenplay: null,
  raw_outputs: {},
})

// ---- model availability checks ----

const wizardCfgId = computed(() => state.wizard_model_config_id)
const gmWizardCfgId = computed(() => state.gm_model_config_id)

const { isOk: wizardModelOk, pullCommands: wizardPullCmds, checking: wizardChecking } = useModelCheck(wizardCfgId)
const { isOk: gmModelOk, pullCommands: gmPullCmds, checking: gmChecking } = useModelCheck(gmWizardCfgId)

// 0..6 (7 stages: setup + 5 LLM-driven steps + review)
const step = ref(0)

const showRawKey = ref<string | null>(null)

const DRAFT_KEY = 'dzmm_wizard_draft'

function saveDraft() {
  try {
    localStorage.setItem(DRAFT_KEY, JSON.stringify({ step: step.value, state }))
  } catch { /* ignore quota errors */ }
}

function clearDraft() {
  localStorage.removeItem(DRAFT_KEY)
}

function loadDraft(): boolean {
  try {
    const raw = localStorage.getItem(DRAFT_KEY)
    if (!raw) return false
    const { step: savedStep, state: savedState } = JSON.parse(raw)
    Object.assign(state, savedState)
    step.value = savedStep
    return true
  } catch {
    clearDraft()
    return false
  }
}

const loading = ref(false)
const errorMsg = ref('')

// edit-mode toggles per step (only used by step 1..5)
const editing = reactive({
  brief: false,
  world: false,
  character: false,
  npcs: false,
  screenplay: false,
})

// live streaming text per step (cleared at the start of each generation)
const streamText = reactive({
  brief: '',
  world: '',
  character: '',
  npcs: '',
  screenplay: '',
})

// ---- timer (reused across loading states) ----

const elapsed = ref(0)
const tipIdx = ref(0)
const tips = [
  '世界观的「冲突」是最重要的，所有故事都从冲突里长出来',
  '主角的「动机」决定 GM 怎么编排剧情',
  '钉住的 NPC 会出现在剧本里反复出场',
  '剧本是大纲，GM 跑团时会即兴发挥不偏离主线',
  '本地模型慢一点，云模型快但需要 API key',
  '每一步都可以「✏️ 我自己写」绕过 LLM',
]
let timer: number | null = null

function clearTimer() {
  if (timer !== null) {
    window.clearInterval(timer)
    timer = null
  }
}

function startTimer() {
  elapsed.value = 0
  tipIdx.value = 0
  clearTimer()
  timer = window.setInterval(() => {
    elapsed.value += 1
    if (elapsed.value % 3 === 0) {
      tipIdx.value = (tipIdx.value + 1) % tips.length
    }
  }, 1000)
}

const currentTip = computed(() => tips[tipIdx.value])

// ---- helpers ----

const effectiveGenre = computed(() =>
  state.genre === '自定义' && state.custom_genre.trim()
    ? state.custom_genre.trim()
    : state.genre,
)

function ensureWizardModel(): number | null {
  if (!state.wizard_model_config_id) {
    ElMessage.error('请先选择「向导用模型」')
    return null
  }
  return state.wizard_model_config_id
}

function setupValid(): boolean {
  return !!(
    state.wizard_model_config_id &&
    state.gm_model_config_id &&
    state.summarizer_model_config_id &&
    state.theme.trim() &&
    state.session_name.trim()
  )
}

// ---- step 1: world brief ----

async function generateBrief() {
  const mid = ensureWizardModel()
  if (!mid) return
  state.world_brief = null
  streamText.brief = ''
  loading.value = true
  errorMsg.value = ''
  startTimer()
  try {
    await streamWizardStep(
      '/wizard/world_brief/stream',
      { model_config_id: mid, genre: effectiveGenre.value, theme: state.theme.trim() },
      {
        onDelta: (t) => { streamText.brief += t },
        onResult: (data: WorldBrief) => {
          state.world_brief = data
          state.raw_outputs['world_brief'] = data.raw_md ?? ''
          saveDraft()
          editing.brief = false
        },
        onError: (msg) => { errorMsg.value = msg },
      },
    )
  } catch (e: any) {
    errorMsg.value = e?.message ?? String(e)
  } finally {
    clearTimer()
    loading.value = false
  }
}

function handwriteBrief() {
  state.world_brief = {
    name: '',
    setting: '',
    conflict: '',
    raw_md: '',
  }
  editing.brief = true
}

// ---- step 2: world details ----

async function generateWorldDetails() {
  const mid = ensureWizardModel()
  if (!mid) return
  if (!state.world_brief?.raw_md.trim()) {
    ElMessage.error('基础设定为空，无法扩展')
    return
  }
  state.world_md = ''
  streamText.world = ''
  loading.value = true
  errorMsg.value = ''
  startTimer()
  try {
    await streamWizardStep(
      '/wizard/world_details/stream',
      { model_config_id: mid, brief_md: state.world_brief.raw_md },
      {
        onDelta: (t) => { streamText.world += t },
        onResult: (data: { world_md: string }) => {
          state.world_md = data.world_md
          state.raw_outputs['world_details'] = data.world_md
          saveDraft()
          editing.world = false
        },
        onError: (msg) => { errorMsg.value = msg },
      },
    )
  } catch (e: any) {
    errorMsg.value = e?.message ?? String(e)
  } finally {
    clearTimer()
    loading.value = false
  }
}

function handwriteWorld() {
  state.world_md = state.world_md || ''
  editing.world = true
}

// ---- step 3: character ----

async function generateCharacter() {
  const mid = ensureWizardModel()
  if (!mid) return
  if (!state.archetype.trim()) {
    ElMessage.error('请输入角色原型')
    return
  }
  state.character_md = ''
  state.character_name = ''
  streamText.character = ''
  loading.value = true
  errorMsg.value = ''
  startTimer()
  try {
    await streamWizardStep(
      '/wizard/character/stream',
      { model_config_id: mid, world_md: state.world_md, archetype: state.archetype.trim() },
      {
        onDelta: (t) => { streamText.character += t },
        onResult: (data: { name: string; profile_md: string }) => {
          state.character_name = data.name
          state.character_md = data.profile_md
          state.raw_outputs['character'] = data.profile_md
          saveDraft()
          editing.character = false
        },
        onError: (msg) => { errorMsg.value = msg },
      },
    )
  } catch (e: any) {
    errorMsg.value = e?.message ?? String(e)
  } finally {
    clearTimer()
    loading.value = false
  }
}

function handwriteCharacter() {
  editing.character = true
}

// ---- step 4: NPCs ----

async function generateNpcs() {
  const mid = ensureWizardModel()
  if (!mid) return
  state.npcs = []
  state.screenplay = null
  streamText.npcs = ''
  loading.value = true
  errorMsg.value = ''
  startTimer()
  try {
    await streamWizardStep(
      '/wizard/npcs/stream',
      { model_config_id: mid, world_md: state.world_md, character_md: state.character_md },
      {
        onDelta: (t) => { streamText.npcs += t },
        onResult: (data: { npcs: WizardNPC[] }) => {
          state.npcs = data.npcs
          state.pinned_npc_names = data.npcs.map((n) => n.name)
          state.raw_outputs['npcs'] = JSON.stringify(data.npcs, null, 2)
          saveDraft()
          editing.npcs = false
        },
        onError: (msg) => { errorMsg.value = msg },
      },
    )
  } catch (e: any) {
    errorMsg.value = e?.message ?? String(e)
  } finally {
    clearTimer()
    loading.value = false
  }
}

const npcEditDialog = reactive<{ open: boolean; idx: number; draft: WizardNPC }>(
  {
    open: false,
    idx: -1,
    draft: { name: '', role: '', description: '', motivation: '' },
  },
)

const npcHintDialog = ref(false)
const npcHint = ref('')
const npcGenerating = ref(false)

function openNpcEdit(i: number) {
  const n = state.npcs[i]
  if (!n) return
  npcEditDialog.idx = i
  npcEditDialog.draft = { ...n }
  npcEditDialog.open = true
}

function saveNpcEdit() {
  if (npcEditDialog.idx >= 0) {
    state.npcs[npcEditDialog.idx] = { ...npcEditDialog.draft }
  }
  npcEditDialog.open = false
}

function togglePinNpc(name: string) {
  const i = state.pinned_npc_names.indexOf(name)
  if (i >= 0) state.pinned_npc_names.splice(i, 1)
  else state.pinned_npc_names.push(name)
}

function isPinned(name: string): boolean {
  return state.pinned_npc_names.includes(name)
}

function deleteNpc(idx: number) {
  const name = state.npcs[idx]?.name
  state.npcs.splice(idx, 1)
  if (name) {
    const i = state.pinned_npc_names.indexOf(name)
    if (i >= 0) state.pinned_npc_names.splice(i, 1)
  }
  saveDraft()
}

function addBlankNpc() {
  state.npcs.push({ name: '', role: '', description: '', motivation: '' })
  openNpcEdit(state.npcs.length - 1)
}

async function aiGenerateSingleNpc() {
  const mid = ensureWizardModel()
  if (!mid) return
  npcGenerating.value = true
  try {
    const r = await wizardApi.generateSingleNpc({
      model_config_id: mid,
      world_md: state.world_md,
      character_md: state.character_md,
      hint: npcHint.value,
    })
    const npc: WizardNPC = {
      name: r.name,
      description: r.description,
      role: r.archetype || '',
      motivation: r.purpose || '',
    }
    state.npcs.push(npc)
    state.pinned_npc_names.push(npc.name)
    npcHintDialog.value = false
    npcHint.value = ''
    saveDraft()
  } catch (e: any) {
    ElMessage.error(e?.message ?? '生成失败')
  } finally {
    npcGenerating.value = false
  }
}

// ---- step 5: screenplay ----

async function generateScreenplay() {
  const mid = ensureWizardModel()
  if (!mid) return
  state.screenplay = null
  streamText.screenplay = ''
  loading.value = true
  errorMsg.value = ''
  startTimer()
  try {
    await streamWizardStep(
      '/wizard/screenplay/stream',
      {
        model_config_id: mid,
        world_md: state.world_md,
        character_md: state.character_md,
        npcs: state.npcs.filter((n) => isPinned(n.name)),
        genre: effectiveGenre.value,
      },
      {
        onDelta: (t) => { streamText.screenplay += t },
        onResult: (data: WizardScreenplay) => {
          state.screenplay = data
          state.raw_outputs['screenplay'] = JSON.stringify(data, null, 2)
          saveDraft()
          editing.screenplay = false
        },
        onError: (msg) => { errorMsg.value = msg },
      },
    )
  } catch (e: any) {
    errorMsg.value = e?.message ?? String(e)
  } finally {
    clearTimer()
    loading.value = false
  }
}

const screenplayDraft = computed({
  get: () => JSON.stringify(state.screenplay ?? {}, null, 2),
  set: (v: string) => {
    try {
      state.screenplay = JSON.parse(v)
    } catch {
      // ignore parse errors while user is typing
    }
  },
})

function handwriteScreenplay() {
  if (!state.screenplay) {
    state.screenplay = {
      chapters: [],
      main_characters: [],
      ending_md: '',
      opening_hook: '',
    }
  }
  editing.screenplay = true
}

// ---- step 6: finalize ----

const finalizing = ref(false)
const finalizeError = ref('')

async function doFinalize() {
  if (!state.world_brief || !state.character_md || !state.screenplay) {
    ElMessage.error('数据不完整，请回到对应步骤')
    return
  }
  finalizing.value = true
  finalizeError.value = ''
  try {
    const pinned = state.npcs.filter((n) => isPinned(n.name))
    const r = await wizardApi.finalize({
      world: {
        name: state.world_brief.name || state.session_name,
        content_md: state.world_md,
      },
      character: {
        name: state.character_name || '主角',
        profile_md: state.character_md,
      },
      pinned_npcs: pinned,
      screenplay: state.screenplay,
      session_name: state.session_name.trim(),
      gm_model_config_id: state.gm_model_config_id!,
      summarizer_model_config_id: state.summarizer_model_config_id!,
      genre: effectiveGenre.value,
    })
    clearDraft()
    router.push(`/play/${r.session_id}`)
  } catch (e: any) {
    finalizeError.value = e?.message ?? String(e)
  } finally {
    finalizing.value = false
  }
}

// ---- step 0: theme suggestions ----

const suggestions = ref<ThemeSuggestion[]>([])
const suggestLoading = ref(false)
const suggestError = ref('')

async function loadSuggestions() {
  if (!state.wizard_model_config_id) {
    ElMessage.warning('请先选择「向导用模型」再获取灵感推荐')
    return
  }
  suggestLoading.value = true
  suggestError.value = ''
  try {
    const r = await wizardApi.suggest({
      model_config_id: state.wizard_model_config_id,
      genre: state.genre !== '自定义' ? state.genre : '',
    })
    suggestions.value = r.suggestions
  } catch (e: any) {
    suggestError.value = e?.message ?? '生成失败'
  } finally {
    suggestLoading.value = false
  }
}

function applySuggestion(s: ThemeSuggestion) {
  state.genre = '自定义'
  state.custom_genre = s.genre
  state.theme = s.theme
  state.archetype = s.archetype
}

// ---- nav helpers ----

function gotoStep(n: number) {
  errorMsg.value = ''
  step.value = n
}

async function startStep1() {
  if (!setupValid()) {
    ElMessage.error('请先填齐设置项')
    return
  }
  gotoStep(1)
  await generateBrief()
}

async function acceptBriefAndNext() {
  if (!state.world_brief?.raw_md.trim()) {
    ElMessage.error('基础设定不能为空')
    return
  }
  saveDraft()
  gotoStep(2)
  if (!state.world_md) await generateWorldDetails()
}

async function acceptWorldAndNext() {
  if (!state.world_md.trim()) {
    ElMessage.error('世界观不能为空')
    return
  }
  saveDraft()
  gotoStep(3)
}

async function acceptCharacterAndNext() {
  if (!state.character_md.trim()) {
    ElMessage.error('角色卡不能为空')
    return
  }
  saveDraft()
  gotoStep(4)
  if (state.npcs.length === 0) await generateNpcs()
}

async function acceptNpcsAndNext() {
  gotoStep(5)
  if (!state.screenplay) await generateScreenplay()
}

function acceptScreenplayAndNext() {
  if (!state.screenplay) {
    ElMessage.error('剧本不能为空')
    return
  }
  gotoStep(6)
}

// ---- mount ----

onMounted(async () => {
  const restored = loadDraft()
  if (restored) {
    ElMessage.info('已恢复上次未完成的向导草稿。如需重新开始请刷新页面。')
  }
  if (modelsStore.items.length === 0) {
    await modelsStore.refresh()
  }
  // pre-fill defaults if available
  if (!restored && modelsStore.items.length > 0) {
    state.wizard_model_config_id = modelsStore.items[0].id
    state.gm_model_config_id = modelsStore.items[0].id
    state.summarizer_model_config_id = modelsStore.items[0].id
  }
})

onBeforeUnmount(() => {
  clearTimer()
})
</script>

<template>
  <div class="h-full overflow-auto bg-slate-50">
    <div class="max-w-3xl mx-auto p-6 space-y-6">
      <div>
        <div class="text-2xl font-bold text-slate-800">📜 创建新存档（向导）</div>
        <div class="text-sm text-slate-500 mt-1">
          一步一步生成世界、角色、NPC、剧本，最后开始跑团。每步都可以编辑或重新生成。
        </div>
      </div>

      <el-steps :active="step" finish-status="success" align-center>
        <el-step title="设置" />
        <el-step title="基础设定" />
        <el-step title="世界扩展" />
        <el-step title="主角" />
        <el-step title="主要 NPC" />
        <el-step title="剧本" />
        <el-step title="审阅" />
      </el-steps>

      <!-- ====== Step 0: setup ====== -->
      <div v-if="step === 0" class="space-y-4 bg-white border border-slate-200 rounded p-6">
        <div class="text-xl font-bold text-slate-800">⚙️ 设置</div>

        <div>
          <div class="text-sm font-medium text-slate-700 mb-1">向导用模型</div>
          <el-select
            v-model="state.wizard_model_config_id"
            placeholder="选择向导生成用的模型"
            class="w-full"
          >
            <el-option
              v-for="m in modelsStore.items"
              :key="m.id"
              :label="`${m.name} (${m.model_name})`"
              :value="m.id"
            />
          </el-select>
          <div class="text-xs text-slate-500 mt-1">
            💡 推荐：12B+ 思考型模型（qwen2.5:14b / deepseek-r1:7b）/ 云端 gpt-4o / claude-haiku。
            创建只跑一次，慢一点没事，质量优先。
          </div>
          <div v-if="state.wizard_model_config_id" class="mt-1.5 text-xs">
            <span v-if="wizardChecking" class="text-slate-400">检查中…</span>
            <span v-else-if="wizardModelOk === true" class="text-green-600">✓ 模型在线</span>
            <template v-else-if="wizardModelOk === false">
              <span class="text-red-600">✗ 模型不可用</span>
              <div v-for="cmd in wizardPullCmds" :key="cmd" class="font-mono bg-red-50 text-red-800 px-1.5 py-0.5 rounded mt-0.5">{{ cmd }}</div>
            </template>
          </div>
        </div>

        <div>
          <div class="text-sm font-medium text-slate-700 mb-1">跑团 GM 模型</div>
          <el-select
            v-model="state.gm_model_config_id"
            placeholder="选择跑团时 GM 用的模型"
            class="w-full"
          >
            <el-option
              v-for="m in modelsStore.items"
              :key="m.id"
              :label="`${m.name} (${m.model_name})`"
              :value="m.id"
            />
          </el-select>
          <div class="text-xs text-slate-500 mt-1">
            💡 推荐：7-8B 快速型（qwen2.5:7b / llama3.1:8b）够用；满血体验用云端 gpt-4o-mini / claude-haiku。
            跑团每回合都要调，速度优先。
          </div>
          <div v-if="state.gm_model_config_id" class="mt-1.5 text-xs">
            <span v-if="gmChecking" class="text-slate-400">检查中…</span>
            <span v-else-if="gmModelOk === true" class="text-green-600">✓ 模型在线（含 nomic-embed-text）</span>
            <template v-else-if="gmModelOk === false">
              <span class="text-red-600">✗ 缺少以下模型：</span>
              <div v-for="cmd in gmPullCmds" :key="cmd" class="font-mono bg-red-50 text-red-800 px-1.5 py-0.5 rounded mt-0.5">{{ cmd }}</div>
            </template>
          </div>
        </div>

        <div>
          <div class="text-sm font-medium text-slate-700 mb-1">摘要模型</div>
          <el-select
            v-model="state.summarizer_model_config_id"
            placeholder="选择摘要 / 编年史用的模型"
            class="w-full"
          >
            <el-option
              v-for="m in modelsStore.items"
              :key="m.id"
              :label="`${m.name} (${m.model_name})`"
              :value="m.id"
            />
          </el-select>
          <div class="text-xs text-slate-500 mt-1">
            💡 一般跟 GM 同一个就行。摘要任务比较轻。
          </div>
        </div>

        <div>
          <div class="text-sm font-medium text-slate-700 mb-1">题材</div>
          <el-select v-model="state.genre" class="w-full">
            <el-option
              v-for="g in KNOWN_GENRES"
              :key="g.key"
              :label="g.label"
              :value="g.key"
            />
          </el-select>
          <el-input
            v-if="state.genre === '自定义'"
            v-model="state.custom_genre"
            class="mt-2"
            placeholder="例如：赛博朋克、武侠、克苏鲁..."
          />
        </div>

        <div>
          <div class="text-sm font-medium text-slate-700 mb-1">主题（一句话）</div>
          <el-input
            v-model="state.theme"
            type="textarea"
            :autosize="{ minRows: 2, maxRows: 4 }"
            placeholder="例如：一座被永夜笼罩的港口，一个寻找妹妹的赏金猎人"
            maxlength="500"
            show-word-limit
          />
        </div>

        <!-- AI 灵感推荐 -->
        <div class="border border-slate-200 rounded-lg p-3 bg-slate-50">
          <div class="flex items-center justify-between mb-2">
            <div class="text-sm font-medium text-slate-700">✨ AI 灵感推荐</div>
            <el-button
              size="small"
              :loading="suggestLoading"
              @click="loadSuggestions"
            >{{ suggestions.length ? '换一批' : '获取推荐' }}</el-button>
          </div>
          <div v-if="suggestError" class="text-xs text-red-500 mb-2">{{ suggestError }}</div>
          <div v-if="suggestLoading" class="text-xs text-slate-400 py-3 text-center">AI 正在构思故事方案…</div>
          <div v-else-if="suggestions.length" class="grid grid-cols-2 gap-2">
            <button
              v-for="(s, i) in suggestions"
              :key="i"
              type="button"
              class="text-left p-2.5 bg-white border border-slate-200 rounded-lg hover:border-blue-400 hover:bg-blue-50 transition-colors cursor-pointer"
              @click="applySuggestion(s)"
            >
              <div class="flex items-center gap-1.5 mb-1">
                <el-tag size="small" type="info" effect="plain">{{ s.genre }}</el-tag>
              </div>
              <div class="text-xs text-slate-700 leading-5 mb-1.5">{{ s.theme }}</div>
              <div class="text-xs text-slate-400">主角：{{ s.archetype }}</div>
            </button>
          </div>
          <div v-else class="text-xs text-slate-400 text-center py-2">
            点「获取推荐」让 AI 生成题材+主题+主角原型套餐，点击即可一键填入
          </div>
        </div>

        <div>
          <div class="text-sm font-medium text-slate-700 mb-1">存档名</div>
          <el-input
            v-model="state.session_name"
            placeholder="给这个存档起个名字"
            maxlength="60"
            show-word-limit
          />
        </div>

        <div class="flex gap-2 pt-2">
          <el-button @click="router.push('/sessions')">取消</el-button>
          <div class="flex-1" />
          <el-button type="primary" :disabled="!setupValid()" @click="startStep1">
            ⏩ 开始生成 →
          </el-button>
        </div>
      </div>

      <!-- ====== Step 1: world brief ====== -->
      <WizardStep
        v-if="step === 1"
        title="🌍 第 1 步 / 基础设定"
        :loading="loading"
        :elapsed="elapsed"
        :tip="currentTip"
        :error="errorMsg"
        :editing="editing.brief"
        :stream-text="streamText.brief"
        :content="state.world_brief?.raw_md ?? ''"
        @update:content="(v) => state.world_brief && (state.world_brief.raw_md = v)"
        @edit="editing.brief = true"
        @regenerate="generateBrief"
        @handwrite="handwriteBrief"
        @accept="acceptBriefAndNext"
        @back="gotoStep(0)"
        @retry="generateBrief"
      >
        <!-- Prompt inputs always visible so user can tweak before regenerating -->
        <div class="mb-4 p-3 bg-slate-50 rounded border border-slate-200 space-y-2">
          <div class="text-xs font-medium text-slate-500">提示词（修改后点「重新生成」）</div>
          <div class="flex items-center gap-2">
            <span class="text-xs text-slate-500 w-10 shrink-0">题材</span>
            <el-select v-model="state.genre" size="small" class="w-36 shrink-0">
              <el-option v-for="g in KNOWN_GENRES" :key="g.key" :label="g.label" :value="g.key" />
            </el-select>
          </div>
          <el-input
            v-if="state.genre === '自定义'"
            v-model="state.custom_genre"
            size="small"
            placeholder="自定义题材…"
          />
          <div class="flex items-start gap-2">
            <span class="text-xs text-slate-500 w-10 shrink-0 pt-1">主题</span>
            <el-input
              v-model="state.theme"
              type="textarea"
              :autosize="{ minRows: 1, maxRows: 4 }"
              size="small"
              placeholder="一句话主题提示…"
            />
          </div>
        </div>
        <div v-if="state.world_brief" class="space-y-3">
          <div>
            <div class="text-xs text-slate-500">世界名</div>
            <div class="text-lg font-bold text-slate-800">{{ state.world_brief.name }}</div>
          </div>
          <div>
            <div class="text-xs text-slate-500">设定</div>
            <MarkdownView :source="state.world_brief.setting" />
          </div>
          <div>
            <div class="text-xs text-slate-500">核心冲突</div>
            <MarkdownView :source="state.world_brief.conflict" />
          </div>
        </div>
        <!-- Debug: raw LLM output toggle -->
        <div v-if="state.raw_outputs['world_brief']" class="mt-3 border-t pt-2">
          <button
            class="text-xs text-slate-400 hover:text-slate-600"
            @click="showRawKey = showRawKey === 'world_brief' ? null : 'world_brief'"
          >
            🐛 原始输出 {{ showRawKey === 'world_brief' ? '▲' : '▼' }}
          </button>
          <pre v-if="showRawKey === 'world_brief'" class="mt-2 text-xs bg-slate-100 p-2 rounded overflow-auto max-h-48 whitespace-pre-wrap">{{ state.raw_outputs['world_brief'] }}</pre>
        </div>
      </WizardStep>

      <!-- ====== Step 2: world details ====== -->
      <WizardStep
        v-if="step === 2"
        title="🗺️ 第 2 步 / 世界扩展"
        :loading="loading"
        :elapsed="elapsed"
        :tip="currentTip"
        :error="errorMsg"
        :editing="editing.world"
        :stream-text="streamText.world"
        :content="state.world_md"
        @update:content="(v) => (state.world_md = v)"
        @edit="editing.world = true"
        @regenerate="generateWorldDetails"
        @handwrite="handwriteWorld"
        @accept="acceptWorldAndNext"
        @back="gotoStep(1)"
        @retry="generateWorldDetails"
      >
        <MarkdownView :source="state.world_md" />
        <!-- Debug: raw LLM output toggle -->
        <div v-if="state.raw_outputs['world_details']" class="mt-3 border-t pt-2">
          <button
            class="text-xs text-slate-400 hover:text-slate-600"
            @click="showRawKey = showRawKey === 'world_details' ? null : 'world_details'"
          >
            🐛 原始输出 {{ showRawKey === 'world_details' ? '▲' : '▼' }}
          </button>
          <pre v-if="showRawKey === 'world_details'" class="mt-2 text-xs bg-slate-100 p-2 rounded overflow-auto max-h-48 whitespace-pre-wrap">{{ state.raw_outputs['world_details'] }}</pre>
        </div>
      </WizardStep>

      <!-- ====== Step 3: character ====== -->
      <WizardStep
        v-if="step === 3"
        title="🎭 第 3 步 / 主角"
        :loading="loading"
        :elapsed="elapsed"
        :tip="currentTip"
        :error="errorMsg"
        :editing="editing.character"
        :stream-text="streamText.character"
        :content="state.character_md"
        :can-regenerate="!!state.archetype.trim()"
        :accept-label="state.character_md ? '⏩ 接受继续' : '⏩ 生成角色卡'"
        @update:content="(v) => (state.character_md = v)"
        @edit="editing.character = true"
        @regenerate="generateCharacter"
        @handwrite="handwriteCharacter"
        @accept="state.character_md ? acceptCharacterAndNext() : generateCharacter()"
        @back="gotoStep(2)"
        @retry="generateCharacter"
      >
        <!-- Archetype prompt always visible so user can tweak before regenerating -->
        <div class="mb-4 p-3 bg-slate-50 rounded border border-slate-200 space-y-2">
          <div class="text-xs font-medium text-slate-500">角色原型提示词（修改后点「重新生成」）</div>
          <el-input
            v-model="state.archetype"
            type="textarea"
            :autosize="{ minRows: 2, maxRows: 4 }"
            placeholder="例如：外冷内热的赏金猎人 / 失忆的前王国骑士 / 想找回弟弟的小镇医生"
            maxlength="200"
            show-word-limit
          />
        </div>
        <div v-if="state.character_md" class="space-y-3">
          <div v-if="state.character_name">
            <div class="text-xs text-slate-500">角色名</div>
            <div class="text-lg font-bold text-slate-800">{{ state.character_name }}</div>
          </div>
          <MarkdownView :source="state.character_md" />
        </div>
        <div v-else class="text-sm text-slate-400 text-center py-4">
          填写原型后点「⏩ 生成角色卡」
        </div>
        <!-- Debug: raw LLM output toggle -->
        <div v-if="state.raw_outputs['character']" class="mt-3 border-t pt-2">
          <button
            class="text-xs text-slate-400 hover:text-slate-600"
            @click="showRawKey = showRawKey === 'character' ? null : 'character'"
          >
            🐛 原始输出 {{ showRawKey === 'character' ? '▲' : '▼' }}
          </button>
          <pre v-if="showRawKey === 'character'" class="mt-2 text-xs bg-slate-100 p-2 rounded overflow-auto max-h-48 whitespace-pre-wrap">{{ state.raw_outputs['character'] }}</pre>
        </div>
      </WizardStep>

      <!-- ====== Step 4: NPCs ====== -->
      <WizardStep
        v-if="step === 4"
        title="🎭 第 4 步 / 主要 NPC"
        :loading="loading"
        :elapsed="elapsed"
        :tip="currentTip"
        :error="errorMsg"
        :editing="false"
        :stream-text="streamText.npcs"
        :can-edit="false"
        :can-handwrite="false"
        @regenerate="generateNpcs"
        @accept="acceptNpcsAndNext"
        @back="gotoStep(3)"
        @retry="generateNpcs"
      >
        <div class="space-y-3">
          <div class="text-sm text-slate-600">
            勾选「📌 钉住」的 NPC 会写入剧本（默认全选）。点单个 NPC 旁的 ✏️ 可以改详情。
          </div>
          <el-card
            v-for="(npc, i) in state.npcs"
            :key="`${npc.name}-${i}`"
            shadow="never"
            class="!border-slate-200"
          >
            <div class="flex items-start gap-3">
              <el-checkbox
                :model-value="isPinned(npc.name)"
                @change="togglePinNpc(npc.name)"
              />
              <div class="flex-1 space-y-1">
                <div class="flex items-center gap-2">
                  <div class="font-bold text-slate-800">{{ npc.name }}</div>
                  <el-tag size="small" type="info">{{ npc.role }}</el-tag>
                </div>
                <div class="text-sm text-slate-700">{{ npc.description }}</div>
                <div class="text-xs text-slate-500">动机：{{ npc.motivation }}</div>
              </div>
              <el-button size="small" @click="openNpcEdit(i)">✏️</el-button>
              <el-button size="small" type="danger" @click="deleteNpc(i)">🗑️</el-button>
            </div>
          </el-card>
          <div v-if="state.npcs.length === 0" class="text-sm text-slate-500">
            （还没生成 NPC）
          </div>
          <!-- Add NPC actions -->
          <div class="flex gap-2 mt-3">
            <el-button size="small" @click="npcHintDialog = true" :loading="npcGenerating">✨ AI 生成一个</el-button>
            <el-button size="small" @click="addBlankNpc">📝 手动添加</el-button>
          </div>
        </div>
        <!-- Debug: raw LLM output toggle -->
        <div v-if="state.raw_outputs['npcs']" class="mt-3 border-t pt-2">
          <button
            class="text-xs text-slate-400 hover:text-slate-600"
            @click="showRawKey = showRawKey === 'npcs' ? null : 'npcs'"
          >
            🐛 原始输出 {{ showRawKey === 'npcs' ? '▲' : '▼' }}
          </button>
          <pre v-if="showRawKey === 'npcs'" class="mt-2 text-xs bg-slate-100 p-2 rounded overflow-auto max-h-48 whitespace-pre-wrap">{{ state.raw_outputs['npcs'] }}</pre>
        </div>
      </WizardStep>

      <!-- AI generate single NPC dialog -->
      <el-dialog v-model="npcHintDialog" title="AI 生成 NPC" width="400px">
        <el-input
          v-model="npcHint"
          placeholder="描述这个 NPC（如：一个神秘的黑市商人）"
        />
        <template #footer>
          <el-button @click="npcHintDialog = false">取消</el-button>
          <el-button type="primary" :loading="npcGenerating" @click="aiGenerateSingleNpc">生成</el-button>
        </template>
      </el-dialog>

      <!-- NPC edit dialog -->
      <el-dialog v-model="npcEditDialog.open" title="编辑 NPC" width="500px">
        <div class="space-y-3">
          <div>
            <div class="text-xs text-slate-500 mb-1">名字</div>
            <el-input v-model="npcEditDialog.draft.name" />
          </div>
          <div>
            <div class="text-xs text-slate-500 mb-1">角色（如：盟友、对手、引路人）</div>
            <el-input v-model="npcEditDialog.draft.role" />
          </div>
          <div>
            <div class="text-xs text-slate-500 mb-1">描述</div>
            <el-input
              v-model="npcEditDialog.draft.description"
              type="textarea"
              :autosize="{ minRows: 3, maxRows: 6 }"
            />
          </div>
          <div>
            <div class="text-xs text-slate-500 mb-1">动机</div>
            <el-input
              v-model="npcEditDialog.draft.motivation"
              type="textarea"
              :autosize="{ minRows: 2, maxRows: 4 }"
            />
          </div>
        </div>
        <template #footer>
          <el-button @click="npcEditDialog.open = false">取消</el-button>
          <el-button type="primary" @click="saveNpcEdit">保存</el-button>
        </template>
      </el-dialog>

      <!-- ====== Step 5: screenplay ====== -->
      <WizardStep
        v-if="step === 5"
        title="📜 第 5 步 / 剧本大纲"
        :loading="loading"
        :elapsed="elapsed"
        :tip="currentTip"
        :error="errorMsg"
        :editing="editing.screenplay"
        :stream-text="streamText.screenplay"
        :content="screenplayDraft"
        @update:content="(v) => (screenplayDraft = v)"
        @edit="editing.screenplay = true"
        @regenerate="generateScreenplay"
        @handwrite="handwriteScreenplay"
        @accept="acceptScreenplayAndNext"
        @back="gotoStep(4)"
        @retry="generateScreenplay"
      >
        <div v-if="state.screenplay" class="space-y-4">
          <div>
            <div class="text-xs text-slate-500">开场钩子</div>
            <div class="bg-slate-50 border border-slate-200 rounded p-3 mt-1">
              <MarkdownView :source="state.screenplay.opening_hook" />
            </div>
          </div>

          <div>
            <div class="text-xs text-slate-500 mb-1">章节（{{ state.screenplay.chapters.length }} 章）</div>
            <div class="space-y-2">
              <el-card
                v-for="(ch, i) in state.screenplay.chapters"
                :key="i"
                shadow="never"
                class="!border-slate-200"
              >
                <div class="font-bold text-slate-800">
                  第 {{ i + 1 }} 章：{{ ch.title || '（未命名）' }}
                </div>
                <div class="text-sm text-slate-600 mt-1">{{ ch.summary }}</div>
                <div v-if="ch.main_events?.length" class="text-xs text-slate-500 mt-2">
                  主线：{{ (ch.main_events || []).join(' / ') }}
                </div>
                <div v-if="ch.optional_events?.length" class="text-xs text-slate-400 mt-1">
                  支线：{{ (ch.optional_events || []).join(' / ') }}
                </div>
              </el-card>
            </div>
          </div>

          <div v-if="state.screenplay.main_characters?.length">
            <div class="text-xs text-slate-500 mb-1">出场角色</div>
            <div class="flex flex-wrap gap-1">
              <el-tag
                v-for="(c, i) in state.screenplay.main_characters"
                :key="i"
                size="small"
              >
                {{ c.name }}<span v-if="c.role"> · {{ c.role }}</span>
              </el-tag>
            </div>
          </div>

          <div v-if="state.screenplay.ending_md || state.screenplay.ending">
            <div class="text-xs text-slate-500">结局</div>
            <div class="bg-slate-50 border border-slate-200 rounded p-3 mt-1">
              <MarkdownView :source="state.screenplay.ending_md || state.screenplay.ending || ''" />
            </div>
          </div>
        </div>
        <!-- Debug: raw LLM output toggle -->
        <div v-if="state.raw_outputs['screenplay']" class="mt-3 border-t pt-2">
          <button
            class="text-xs text-slate-400 hover:text-slate-600"
            @click="showRawKey = showRawKey === 'screenplay' ? null : 'screenplay'"
          >
            🐛 原始输出 {{ showRawKey === 'screenplay' ? '▲' : '▼' }}
          </button>
          <pre v-if="showRawKey === 'screenplay'" class="mt-2 text-xs bg-slate-100 p-2 rounded overflow-auto max-h-48 whitespace-pre-wrap">{{ state.raw_outputs['screenplay'] }}</pre>
        </div>
      </WizardStep>

      <!-- ====== Step 6: review + finalize ====== -->
      <div v-if="step === 6" class="space-y-4">
        <div class="text-xl font-bold text-slate-800">✅ 第 6 步 / 审阅 + 创建</div>
        <div class="text-sm text-slate-600">
          这次创建会落地：1 个 World + 1 个 Character +
          {{ state.npcs.filter((n) => isPinned(n.name)).length }} 个 NPC + 1 个
          Session + 1 个 Screenplay。
        </div>

        <el-card shadow="never" class="!border-slate-200">
          <template #header>
            <div class="font-bold">🌍 世界 · {{ state.world_brief?.name || '（未命名）' }}</div>
          </template>
          <div class="text-sm text-slate-700 max-h-40 overflow-y-auto">
            <MarkdownView :source="state.world_md.slice(0, 800) + (state.world_md.length > 800 ? '...' : '')" />
          </div>
        </el-card>

        <el-card shadow="never" class="!border-slate-200">
          <template #header>
            <div class="font-bold">🎭 主角 · {{ state.character_name }}</div>
          </template>
          <div class="text-sm text-slate-700 max-h-40 overflow-y-auto">
            <MarkdownView :source="state.character_md.slice(0, 600) + (state.character_md.length > 600 ? '...' : '')" />
          </div>
        </el-card>

        <el-card shadow="never" class="!border-slate-200">
          <template #header>
            <div class="font-bold">
              📌 钉住的 NPC ·
              {{ state.npcs.filter((n) => isPinned(n.name)).length }}
              / {{ state.npcs.length }}
            </div>
          </template>
          <div class="space-y-2">
            <div
              v-for="npc in state.npcs.filter((n) => isPinned(n.name))"
              :key="npc.name"
              class="text-sm"
            >
              <span class="font-bold text-slate-800">{{ npc.name }}</span>
              <el-tag size="small" type="info" class="ml-2">{{ npc.role }}</el-tag>
              <span class="text-slate-600 ml-2">{{ npc.description }}</span>
            </div>
            <div v-if="state.npcs.filter((n) => isPinned(n.name)).length === 0" class="text-xs text-slate-400">
              （没有钉住任何 NPC）
            </div>
          </div>
        </el-card>

        <el-card shadow="never" class="!border-slate-200">
          <template #header>
            <div class="font-bold">
              📜 剧本 · {{ state.screenplay?.chapters?.length ?? 0 }} 章
            </div>
          </template>
          <div class="text-sm text-slate-700">
            <div v-if="state.screenplay?.opening_hook" class="bg-slate-50 border border-slate-200 rounded p-2 mb-2 text-xs">
              开场：{{ state.screenplay.opening_hook.slice(0, 200) }}{{ state.screenplay.opening_hook.length > 200 ? '...' : '' }}
            </div>
            <ul class="list-decimal list-inside space-y-1">
              <li v-for="(ch, i) in state.screenplay?.chapters ?? []" :key="i">
                {{ ch.title || `第 ${i + 1} 章` }}
              </li>
            </ul>
          </div>
        </el-card>

        <div v-if="finalizeError" class="text-sm text-red-600 break-words">
          {{ finalizeError }}
        </div>

        <div class="flex gap-2">
          <el-button :disabled="finalizing" @click="gotoStep(5)">⬅ 返回</el-button>
          <div class="flex-1" />
          <el-button
            type="primary"
            size="large"
            :loading="finalizing"
            @click="doFinalize"
          >
            📜 创建并开始跑团
          </el-button>
        </div>
      </div>
    </div>
  </div>
</template>
