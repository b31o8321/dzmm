# Open World Framework — Plan D: Frontend

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add WorldMapPanel (location graph display + LocationDetailPopup), CampaignProgressPanel, wire them into GameView as new tabs, and add a new 8-step OpenWorldWizardView for creating framework-based sessions. Remove obsolete Screenplay-based frontend views once the new ones are live.

**Architecture:** New components are additive — GameView shows WorldMapPanel only when `session.framework_id` is set (detected via a new field in the session state API response). The new wizard is a separate route (`/wizard/framework`) so the old wizard (`/wizard`) keeps working for legacy. All new API types go into a new `frontend/src/api/framework.ts` file. TypeScript is the sole language.

**Tech Stack:** Vue 3 Composition API, TypeScript, Element Plus, Vite

**Prerequisites:** Plan C (Backend Wizard API) must be merged so `/wizard/fw/*` endpoints exist.

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `frontend/src/api/framework.ts` | Create | Types for WorldLocation, WorldEvent, WorldFaction, WorldNPCTemplate, session state extensions |
| `frontend/src/components/WorldMapPanel.vue` | Create | Location graph + LocationDetailPopup |
| `frontend/src/components/CampaignProgressPanel.vue` | Create | Campaign phase progress display |
| `frontend/src/views/OpenWorldWizardView.vue` | Create | 8-step framework wizard |
| `frontend/src/views/GameView.vue` | Modify | Add World Map tab; show new panels when framework_id set |
| `frontend/src/api/sessions.ts` | Modify | Add `framework_id` to Session type |
| `frontend/src/router/index.ts` | Modify | Add `/wizard/framework` route |
| `frontend/src/views/ScreenplaysView.vue` et al. | Delete | Remove after new views confirmed working |

---

### Task 1: framework.ts API types

**Files:**
- Create: `frontend/src/api/framework.ts`

This file defines all TypeScript types used by the open-world frontend. No LLM calls needed — pure type definitions.

- [ ] **Step 1: Create frontend/src/api/framework.ts**

