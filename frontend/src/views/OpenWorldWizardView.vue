<script setup lang="ts">
import { ref, reactive, computed, watch, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { frameworkApi } from '@/api/framework'
import type {
  FwLocationInput, FwFactionInput, FwNpcTemplateInput,
  FwEventInput, FwCampaignInput, FwFinalizePayload,
} from '@/api/framework'
import { wizardApi } from '@/api/wizard'
import { worldsApi } from '@/api/worlds'
import { charactersApi } from '@/api/characters'
import { sessionsApi } from '@/api/sessions'
import { useModelConfigsStore } from '@/stores/modelConfigs'
import MarkdownView from '@/components/MarkdownView.vue'

const router = useRouter()
const modelStore = useModelConfigsStore()

// localStorage draft key — survives app restart / browser refresh.
// Cleared when wizard finalizes successfully.
const DRAFT_KEY = 'dzmm.openWorldWizard.draft'

const step = ref(0)
const loading = ref(false)
const hints = reactive<Record<number, string>>({})

const state = reactive({
  genre: '悬疑探案',
  model_config_id: 0,   // 0 = use preferred default; user can pick a specific one in step 0
  world_brief_md: '',
  world_name: '',
  locations: [] as FwLocationInput[],
  factions: [] as FwFactionInput[],
  npc_templates: [] as FwNpcTemplateInput[],
  events: [] as FwEventInput[],
  campaign: null as FwCampaignInput | null,
  include_campaign: false,
  character_name: '',
  character_profile_md: '',
})

// Save draft to localStorage whenever state, step, or hints change.
// `draftReady` gates the watch so we don't OVERWRITE the saved draft
// with an empty state during the initial mount, BEFORE the user has
// had a chance to choose "continue" vs "start fresh".
const draftReady = ref(false)

function saveDraft() {
  if (!draftReady.value) return  // see comment above
  try {
    localStorage.setItem(DRAFT_KEY, JSON.stringify({
      step: step.value,
      state: { ...state },
      hints: { ...hints },
      savedAt: new Date().toISOString(),
    }))
    console.log('[wizard] draft saved', { step: step.value })
  } catch (e) {
    console.warn('[wizard] saveDraft failed', e)
  }
}

// Use getter form so each ref/reactive is tracked individually + deep
watch(
  () => [step.value, JSON.stringify(state), JSON.stringify(hints)],
  saveDraft,
)

function clearDraft() {
  try { localStorage.removeItem(DRAFT_KEY) } catch { /* ignore */ }
  console.log('[wizard] draft cleared')
}

function hasDraft(): boolean {
  try { return !!localStorage.getItem(DRAFT_KEY) } catch { return false }
}

function loadDraft() {
  try {
    const raw = localStorage.getItem(DRAFT_KEY)
    if (!raw) {
      console.warn('[wizard] loadDraft: localStorage empty')
      return
    }
    const d = JSON.parse(raw)
    console.log('[wizard] loadDraft: parsed', {
      step: d.step,
      world_name: d.state?.world_name,
      locations: d.state?.locations?.length ?? 0,
      factions: d.state?.factions?.length ?? 0,
      npc_templates: d.state?.npc_templates?.length ?? 0,
      events: d.state?.events?.length ?? 0,
      character_name: d.state?.character_name,
    })
    if (d.state && typeof d.state === 'object') {
      Object.assign(state, d.state)
    }
    if (d.hints && typeof d.hints === 'object') {
      Object.assign(hints, d.hints)
    }
    // step LAST so v-if doesn't tear down already-restored content
    if (typeof d.step === 'number') step.value = d.step
  } catch (e) {
    console.warn('[wizard] loadDraft failed', e)
  }
}

onMounted(async () => {
  console.log('[wizard] mount; hasDraft=', hasDraft())

  // Initialize default model FIRST so saved model_config_id (loaded below)
  // can override it without race.
  if (!state.model_config_id) {
    await modelStore.refresh()
    state.model_config_id = modelStore.preferredId() ?? 0
  }

  if (hasDraft()) {
    try {
      const raw = localStorage.getItem(DRAFT_KEY)
      const d = raw ? JSON.parse(raw) : null
      const savedAt = d?.savedAt ? new Date(d.savedAt).toLocaleString('zh-CN') : '未知时间'
      const stepLabel = STEP_LABELS[d?.step ?? 0] ?? `第 ${d?.step ?? 0} 步`
      await ElMessageBox.confirm(
        `检测到上次未完成的世界草稿（保存于 ${savedAt}，进度：${stepLabel}）。\n是否继续？`,
        '恢复上次草稿',
        {
          confirmButtonText: '继续上次',
          cancelButtonText: '从头开始',
          type: 'info',
        },
      )
      loadDraft()
      ElMessage.success(`已恢复到「${stepLabel}」`)
    } catch {
      // User chose to start fresh
      clearDraft()
    }
  }

  // Now allow the auto-save watch to fire. Any further changes get persisted.
  draftReady.value = true
})

async function resetWizard() {
  try {
    await ElMessageBox.confirm(
      '清空所有草稿并从头开始？已生成的地点 / 势力 / NPC 等会全部丢失。',
      '确认清空',
      { confirmButtonText: '清空', cancelButtonText: '取消', type: 'warning' },
    )
  } catch {
    return
  }
  clearDraft()
  step.value = 0
  state.genre = '悬疑探案'
  state.world_brief_md = ''
  state.world_name = ''
  state.locations = []
  state.factions = []
  state.npc_templates = []
  state.events = []
  state.campaign = null
  state.include_campaign = false
  state.character_name = ''
  state.character_profile_md = ''
  for (const k in hints) delete hints[Number(k)]
  ElMessage.success('已清空')
}

// Bug 6: clear stale campaign when user unchecks include_campaign
watch(() => state.include_campaign, (newVal) => {
  if (!newVal) state.campaign = null
})

// ─── CRUD dialog ───────────────────────────────────────────────────────────────
type DialogKind = 'location' | 'faction' | 'npc' | 'event'

interface EditDialog {
  visible: boolean
  kind: DialogKind
  mode: 'add' | 'edit'
  index: number
  draft: any
}

const editDialog = reactive<EditDialog>({
  visible: false,
  kind: 'location',
  mode: 'add',
  index: -1,
  draft: {},
})

function blankLocation(): FwLocationInput {
  return { name: '', description_md: '', location_type: 'city', connections: [], initial_state: 'normal' }
}

function blankFaction(): FwFactionInput {
  return {
    name: '', description_md: '',
    rival_faction_names: [], ally_faction_names: [],
    tension_rules: { passive_gain_per_turn: 1, threshold_conflict: 50 },
  }
}

function blankNpc(): FwNpcTemplateInput {
  return {
    name: '', gender: '', role: '', description_md: '', motivation: '',
    home_location_name: '', faction_name: null,
    contact_favor_threshold: 70, contact_cooldown_turns: 10,
    speech_pattern: '',
  }
}

function blankEvent(): FwEventInput {
  return {
    name: '', summary_md: '', scope_type: 'global',
    scope_location_name: null, scope_faction_name: null,
    importance: 3, is_repeatable: false, cooldown_turns: 0,
    trigger_conditions: [],
  }
}

function openAdd(kind: DialogKind) {
  editDialog.kind = kind
  editDialog.mode = 'add'
  editDialog.index = -1
  if (kind === 'location') editDialog.draft = blankLocation()
  else if (kind === 'faction') editDialog.draft = blankFaction()
  else if (kind === 'npc') editDialog.draft = blankNpc()
  else editDialog.draft = blankEvent()
  editDialog.visible = true
}

function openEdit(kind: DialogKind, index: number) {
  editDialog.kind = kind
  editDialog.mode = 'edit'
  editDialog.index = index
  if (kind === 'location') {
    editDialog.draft = { ...state.locations[index] }
  } else if (kind === 'faction') {
    const f = state.factions[index]
    editDialog.draft = {
      ...f,
      rival_faction_names: [...f.rival_faction_names],
      ally_faction_names: [...f.ally_faction_names],
      tension_rules: { ...(f.tension_rules ?? { passive_gain_per_turn: 1, threshold_conflict: 50 }) },
    }
  } else if (kind === 'npc') {
    editDialog.draft = { ...state.npc_templates[index] }
  } else {
    editDialog.draft = { ...state.events[index] }
  }
  editDialog.visible = true
}

function saveDialog() {
  const d = editDialog.draft
  if (!d.name?.trim()) {
    ElMessage.warning('名称不能为空')
    return
  }
  if (editDialog.mode === 'add') {
    if (editDialog.kind === 'location') state.locations.push({ ...d })
    else if (editDialog.kind === 'faction') state.factions.push({ ...d, rival_faction_names: [...d.rival_faction_names], ally_faction_names: [...d.ally_faction_names] })
    else if (editDialog.kind === 'npc') state.npc_templates.push({ ...d })
    else state.events.push({ ...d })
    ElMessage.success('已新增')
  } else {
    const idx = editDialog.index
    if (editDialog.kind === 'location') state.locations.splice(idx, 1, { ...d })
    else if (editDialog.kind === 'faction') state.factions.splice(idx, 1, { ...d, rival_faction_names: [...d.rival_faction_names], ally_faction_names: [...d.ally_faction_names] })
    else if (editDialog.kind === 'npc') state.npc_templates.splice(idx, 1, { ...d })
    else state.events.splice(idx, 1, { ...d })
    ElMessage.success('已保存')
  }
  editDialog.visible = false
}

async function deleteItem(kind: DialogKind, index: number) {
  try {
    await ElMessageBox.confirm('确认删除？', '删除确认', {
      confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning',
    })
  } catch { return }
  if (kind === 'location') state.locations.splice(index, 1)
  else if (kind === 'faction') state.factions.splice(index, 1)
  else if (kind === 'npc') state.npc_templates.splice(index, 1)
  else state.events.splice(index, 1)
  ElMessage.success('已删除')
}

function factionNamesExcluding(selfName: string) {
  return state.factions.map(f => f.name).filter(n => n !== selfName)
}

function importanceStars(n: number) {
  return '★'.repeat(Math.min(Math.max(n, 1), 5))
}

// User-picked model takes precedence; falls back to preferred (default).
// Initialization is done inside the main onMounted above (so draft load
// can override the default cleanly without race).
const modelConfigId = computed(() => state.model_config_id || modelStore.preferredId())

async function generate(stepNum: number) {
  if (!modelConfigId.value) {
    ElMessage.error('请先配置 LLM 模型')
    return
  }
  loading.value = true
  const usedHint = hints[stepNum] || ''
  try {
    const hint = usedHint ? `\n\n用户引导：${usedHint}` : ''
    const brief = state.world_brief_md + hint

    if (stepNum === 1) {
      const r = await wizardApi.worldBrief({
        model_config_id: modelConfigId.value,
        genre: state.genre,
        theme: hints[1] || '',
      })
      state.world_brief_md = r.raw_md
      state.world_name = r.name
    } else if (stepNum === 2) {
      state.locations = await frameworkApi.generateLocations({
        model_config_id: modelConfigId.value,
        genre: state.genre,
        world_brief_md: brief,
      })
    } else if (stepNum === 3) {
      state.factions = await frameworkApi.generateFactions({
        model_config_id: modelConfigId.value,
        genre: state.genre,
        world_brief_md: brief,
        locations: state.locations,
      })
    } else if (stepNum === 4) {
      state.npc_templates = await frameworkApi.generateNpcTemplates({
        model_config_id: modelConfigId.value,
        genre: state.genre,
        world_brief_md: brief,
        locations: state.locations,
        factions: state.factions,
      })
    } else if (stepNum === 5) {
      state.events = await frameworkApi.generateEvents({
        model_config_id: modelConfigId.value,
        genre: state.genre,
        world_brief_md: brief,
        locations: state.locations,
        factions: state.factions,
        npc_templates: state.npc_templates,
      })
    } else if (stepNum === 6) {
      const r = await wizardApi.fwCharacter({
        model_config_id: modelConfigId.value,
        world_md: state.world_brief_md + hint,
        archetype: hints[6] || '侦探',
      })
      state.character_name = r.name
      state.character_profile_md = r.profile_md
    } else if (stepNum === 7 && state.include_campaign) {
      state.campaign = await frameworkApi.generateCampaign({
        model_config_id: modelConfigId.value,
        genre: state.genre,
        world_brief_md: brief,
        events: state.events,
      })
    }
    // Bug 7: clear hint after successful generation; toast if one was used
    if (usedHint) {
      ElMessage.success(`已应用引导词「${usedHint}」`)
    }
    hints[stepNum] = ''
  } catch (e: unknown) {
    ElMessage.error(`生成失败：${e instanceof Error ? e.message : String(e)}`)
  } finally {
    loading.value = false
  }
}

async function finalize() {
  if (!modelConfigId.value) return
  loading.value = true
  try {
    let phase = 'framework'
    try {
      // 1. 提交 WorldFramework（地点/势力/NPC/事件/主线）
      const payload: FwFinalizePayload = {
        name: state.world_name,
        genre: state.genre,
        style: '',
        description_md: state.world_brief_md,
        locations: state.locations,
        factions: state.factions,
        npc_templates: state.npc_templates,
        events: state.events,
        campaign: state.include_campaign ? state.campaign : null,
      }
      const { framework_id } = await frameworkApi.finalize(payload)

      // 2. 创建 World（存储世界观文本）
      phase = 'world'
      const world = await worldsApi.create({
        name: state.world_name || state.genre,
        content_md: state.world_brief_md,
        style: state.genre,
        rules_mode: 'simple',
      })

      // 3. 创建 Character
      phase = 'character'
      const character = await charactersApi.create({
        world_id: world.id,
        name: state.character_name || '主角',
        gender: '',
        profile_md: state.character_profile_md,
        base_stats_json: '{}',
      })

      // 4. 创建 Session，绑定 framework_id
      phase = 'session'
      const session = await sessionsApi.create({
        name: `${state.world_name || state.genre} · ${state.character_name || '主角'}`,
        world_id: world.id,
        character_id: character.id,
        framework_id,
        gm_model_config_id: modelConfigId.value,
        summarizer_model_config_id: modelConfigId.value,
      })

      ElMessage.success('开放世界存档创建成功！')
      clearDraft()  // wizard succeeded — discard the local draft
      router.push(`/play/${session.id}`)
    } catch (e) {
      const stepLabel = ({
        framework: '世界框架',
        world: '世界条目',
        character: '角色',
        session: '存档',
      } as Record<string, string>)[phase]
      ElMessage.error(`创建${stepLabel}失败：${e instanceof Error ? e.message : String(e)}`)
      throw e  // let outer finally fire
    }
  } finally {
    loading.value = false
  }
}

const STEP_LABELS = [
  '基础设置', '世界简介', '地点网络', '势力', 'NPC模板', '事件库', '角色', '主线（可选）', '确认'
]
</script>

<template>
  <div class="ow-wizard">
    <h2>开放世界创建向导</h2>
    <el-steps :active="step" align-center style="margin-bottom: 24px">
      <el-step v-for="(label, i) in STEP_LABELS" :key="i" :title="label" />
    </el-steps>

    <!-- Step 0: Setup -->
    <el-card v-if="step === 0">
      <h3>选择 LLM 模型</h3>
      <div style="margin-bottom:8px; color:#909399; font-size:13px">
        向导生成 5-10 次 LLM 调用，本地小模型可能卡，建议大模型或云端。
      </div>
      <el-select v-model="state.model_config_id" placeholder="选择模型" style="width: 100%; margin-bottom: 20px">
        <el-option
          v-for="m in modelStore.items"
          :key="m.id"
          :label="`${m.name}（${m.model_name}）`"
          :value="m.id"
        />
      </el-select>

      <h3>选择类型</h3>
      <div style="display:flex; gap:12px; flex-wrap:wrap; margin-bottom:16px">
        <label
          v-for="g in ['悬疑探案', '英雄成长', '政治阴谋', '灾难求生', '恋爱攻略', '奇幻冒险', '赛博朋克', '东方武侠', '恐怖求生']"
          :key="g"
          class="genre-pill"
          :class="{ selected: state.genre === g }"
        >
          <input type="radio" :value="g" v-model="state.genre" style="display:none" />
          {{ g }}
        </label>
      </div>
      <el-input v-model="state.genre" placeholder="自定义类型" style="width:200px" />
    </el-card>

    <!-- Steps 1-7: Generation steps -->
    <el-card v-else-if="step >= 1 && step <= 7">
      <div class="step-regen-bar">
        <el-input v-model="hints[step]" :placeholder="`引导词（可选）`" style="flex:1" size="small" />
        <el-button size="small" :loading="loading" @click="generate(step)">↻ 重新生成</el-button>
      </div>

      <!-- Step 1: World brief -->
      <div v-if="step === 1">
        <MarkdownView v-if="state.world_brief_md" :source="state.world_brief_md" />
        <el-button v-else :loading="loading" @click="generate(1)">生成世界简介</el-button>
      </div>

      <!-- Step 2: Locations -->
      <div v-else-if="step === 2">
        <div v-if="!state.locations.length">
          <el-button :loading="loading" @click="generate(2)">生成地点网络</el-button>
        </div>
        <div v-else>
          <div class="card-grid">
            <div v-for="(loc, i) in state.locations" :key="i" class="fw-card">
              <div class="fw-card-header">
                <span class="fw-card-name">{{ loc.name }}</span>
                <span class="fw-badge" :class="`type-${loc.location_type}`">
                  {{ { city: '城镇', dungeon: '地下城', wilderness: '荒野', landmark: '地标' }[loc.location_type] ?? loc.location_type }}
                </span>
              </div>
              <p class="fw-card-desc">{{ loc.description_md }}</p>
              <div class="fw-card-meta">
                <span v-if="loc.connections.length">{{ loc.connections.length }} 个出口</span>
                <span v-else class="muted">0 个出口</span>
              </div>
              <div class="fw-card-actions">
                <el-button size="small" text @click="openEdit('location', i)">✏️ 编辑</el-button>
                <el-button size="small" text type="danger" @click="deleteItem('location', i)">🗑️</el-button>
              </div>
            </div>
          </div>
          <div class="add-btn-row">
            <el-button size="small" @click="openAdd('location')">➕ 新增地点</el-button>
          </div>
        </div>
      </div>

      <!-- Step 3: Factions -->
      <div v-else-if="step === 3">
        <div v-if="!state.factions.length">
          <el-button :loading="loading" @click="generate(3)">生成势力</el-button>
        </div>
        <div v-else>
          <div class="card-grid">
            <div v-for="(f, i) in state.factions" :key="i" class="fw-card">
              <div class="fw-card-header">
                <span class="fw-card-name">{{ f.name }}</span>
                <span class="fw-badge type-faction">势力</span>
              </div>
              <p class="fw-card-desc">{{ f.description_md }}</p>
              <div class="fw-card-meta">
                <span v-if="f.ally_faction_names.length">盟友 {{ f.ally_faction_names.length }}</span>
                <span v-if="f.rival_faction_names.length">对立 {{ f.rival_faction_names.length }}</span>
                <span v-if="f.tension_rules" class="tension-hint">张力 +{{ f.tension_rules.passive_gain_per_turn }}/回合, 阈值 {{ f.tension_rules.threshold_conflict }}</span>
              </div>
              <div class="fw-card-actions">
                <el-button size="small" text @click="openEdit('faction', i)">✏️ 编辑</el-button>
                <el-button size="small" text type="danger" @click="deleteItem('faction', i)">🗑️</el-button>
              </div>
            </div>
          </div>
          <div class="add-btn-row">
            <el-button size="small" @click="openAdd('faction')">➕ 新增势力</el-button>
          </div>
        </div>
      </div>

      <!-- Step 4: NPC Templates -->
      <div v-else-if="step === 4">
        <div v-if="!state.npc_templates.length">
          <el-button :loading="loading" @click="generate(4)">生成NPC模板</el-button>
        </div>
        <div v-else>
          <div class="card-grid">
            <div v-for="(n, i) in state.npc_templates" :key="i" class="fw-card">
              <div class="fw-card-header">
                <span class="fw-card-name">{{ n.name }}</span>
                <span class="fw-badge type-npc">{{ n.gender === 'male' ? '男' : n.gender === 'female' ? '女' : '?' }} · {{ n.role }}</span>
              </div>
              <p class="fw-card-desc">{{ n.description_md }}</p>
              <em v-if="n.speech_pattern" class="fw-speech-pattern">「{{ n.speech_pattern }}」</em>
              <div class="fw-card-meta">📍 {{ n.home_location_name }}</div>
              <div class="fw-card-actions">
                <el-button size="small" text @click="openEdit('npc', i)">✏️ 编辑</el-button>
                <el-button size="small" text type="danger" @click="deleteItem('npc', i)">🗑️</el-button>
              </div>
            </div>
          </div>
          <div class="add-btn-row">
            <el-button size="small" @click="openAdd('npc')">➕ 新增NPC</el-button>
          </div>
        </div>
      </div>

      <!-- Step 5: Events -->
      <div v-else-if="step === 5">
        <div v-if="!state.events.length">
          <el-button :loading="loading" @click="generate(5)">生成事件库</el-button>
        </div>
        <div v-else>
          <div class="card-grid">
            <div v-for="(ev, i) in state.events" :key="i" class="fw-card">
              <div class="fw-card-header">
                <span class="fw-card-name">{{ ev.name }}</span>
                <span class="fw-badge" :class="`imp-${Math.min(ev.importance, 5)}`">
                  重要性 {{ importanceStars(ev.importance) }}
                </span>
              </div>
              <p class="fw-card-desc">{{ ev.summary_md }}</p>
              <div class="fw-card-meta">
                <span>{{ ev.scope_type === 'global' ? '全局' : ev.scope_type === 'faction' ? '势力' : '地点' }}</span>
                <span v-if="ev.is_repeatable">可重复</span>
              </div>
              <div class="fw-card-actions">
                <el-button size="small" text @click="openEdit('event', i)">✏️ 编辑</el-button>
                <el-button size="small" text type="danger" @click="deleteItem('event', i)">🗑️</el-button>
              </div>
            </div>
          </div>
          <div class="add-btn-row">
            <el-button size="small" @click="openAdd('event')">➕ 新增事件</el-button>
          </div>
        </div>
      </div>

      <!-- Step 6: Character -->
      <div v-else-if="step === 6">
        <div v-if="!state.character_profile_md">
          <el-button :loading="loading" @click="generate(6)">生成主角</el-button>
        </div>
        <div v-else>
          <h4>{{ state.character_name }}</h4>
          <MarkdownView :source="state.character_profile_md" />
        </div>
      </div>

      <!-- Step 7: Campaign (optional) -->
      <div v-else-if="step === 7">
        <el-checkbox v-model="state.include_campaign" style="margin-bottom:12px">
          包含主线剧情（可选）
        </el-checkbox>
        <div v-if="state.include_campaign">
          <el-button v-if="!state.campaign" :loading="loading" @click="generate(7)">生成主线框架</el-button>
          <div v-else>
            <div v-for="ph in state.campaign.phases" :key="ph.phase_id" class="list-item">
              <strong>Phase {{ ph.phase_id }}: {{ ph.name }}</strong>
              <p class="item-desc">{{ ph.description }}</p>
              <p class="item-desc">关键事件：{{ ph.key_event_names.join('、') }}（需 {{ ph.required_count }} 个）</p>
            </div>
          </div>
        </div>
        <div v-else class="muted">跳过主线 → 纯沙盒模式</div>
      </div>
    </el-card>

    <!-- Step 8: Review -->
    <el-card v-else-if="step === 8">
      <h3>确认创建</h3>
      <p><strong>世界：</strong>{{ state.world_name }}（{{ state.genre }}）</p>
      <p><strong>地点：</strong>{{ state.locations.length }} 个</p>
      <p><strong>势力：</strong>{{ state.factions.length }} 个</p>
      <p><strong>NPC 模板：</strong>{{ state.npc_templates.length }} 个</p>
      <p><strong>事件库：</strong>{{ state.events.length }} 个事件</p>
      <p><strong>主线：</strong>{{ state.include_campaign && state.campaign ? state.campaign.name : '无（沙盒模式）' }}</p>
      <p><strong>主角：</strong>{{ state.character_name }}</p>
    </el-card>

    <!-- Nav buttons -->
    <div class="wizard-nav">
      <el-button v-if="step > 0" @click="step--">上一步</el-button>
      <el-button
        v-if="step < 8"
        type="primary"
        @click="step++"
      >
        下一步
      </el-button>
      <el-button v-else type="success" :loading="loading" @click="finalize">
        创建开放世界存档
      </el-button>
      <el-button text type="danger" @click="resetWizard" style="margin-left: auto">
        🗑️ 清空草稿
      </el-button>
    </div>
    <div class="muted" style="margin-top: 6px; text-align: right; font-size: 12px">
      ✓ 自动保存到本地，关闭窗口后可从「{{ STEP_LABELS[step] }}」继续
    </div>

    <!-- ─── Shared CRUD dialog ──────────────────────────────────────────────── -->
    <el-dialog
      v-model="editDialog.visible"
      :title="editDialog.mode === 'add' ? '新增' : '编辑'"
      width="520px"
      destroy-on-close
    >
      <!-- Location form -->
      <el-form v-if="editDialog.kind === 'location'" label-width="90px" label-position="right">
        <el-form-item label="名称">
          <el-input v-model="editDialog.draft.name" placeholder="地点名称" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="editDialog.draft.description_md" type="textarea" :rows="3" placeholder="地点描述" />
        </el-form-item>
        <el-form-item label="类型">
          <el-select v-model="editDialog.draft.location_type" style="width:100%">
            <el-option value="city" label="城镇" />
            <el-option value="dungeon" label="地下城" />
            <el-option value="wilderness" label="荒野" />
            <el-option value="landmark" label="地标" />
          </el-select>
        </el-form-item>
        <el-form-item label="初始状态">
          <el-select v-model="editDialog.draft.initial_state" style="width:100%">
            <el-option value="normal" label="正常" />
            <el-option value="damaged" label="受损" />
            <el-option value="destroyed" label="毁坏" />
          </el-select>
        </el-form-item>
        <el-form-item label="出口">
          <span class="muted">{{ editDialog.draft.connections?.length ?? 0 }} 个出口（连接编辑暂不支持）</span>
        </el-form-item>
      </el-form>

      <!-- Faction form -->
      <el-form v-else-if="editDialog.kind === 'faction'" label-width="110px" label-position="right">
        <el-form-item label="名称">
          <el-input v-model="editDialog.draft.name" placeholder="势力名称" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="editDialog.draft.description_md" type="textarea" :rows="3" placeholder="势力描述" />
        </el-form-item>
        <el-form-item label="盟友">
          <el-select v-model="editDialog.draft.ally_faction_names" multiple style="width:100%" placeholder="选择盟友势力">
            <el-option
              v-for="n in factionNamesExcluding(editDialog.draft.name)"
              :key="n" :value="n" :label="n"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="对立">
          <el-select v-model="editDialog.draft.rival_faction_names" multiple style="width:100%" placeholder="选择对立势力">
            <el-option
              v-for="n in factionNamesExcluding(editDialog.draft.name)"
              :key="n" :value="n" :label="n"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="张力/回合">
          <el-input-number
            v-model="editDialog.draft.tension_rules.passive_gain_per_turn"
            :min="0" :max="10" :step="1" style="width:100%"
          />
        </el-form-item>
        <el-form-item label="冲突阈值">
          <el-input-number
            v-model="editDialog.draft.tension_rules.threshold_conflict"
            :min="0" :max="100" :step="5" style="width:100%"
          />
        </el-form-item>
      </el-form>

      <!-- NPC form -->
      <el-form v-else-if="editDialog.kind === 'npc'" label-width="110px" label-position="right">
        <el-form-item label="名称">
          <el-input v-model="editDialog.draft.name" placeholder="NPC姓名" />
        </el-form-item>
        <el-form-item label="性别">
          <el-select v-model="editDialog.draft.gender" style="width:100%">
            <el-option value="" label="未知" />
            <el-option value="male" label="男" />
            <el-option value="female" label="女" />
          </el-select>
        </el-form-item>
        <el-form-item label="职业/角色">
          <el-input v-model="editDialog.draft.role" placeholder="如：侦探、商人" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="editDialog.draft.description_md" type="textarea" :rows="3" placeholder="NPC描述" />
        </el-form-item>
        <el-form-item label="动机">
          <el-input v-model="editDialog.draft.motivation" placeholder="NPC核心动机" />
        </el-form-item>
        <el-form-item label="说话风格">
          <el-input v-model="editDialog.draft.speech_pattern" placeholder="如：口头禅「啧」 / 说话总用反问句" />
        </el-form-item>
        <el-form-item label="所在地点">
          <el-select v-model="editDialog.draft.home_location_name" style="width:100%" clearable placeholder="选择地点">
            <el-option v-for="loc in state.locations" :key="loc.name" :value="loc.name" :label="loc.name" />
          </el-select>
        </el-form-item>
        <el-form-item label="所属势力">
          <el-select v-model="editDialog.draft.faction_name" style="width:100%" clearable placeholder="无势力">
            <el-option v-for="f in state.factions" :key="f.name" :value="f.name" :label="f.name" />
          </el-select>
        </el-form-item>
        <el-form-item label="好感阈值">
          <el-input-number v-model="editDialog.draft.contact_favor_threshold" :min="0" :max="100" style="width:100%" />
        </el-form-item>
        <el-form-item label="冷却回合">
          <el-input-number v-model="editDialog.draft.contact_cooldown_turns" :min="0" :max="50" style="width:100%" />
        </el-form-item>
      </el-form>

      <!-- Event form -->
      <el-form v-else-if="editDialog.kind === 'event'" label-width="110px" label-position="right">
        <el-form-item label="名称">
          <el-input v-model="editDialog.draft.name" placeholder="事件名称" />
        </el-form-item>
        <el-form-item label="摘要">
          <el-input v-model="editDialog.draft.summary_md" type="textarea" :rows="3" placeholder="事件描述" />
        </el-form-item>
        <el-form-item label="范围类型">
          <el-select v-model="editDialog.draft.scope_type" style="width:100%">
            <el-option value="global" label="全局" />
            <el-option value="location" label="地点" />
            <el-option value="faction" label="势力" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="editDialog.draft.scope_type === 'location'" label="地点">
          <el-select v-model="editDialog.draft.scope_location_name" style="width:100%" clearable placeholder="选择地点">
            <el-option v-for="loc in state.locations" :key="loc.name" :value="loc.name" :label="loc.name" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="editDialog.draft.scope_type === 'faction'" label="势力">
          <el-select v-model="editDialog.draft.scope_faction_name" style="width:100%" clearable placeholder="选择势力">
            <el-option v-for="f in state.factions" :key="f.name" :value="f.name" :label="f.name" />
          </el-select>
        </el-form-item>
        <el-form-item label="重要性">
          <el-input-number v-model="editDialog.draft.importance" :min="1" :max="5" style="width:100%" />
        </el-form-item>
        <el-form-item label="可重复">
          <el-checkbox v-model="editDialog.draft.is_repeatable" />
        </el-form-item>
        <el-form-item label="冷却回合">
          <el-input-number v-model="editDialog.draft.cooldown_turns" :min="0" :max="50" style="width:100%" />
        </el-form-item>
        <el-form-item label="触发条件">
          <span class="muted">（高级，可在创建后编辑）</span>
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="editDialog.visible = false">取消</el-button>
        <el-button type="primary" @click="saveDialog">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.ow-wizard { max-width: 860px; margin: 0 auto; padding: 24px; }
.step-regen-bar { display: flex; gap: 8px; margin-bottom: 16px; }
.wizard-nav { display: flex; gap: 12px; margin-top: 20px; justify-content: flex-end; }
.muted { color: #909399; font-size: 13px; }

/* Genre pills */
.genre-pill {
  padding: 8px 16px; border: 1px solid #dcdfe6; border-radius: 20px;
  cursor: pointer; font-size: 14px; transition: all .2s;
}
.genre-pill.selected { border-color: #409eff; color: #409eff; background: #ecf5ff; }

/* Card grid */
.card-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 12px;
}
.fw-card {
  border: 1px solid #e4e7ed;
  border-radius: 10px;
  padding: 14px 16px;
  background: #fff;
  display: flex;
  flex-direction: column;
  gap: 6px;
  transition: box-shadow 0.18s;
}
.fw-card:hover { box-shadow: 0 4px 14px rgba(0,0,0,.08); }
.fw-card-header { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.fw-card-name { font-weight: 600; font-size: 15px; color: #1a1a2e; }
.fw-card-desc { font-size: 13px; color: #5a5a72; line-height: 1.55; margin: 0; flex: 1; }
.fw-card-meta { font-size: 12px; color: #909399; margin-top: 2px; display: flex; gap: 8px; flex-wrap: wrap; }
.fw-card-actions { display: flex; gap: 4px; margin-top: 4px; }
.fw-speech-pattern { font-size: 12px; color: #7a7a9a; font-style: italic; }
.tension-hint { color: #b0820a; }
.add-btn-row { margin-top: 12px; display: flex; justify-content: flex-start; }

/* Type badges */
.fw-badge {
  font-size: 11px; font-weight: 500;
  padding: 2px 8px; border-radius: 20px;
  white-space: nowrap; flex-shrink: 0;
}
.type-city      { background: #ecf5ff; color: #409eff; }
.type-dungeon   { background: #fdf2f8; color: #c45fad; }
.type-wilderness{ background: #f0f9eb; color: #67c23a; }
.type-landmark  { background: #fdf6ec; color: #e6a23c; }
.type-faction   { background: #f4f4f5; color: #606266; }
.type-npc       { background: #fff0f0; color: #e85858; }
/* Importance badges */
.imp-1, .imp-2  { background: #f4f4f5; color: #909399; }
.imp-3          { background: #fdf6ec; color: #e6a23c; }
.imp-4          { background: #fef0e6; color: #d97706; }
.imp-5          { background: #fef0f0; color: #e85858; }
</style>
