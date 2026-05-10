<script setup lang="ts">
import { ref, reactive, computed } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { frameworkApi } from '@/api/framework'
import type {
  FwLocationInput, FwFactionInput, FwNpcTemplateInput,
  FwEventInput, FwCampaignInput, FwFinalizePayload,
} from '@/api/framework'
import { wizardApi } from '@/api/wizard'
import { useModelConfigsStore } from '@/stores/modelConfigs'
import MarkdownView from '@/components/MarkdownView.vue'

const router = useRouter()
const modelStore = useModelConfigsStore()

const step = ref(0)
const loading = ref(false)
const hints = reactive<Record<number, string>>({})

const state = reactive({
  genre: '悬疑探案',
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

const modelConfigId = computed(() => modelStore.preferredId())

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
      const r = await wizardApi.character({
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
    await frameworkApi.finalize(payload)
    ElMessage.success('开放世界创建成功！')
    router.push('/sessions')
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