```typescript
// frontend/src/api/framework.ts
import { api } from './client'

// ── DB-backed types (match ORM fields) ──────────────────

export interface WorldLocationData {
  id: number
  framework_id: number
  name: string
  description_md: string
  location_type: 'city' | 'dungeon' | 'wilderness' | 'landmark'
  connections: Array<{
    target_id: number
    direction: string
    distance: number
    travel_turns: number
  }>
  initial_state: 'normal' | 'damaged' | 'destroyed'
  // session override (injected at runtime)
  session_status?: 'normal' | 'damaged' | 'destroyed'
}

export interface WorldFactionData {
  id: number
  name: string
  description_md: string
  tension: number       // from SessionFactionState
  pc_reputation: number
}

export interface WorldNPCStateData {
  npc_template_id: number
  name: string
  gender: string
  role: string
  current_location_id: number | null
  favor: number
  is_companion: boolean
  is_revealed: boolean
  is_alive: boolean
}

export interface WorldEventStateData {
  event_id: number
  name: string
  summary_md: string
  importance: number
  scope_type: string
  scope_ref: string
  status: 'pending' | 'triggered' | 'completed'
  triggered_turn: number
}

export interface LocationDetail {
  location: WorldLocationData
  npcs_here: WorldNPCStateData[]
  triggered_events: WorldEventStateData[]
  controlling_faction: string | null
}

export interface CampaignPhaseProgress {
  phase_id: number
  name: string
  description: string
  status: 'locked' | 'active' | 'completed'
  triggered_count: number
  required_count: number
  triggered_key_events: Array<{ event_id: number; name: string }>
}

export interface CampaignProgress {
  campaign_name: string
  phases: CampaignPhaseProgress[]
}

// ── Wizard payload types ─────────────────────────────────

export interface FwLocationInput {
  name: string
  description_md: string
  location_type: string
  connections: Array<{
    target_name: string
    direction: string
    distance: number
    travel_turns: number
  }>
  initial_state: string
}

export interface FwFactionInput {
  name: string
  description_md: string
  rival_faction_names: string[]
  ally_faction_names: string[]
  tension_rules: { passive_gain_per_turn: number; threshold_conflict: number }
}

export interface FwNpcTemplateInput {
  name: string
  gender: 'male' | 'female' | ''
  role: string
  description_md: string
  motivation: string
  home_location_name: string
  faction_name: string | null
  contact_favor_threshold: number
  contact_cooldown_turns: number
}

export interface FwEventInput {
  name: string
  summary_md: string
  scope_type: 'location' | 'faction' | 'global'
  scope_location_name?: string
  scope_faction_name?: string
  importance: number
  trigger_conditions: unknown[]
  is_repeatable: boolean
  cooldown_turns: number
}

export interface FwCampaignPhaseInput {
  phase_id: number
  name: string
  description: string
  prerequisite_phase_ids: number[]
  key_event_names: string[]
  required_count: number
}

export interface FwCampaignInput {
  name: string
  phases: FwCampaignPhaseInput[]
}

export interface FwFinalizePayload {
  name: string
  genre: string
  style: string
  description_md: string
  locations: FwLocationInput[]
  factions: FwFactionInput[]
  npc_templates: FwNpcTemplateInput[]
  events: FwEventInput[]
  campaign: FwCampaignInput | null
}

// ── API calls ────────────────────────────────────────────

export const frameworkApi = {
  generateLocations: (b: { model_config_id: number; genre: string; world_brief_md: string }) =>
    api.post<FwLocationInput[]>('/wizard/fw/locations', b, { timeout: 600_000 }).then(r => r.data),

  generateFactions: (b: {
    model_config_id: number; genre: string; world_brief_md: string; locations: FwLocationInput[]
  }) =>
    api.post<FwFactionInput[]>('/wizard/fw/factions', b, { timeout: 600_000 }).then(r => r.data),

  generateNpcTemplates: (b: {
    model_config_id: number; genre: string; world_brief_md: string
    locations: FwLocationInput[]; factions: FwFactionInput[]
  }) =>
    api.post<FwNpcTemplateInput[]>('/wizard/fw/npc_templates', b, { timeout: 600_000 }).then(r => r.data),

  generateEvents: (b: {
    model_config_id: number; genre: string; world_brief_md: string
    locations: FwLocationInput[]; factions: FwFactionInput[]; npc_templates: FwNpcTemplateInput[]
  }) =>
    api.post<FwEventInput[]>('/wizard/fw/events', b, { timeout: 600_000 }).then(r => r.data),

  generateCampaign: (b: {
    model_config_id: number; genre: string; world_brief_md: string; events: FwEventInput[]
  }) =>
    api.post<FwCampaignInput>('/wizard/fw/campaign', b, { timeout: 600_000 }).then(r => r.data),

  finalize: (b: FwFinalizePayload) =>
    api.post<{ framework_id: number }>('/wizard/fw/finalize', b).then(r => r.data),
}
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd frontend && npx tsc --noEmit 2>&1 | head -20
```

Expected: No errors related to `framework.ts`.

- [ ] **Step 3: Add framework_id to Session type in sessions.ts**

Find the `Session` interface in `frontend/src/api/sessions.ts` and add:

```typescript
  framework_id?: number | null
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/api/framework.ts frontend/src/api/sessions.ts
git commit -m "feat(frontend): framework.ts API types + framework_id on Session"
```

---

### Task 2: WorldMapPanel component

**Files:**
- Create: `frontend/src/components/WorldMapPanel.vue`

