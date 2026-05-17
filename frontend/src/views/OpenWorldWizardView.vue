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
  try {
    const hint = hints[stepNum] ? `\n\n用户引导：${hints[stepNum]}` : ''
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
    const world = await worldsApi.create({
      name: state.world_name || state.genre,
      content_md: state.world_brief_md,
      style: state.genre,
      rules_mode: 'simple',
    })

    // 3. 创建 Character
    const character = await charactersApi.create({
      world_id: world.id,
      name: state.character_name || '主角',
      gender: '',
      profile_md: state.character_profile_md,
      base_stats_json: '{}',
    })

    // 4. 创建 Session，绑定 framework_id
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
  } catch (e: unknown) {
    ElMessage.error(`创建失败：${e instanceof Error ? e.message : String(e)}`)
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
          v-for="g in ['悬疑探案', '奇幻冒险', '赛博朋克', '东方武侠', '恐怖求生']"
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
        <div v-else class="card-grid">
          <div v-for="(loc, i) in state.locations" :key="i" class="fw-card">
            <div class="fw-card-header">
              <span class="fw-card-name">{{ loc.name }}</span>
              <span class="fw-badge" :class="`type-${loc.location_type}`">
                {{ { city: '城镇', dungeon: '地下城', wilderness: '荒野', landmark: '地标' }[loc.location_type] ?? loc.location_type }}
              </span>
            </div>
            <p class="fw-card-desc">{{ loc.description_md }}</p>
            <div v-if="loc.connections.length" class="fw-card-meta">
              {{ loc.connections.length }} 个出口
            </div>
          </div>
        </div>
      </div>

      <!-- Step 3: Factions -->
      <div v-else-if="step === 3">
        <div v-if="!state.factions.length">
          <el-button :loading="loading" @click="generate(3)">生成势力</el-button>
        </div>
        <div v-else class="card-grid">
          <div v-for="(f, i) in state.factions" :key="i" class="fw-card">
            <div class="fw-card-header">
              <span class="fw-card-name">{{ f.name }}</span>
              <span class="fw-badge type-faction">势力</span>
            </div>
            <p class="fw-card-desc">{{ f.description_md }}</p>
            <div class="fw-card-meta">
              <span v-if="f.ally_faction_names.length">盟友 {{ f.ally_faction_names.length }}</span>
              <span v-if="f.rival_faction_names.length">对立 {{ f.rival_faction_names.length }}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- Step 4: NPC Templates -->
      <div v-else-if="step === 4">
        <div v-if="!state.npc_templates.length">
          <el-button :loading="loading" @click="generate(4)">生成NPC模板</el-button>
        </div>
        <div v-else class="card-grid">
          <div v-for="(n, i) in state.npc_templates" :key="i" class="fw-card">
            <div class="fw-card-header">
              <span class="fw-card-name">{{ n.name }}</span>
              <span class="fw-badge type-npc">{{ n.gender === 'male' ? '男' : n.gender === 'female' ? '女' : '?' }} · {{ n.role }}</span>
            </div>
            <p class="fw-card-desc">{{ n.description_md }}</p>
            <div class="fw-card-meta">📍 {{ n.home_location_name }}</div>
          </div>
        </div>
      </div>

      <!-- Step 5: Events -->
      <div v-else-if="step === 5">
        <div v-if="!state.events.length">
          <el-button :loading="loading" @click="generate(5)">生成事件库</el-button>
        </div>
        <div v-else class="card-grid">
          <div v-for="(ev, i) in state.events" :key="i" class="fw-card">
            <div class="fw-card-header">
              <span class="fw-card-name">{{ ev.name }}</span>
              <span class="fw-badge" :class="`imp-${Math.min(ev.importance, 5)}`">
                ★ {{ ev.importance }}
              </span>
            </div>
            <p class="fw-card-desc">{{ ev.summary_md }}</p>
            <div class="fw-card-meta">{{ ev.scope_type === 'global' ? '全局' : ev.scope_type === 'faction' ? '势力' : '地点' }}</div>
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
.fw-card-meta { font-size: 12px; color: #909399; margin-top: 2px; display: flex; gap: 8px; }

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