This component renders the location graph as a list of location cards (no canvas/SVG graph required — that's optional). Clicking a card opens `LocationDetailPopup`.

- [ ] **Step 1: Create WorldMapPanel.vue**

```vue
<!-- frontend/src/components/WorldMapPanel.vue -->
<script setup lang="ts">
import { computed, ref } from 'vue'
import type { WorldLocationData, WorldNPCStateData, WorldEventStateData, LocationDetail } from '@/api/framework'

const props = defineProps<{
  locations: WorldLocationData[]
  npcStates: WorldNPCStateData[]
  eventStates: WorldEventStateData[]
  pcLocationId: number | null
  factionNames: Record<number, string>  // location_id → controlling faction name
}>()

const selectedLocation = ref<WorldLocationData | null>(null)

const locationDetail = computed((): LocationDetail | null => {
  const loc = selectedLocation.value
  if (!loc) return null
  const npcsHere = props.npcStates.filter(
    n => n.current_location_id === loc.id && n.is_revealed
  )
  const triggeredEvents = props.eventStates.filter(
    e => e.scope_type === 'location' && e.scope_ref === String(loc.id)
      && (e.status === 'triggered' || e.status === 'completed')
  )
  return {
    location: loc,
    npcs_here: npcsHere,
    triggered_events: triggeredEvents,
    controlling_faction: props.factionNames[loc.id] ?? null,
  }
})

function statusColor(loc: WorldLocationData): string {
  const status = loc.session_status ?? loc.initial_state
  if (status === 'destroyed') return '#f56c6c'
  if (status === 'damaged') return '#e6a23c'
  return '#67c23a'
}

function isExplored(loc: WorldLocationData): boolean {
  // A location is explored if any event or NPC is revealed there
  return props.eventStates.some(
    e => e.scope_type === 'location' && e.scope_ref === String(loc.id)
  ) || props.npcStates.some(n => n.current_location_id === loc.id && n.is_revealed)
  || loc.id === props.pcLocationId
}
</script>

<template>
  <div class="world-map-panel">
    <div class="locations-grid">
      <div
        v-for="loc in locations"
        :key="loc.id"
        class="location-card"
        :class="{
          'is-current': loc.id === pcLocationId,
          'is-unexplored': !isExplored(loc),
        }"
        @click="selectedLocation = loc"
      >
        <div class="loc-header">
          <span class="loc-indicator" :style="{ background: statusColor(loc) }" />
          <span class="loc-name">{{ loc.name }}</span>
          <el-tag v-if="loc.id === pcLocationId" size="small" type="success">当前</el-tag>
        </div>
        <div class="loc-type">{{ loc.location_type }}</div>
        <div v-if="isExplored(loc)" class="loc-summary">
          <span v-if="npcStates.filter(n => n.current_location_id === loc.id && n.is_revealed).length">
            {{ npcStates.filter(n => n.current_location_id === loc.id && n.is_revealed).length }} 个 NPC
          </span>
          <span v-if="eventStates.filter(e => e.scope_ref === String(loc.id) && e.status !== 'pending').length">
            {{ eventStates.filter(e => e.scope_ref === String(loc.id) && e.status !== 'pending').length }} 个事件
          </span>
        </div>
        <div v-else class="loc-unknown">未探索</div>
        <div class="loc-connections">
          <span v-for="conn in loc.connections" :key="conn.target_id" class="conn-chip">
            {{ conn.direction }}
          </span>
        </div>
      </div>
    </div>

    <!-- Location detail popup -->
    <el-dialog
      v-if="locationDetail"
      :model-value="!!selectedLocation"
      :title="locationDetail.location.name"
      width="480px"
      @close="selectedLocation = null"
    >
      <div class="location-detail">
        <p class="desc">{{ locationDetail.location.description_md }}</p>
        <div v-if="locationDetail.controlling_faction" class="faction-badge">
          势力：{{ locationDetail.controlling_faction }}
        </div>

        <template v-if="locationDetail.npcs_here.length">
          <h4>已知 NPC</h4>
          <div v-for="npc in locationDetail.npcs_here" :key="npc.npc_template_id" class="npc-row">
            <span class="npc-name">{{ npc.name }}</span>
            <span class="npc-role">{{ npc.role }}</span>
            <el-tag v-if="npc.is_companion" size="small" type="warning">旅伴</el-tag>
            <span class="favor-badge">好感 {{ npc.favor }}</span>
          </div>
        </template>

        <template v-if="locationDetail.triggered_events.length">
          <h4>已触发事件</h4>
          <div v-for="ev in locationDetail.triggered_events" :key="ev.event_id" class="event-row">
            <el-tag :type="ev.status === 'completed' ? 'info' : 'warning'" size="small">
              {{ ev.status === 'completed' ? '已完成' : '进行中' }}
            </el-tag>
            <span class="ev-name">{{ ev.name }}</span>
            <span class="ev-summary">{{ ev.summary_md }}</span>
          </div>
        </template>

        <template v-if="locationDetail.location.connections.length">
          <h4>可前往</h4>
          <div class="exits-list">
            <span v-for="conn in locationDetail.location.connections" :key="conn.target_id" class="exit-chip">
              {{ conn.direction }} → ({{ conn.travel_turns }} 回合)
            </span>
          </div>
        </template>
      </div>
    </el-dialog>
  </div>
</template>

<style scoped>
.world-map-panel { padding: 12px; }
.locations-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 10px;
}
.location-card {
  border: 1px solid #dcdfe6;
  border-radius: 8px;
  padding: 10px 12px;
  cursor: pointer;
  transition: border-color 0.2s, box-shadow 0.2s;
}
.location-card:hover { border-color: #409eff; box-shadow: 0 2px 8px rgba(64,158,255,.15); }
.location-card.is-current { border-color: #67c23a; background: #f0f9eb; }
.location-card.is-unexplored { opacity: 0.5; }
.loc-header { display: flex; align-items: center; gap: 6px; margin-bottom: 4px; }
.loc-indicator { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
.loc-name { font-weight: 600; font-size: 14px; flex: 1; }
.loc-type { font-size: 11px; color: #909399; margin-bottom: 4px; }
.loc-summary, .loc-unknown { font-size: 12px; color: #606266; }
.loc-connections { margin-top: 6px; display: flex; flex-wrap: wrap; gap: 4px; }
.conn-chip {
  font-size: 11px; background: #ecf5ff; color: #409eff;
  border-radius: 4px; padding: 1px 5px;
}
.location-detail .desc { color: #606266; margin-bottom: 12px; }
.location-detail h4 { font-size: 13px; color: #303133; margin: 12px 0 6px; }
.npc-row, .event-row { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; font-size: 13px; }
.favor-badge { margin-left: auto; font-size: 12px; color: #909399; }
.exits-list { display: flex; flex-wrap: wrap; gap: 6px; }
.exit-chip { font-size: 12px; background: #f4f4f5; padding: 3px 8px; border-radius: 4px; }
.faction-badge { font-size: 12px; color: #909399; margin-bottom: 8px; }
</style>
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd frontend && npx tsc --noEmit 2>&1 | head -20
```

Expected: No errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/WorldMapPanel.vue
git commit -m "feat(frontend): WorldMapPanel with LocationDetailPopup"
```

---

### Task 3: CampaignProgressPanel component

**Files:**
- Create: `frontend/src/components/CampaignProgressPanel.vue`

- [ ] **Step 1: Create CampaignProgressPanel.vue**

```vue
<!-- frontend/src/components/CampaignProgressPanel.vue -->
<script setup lang="ts">
import type { CampaignProgress } from '@/api/framework'

defineProps<{
  campaign: CampaignProgress | null
}>()
</script>

<template>
  <div v-if="campaign" class="campaign-panel">
    <div class="campaign-title">主线：{{ campaign.campaign_name }}</div>
    <div v-for="phase in campaign.phases" :key="phase.phase_id" class="phase-row">
      <span class="phase-icon">
        {{ phase.status === 'completed' ? '✓' : phase.status === 'active' ? '→' : '🔒' }}
      </span>
      <div class="phase-info">
        <div class="phase-name">{{ phase.name }}</div>
        <div class="phase-progress" v-if="phase.status !== 'locked'">
          {{ phase.triggered_count }} / {{ phase.required_count }} 关键事件
        </div>
        <div v-if="phase.status === 'active' && phase.triggered_key_events.length" class="key-events">
          <span v-for="ev in phase.triggered_key_events" :key="ev.event_id" class="key-ev-badge">
            {{ ev.name }}
          </span>
        </div>
      </div>
    </div>
  </div>
  <div v-else class="no-campaign">沙盒模式（无主线）</div>
</template>

<style scoped>
.campaign-panel { padding: 10px 12px; }
.campaign-title { font-weight: 600; font-size: 14px; margin-bottom: 10px; color: #303133; }
.phase-row { display: flex; gap: 10px; margin-bottom: 8px; align-items: flex-start; }
.phase-icon { font-size: 16px; flex-shrink: 0; width: 20px; text-align: center; }
.phase-name { font-size: 13px; font-weight: 500; }
.phase-progress { font-size: 12px; color: #909399; }
.key-events { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 4px; }
.key-ev-badge { font-size: 11px; background: #fdf6ec; color: #e6a23c; border-radius: 4px; padding: 2px 6px; }
.no-campaign { color: #909399; font-size: 13px; padding: 12px; }
</style>
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd frontend && npx tsc --noEmit 2>&1 | head -20
```

Expected: No errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/CampaignProgressPanel.vue
git commit -m "feat(frontend): CampaignProgressPanel for open-world sessions"
```

---

### Task 4: Wire WorldMapPanel + CampaignProgressPanel into GameView

**Files:**
- Modify: `frontend/src/views/GameView.vue`

GameView currently shows `ScreenplayProgressPanel` in the right-side panel. We add a check: if `session.framework_id` is set, show WorldMapPanel + CampaignProgressPanel instead. The session object is already loaded in GameView; we just need to expose `framework_id` from the API.

- [ ] **Step 1: Check current session loading in GameView**

```bash
grep -n "session\b\|framework_id\|screenplay" frontend/src/views/GameView.vue | head -30
```

- [ ] **Step 2: Add new imports to GameView.vue**

In the `<script setup>` imports section, add:

```typescript
import WorldMapPanel from '@/components/WorldMapPanel.vue'
import CampaignProgressPanel from '@/components/CampaignProgressPanel.vue'
import type { WorldLocationData, WorldNPCStateData, WorldEventStateData } from '@/api/framework'
```

- [ ] **Step 3: Add reactive state for open-world data**

After existing refs (e.g. after `const screenplay = ref<Screenplay | null>(null)`), add:

```typescript
const frameworkId = ref<number | null>(null)
const worldLocations = ref<WorldLocationData[]>([])
const worldNpcStates = ref<WorldNPCStateData[]>([])
const worldEventStates = ref<WorldEventStateData[]>([])
const pcLocationId = ref<number | null>(null)
const campaignProgress = ref<import('@/api/framework').CampaignProgress | null>(null)
const activeTab = ref<'state' | 'map' | 'screenplay'>('state')
```

- [ ] **Step 4: Set framework_id when session loads**

Find where the session is fetched (e.g. `loadSession()` or equivalent) and add after loading:

```typescript
frameworkId.value = session.framework_id ?? null
if (frameworkId.value) {
  activeTab.value = 'map'
}
```

- [ ] **Step 5: Replace ScreenplayProgressPanel with conditional tabs in the template**

Find the section with `<ScreenplayProgressPanel .../>` in both desktop and mobile template locations and replace each with:

```vue
<!-- Open-world tabs: map + campaign (only when framework_id set) -->
<template v-if="frameworkId">
  <div class="panel-tabs">
    <button :class="{ active: activeTab === 'map' }" @click="activeTab = 'map'">世界地图</button>
    <button :class="{ active: activeTab === 'screenplay' }" @click="activeTab = 'screenplay'">主线进度</button>
  </div>
  <WorldMapPanel
    v-if="activeTab === 'map'"
    :locations="worldLocations"
    :npc-states="worldNpcStates"
    :event-states="worldEventStates"
    :pc-location-id="pcLocationId"
    :faction-names="{}"
  />
  <CampaignProgressPanel
    v-if="activeTab === 'screenplay'"
    :campaign="campaignProgress"
  />
</template>
<!-- Legacy: screenplay progress for old sessions -->
<ScreenplayProgressPanel v-else :screenplay="screenplay" :session-id="sessionId" />
```

- [ ] **Step 6: Add minimal tab styles to GameView**

In the `<style scoped>` block, add:

```css
.panel-tabs {
  display: flex;
  gap: 8px;
  padding: 8px 12px 0;
  border-bottom: 1px solid #e4e7ed;
}
.panel-tabs button {
  background: none;
  border: none;
  padding: 6px 12px;
  font-size: 13px;
  cursor: pointer;
  color: #606266;
  border-bottom: 2px solid transparent;
}
.panel-tabs button.active {
  color: #409eff;
  border-bottom-color: #409eff;
}
```

- [ ] **Step 7: Verify TypeScript compiles**

```bash
cd frontend && npx tsc --noEmit 2>&1 | head -20
```

Expected: No errors.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/views/GameView.vue
git commit -m "feat(frontend): wire WorldMapPanel + CampaignProgressPanel into GameView (framework sessions)"
```

---

### Task 5: OpenWorldWizardView — 8-step framework wizard

**Files:**
- Create: `frontend/src/views/OpenWorldWizardView.vue`
- Modify: `frontend/src/router/index.ts`

This is an 8-step wizard using `/wizard/fw/*` endpoints. Each step has a "再生成（含引导词）" button. Steps with lists (locations, factions, NPCs, events) have per-item regeneration.

- [ ] **Step 1: Create OpenWorldWizardView.vue**

```vue
<!-- frontend/src/views/OpenWorldWizardView.vue -->
<script setup lang="ts">
import { ref, reactive, computed } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElSteps, ElStep, ElButton, ElInput, ElCard } from 'element-plus'
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

// Per-step hint inputs for whole-step regeneration
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
  // Character (reuses existing wizard step)
  character_name: '',
  character_gender: '' as '' | 'male' | 'female',
  character_profile_md: '',
})

const modelConfigId = computed(() => modelStore.defaultId ?? modelStore.configs[0]?.id)

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
      // World brief (reuse existing wizard)
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
      // Character
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

async function regenerateItem<T>(
  list: T[],
  index: number,
  hint: string,
  genFn: (hint: string) => Promise<T>,
) {
  loading.value = true
  try {
    list[index] = await genFn(hint)
  } catch (e: unknown) {
    ElMessage.error(`单项重生成失败`)
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
    const { framework_id } = await frameworkApi.finalize(payload)
    ElMessage.success('开放世界创建成功！')
    // TODO: create session with framework_id, redirect to play
    router.push('/')
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
        <el-input v-model="hints[step]" :placeholder="`引导词（可选）— 重新生成 Step ${step}`" style="flex:1" size="small" />
        <el-button size="small" :loading="loading" @click="generate(step)">↻ 重新生成</el-button>
      </div>

      <!-- Step 1: World brief -->
      <div v-if="step === 1">
        <MarkdownView v-if="state.world_brief_md" :content="state.world_brief_md" />
        <el-button v-else :loading="loading" @click="generate(1)">生成世界简介</el-button>
      </div>

      <!-- Step 2: Locations -->
      <div v-else-if="step === 2">
        <div v-if="!state.locations.length">
          <el-button :loading="loading" @click="generate(2)">生成地点网络</el-button>
        </div>
        <div v-else>
          <div v-for="(loc, i) in state.locations" :key="i" class="list-item">
            <div class="item-header">
              <strong>{{ loc.name }}</strong>
              <span class="item-type">{{ loc.location_type }}</span>
              <div class="item-regen">
                <el-input v-model="hints[200 + i]" placeholder="引导词" size="small" style="width:120px" />
                <el-button size="small" @click="generate(2)">↻</el-button>
              </div>
            </div>
            <p class="item-desc">{{ loc.description_md }}</p>
          </div>
        </div>
      </div>

      <!-- Step 3: Factions -->
      <div v-else-if="step === 3">
        <div v-if="!state.factions.length">
          <el-button :loading="loading" @click="generate(3)">生成势力</el-button>
        </div>
        <div v-else>
          <div v-for="(f, i) in state.factions" :key="i" class="list-item">
            <div class="item-header">
              <strong>{{ f.name }}</strong>
              <div class="item-regen">
                <el-button size="small" @click="generate(3)">↻</el-button>
              </div>
            </div>
            <p class="item-desc">{{ f.description_md }}</p>
          </div>
        </div>
      </div>

      <!-- Step 4: NPC Templates -->
      <div v-else-if="step === 4">
        <div v-if="!state.npc_templates.length">
          <el-button :loading="loading" @click="generate(4)">生成NPC模板</el-button>
        </div>
        <div v-else>
          <div v-for="(n, i) in state.npc_templates" :key="i" class="list-item">
            <div class="item-header">
              <strong>{{ n.name }}</strong>
              <span class="item-type">{{ n.role }}</span>
              <span class="item-type">{{ n.gender === 'male' ? '男' : n.gender === 'female' ? '女' : '' }}</span>
              <div class="item-regen">
                <el-button size="small" @click="generate(4)">↻</el-button>
              </div>
            </div>
            <p class="item-desc">{{ n.description_md }}</p>
          </div>
        </div>
      </div>

      <!-- Step 5: Events -->
      <div v-else-if="step === 5">
        <div v-if="!state.events.length">
          <el-button :loading="loading" @click="generate(5)">生成事件库</el-button>
        </div>
        <div v-else>
          <div v-for="(ev, i) in state.events" :key="i" class="list-item">
            <div class="item-header">
              <strong>{{ ev.name }}</strong>
              <el-tag size="small">重要性 {{ ev.importance }}</el-tag>
              <div class="item-regen">
                <el-button size="small" @click="generate(5)">↻</el-button>
              </div>
            </div>
            <p class="item-desc">{{ ev.summary_md }}</p>
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
          <MarkdownView :content="state.character_profile_md" />
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
        :disabled="step === 7 && !state.include_campaign && false"
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
.ow-wizard { max-width: 800px; margin: 0 auto; padding: 24px; }
.step-regen-bar { display: flex; gap: 8px; margin-bottom: 16px; }
.list-item { border: 1px solid #ebeef5; border-radius: 6px; padding: 10px 12px; margin-bottom: 8px; }
.item-header { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.item-type { font-size: 12px; color: #909399; }
.item-regen { margin-left: auto; display: flex; gap: 4px; }
.item-desc { font-size: 13px; color: #606266; margin: 4px 0 0; }
.wizard-nav { display: flex; gap: 12px; margin-top: 20px; justify-content: flex-end; }
.genre-pill {
  padding: 8px 16px; border: 1px solid #dcdfe6; border-radius: 20px;
  cursor: pointer; font-size: 14px; transition: all .2s;
}
.genre-pill.selected { border-color: #409eff; color: #409eff; background: #ecf5ff; }
.muted { color: #909399; font-size: 13px; }
</style>
```

- [ ] **Step 2: Add route to router/index.ts**

Find the routes array and add:

```typescript
{
  path: '/wizard/framework',
  name: 'open-world-wizard',
  component: () => import('@/views/OpenWorldWizardView.vue'),
},
```

- [ ] **Step 3: Add link in SessionsView or WelcomeView**

Find where the "新开一局" button is in `SessionsView.vue` or `WelcomeView.vue` and add a second option:

```vue
<el-button @click="$router.push('/wizard/framework')">
  开放世界（新）
</el-button>
```

- [ ] **Step 4: Verify TypeScript compiles**

```bash
cd frontend && npx tsc --noEmit 2>&1 | head -20
```

Expected: No errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/views/OpenWorldWizardView.vue frontend/src/router/index.ts frontend/src/views/SessionsView.vue
git commit -m "feat(frontend): OpenWorldWizardView 8-step flow + /wizard/framework route"
```

---

### Task 6: Cleanup — remove obsolete Screenplay frontend views

Only safe after new views are confirmed working (previous tasks complete).

**Files to delete:**
- `frontend/src/views/ScreenplaysView.vue`
- `frontend/src/views/WorldScreenplaysView.vue`
- `frontend/src/views/ScreenplayView.vue` (if no longer needed)

- [ ] **Step 1: Remove the views**

```bash
git rm frontend/src/views/ScreenplaysView.vue
git rm frontend/src/views/WorldScreenplaysView.vue
```

- [ ] **Step 2: Remove their routes from router/index.ts**

Find and delete these route entries:
```typescript
{ path: 'worlds/:id/screenplays', name: 'world-screenplays', ... }
{ path: 'screenplays', name: 'screenplays-list', ... }
{ path: 'play/:id/screenplay', name: 'screenplay', ... }
```

- [ ] **Step 3: Remove nav links to deleted views**

```bash
grep -rn "world-screenplays\|screenplays-list\|ScreenplaysView\|WorldScreenplaysView" frontend/src/ | grep -v ".vue:0"
```

Remove any `<router-link>` or `router.push` calls pointing to deleted routes.

- [ ] **Step 4: Verify TypeScript compiles + no broken imports**

```bash
cd frontend && npx tsc --noEmit 2>&1 | head -20
```

Expected: No errors.

- [ ] **Step 5: Commit**

```bash
git add -A frontend/src/views/ frontend/src/router/
git commit -m "chore(frontend): remove obsolete Screenplay views and routes"
```
