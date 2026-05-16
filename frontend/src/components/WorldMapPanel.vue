<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { WorldLocationData, WorldNPCStateData, WorldEventStateData, LocationDetail } from '@/api/framework'

const props = defineProps<{
  locations: WorldLocationData[]
  npcStates: WorldNPCStateData[]
  eventStates: WorldEventStateData[]
  pcLocationId: number | null
  factionNames: Record<number, string>
}>()

const selectedLocation = ref<WorldLocationData | null>(null)
const activeTab = ref<'map' | 'list'>('map')

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
  return props.eventStates.some(
    e => e.scope_type === 'location' && e.scope_ref === String(loc.id)
  ) || props.npcStates.some(n => n.current_location_id === loc.id && n.is_revealed)
  || loc.id === props.pcLocationId
}

// ── Force-directed layout ──────────────────────────────────

const SVG_W = 800
const SVG_H = 420
const PADDING = 48
const NODE_R = 28
const SPRING_L = 160   // rest length
const SPRING_K = 0.04  // attraction strength
const REPULSE  = 6000  // Coulomb constant
const DAMPING  = 0.82
const TICKS    = 150

interface Vec { x: number; y: number }

const nodePositions = ref<Map<number, Vec>>(new Map())

function runLayout(locs: WorldLocationData[]) {
  if (!locs.length) { nodePositions.value = new Map(); return }

  const n = locs.length
  const cx = SVG_W / 2
  const cy = SVG_H / 2
  const r0 = Math.min(cx, cy) * 0.6

  // initialise on a circle
  const pos: Vec[] = locs.map((_, i) => ({
    x: cx + r0 * Math.cos((2 * Math.PI * i) / n),
    y: cy + r0 * Math.sin((2 * Math.PI * i) / n),
  }))
  const vel: Vec[] = locs.map(() => ({ x: 0, y: 0 }))

  // build adjacency (by index)
  const idxById = new Map(locs.map((l, i) => [l.id, i]))
  const edges: [number, number][] = []
  locs.forEach((loc, ai) => {
    loc.connections.forEach(c => {
      const bi = idxById.get(c.target_id)
      if (bi !== undefined && ai < bi) edges.push([ai, bi])
    })
  })

  for (let t = 0; t < TICKS; t++) {
    const force: Vec[] = locs.map(() => ({ x: 0, y: 0 }))

    // repulsion (all pairs)
    for (let a = 0; a < n; a++) {
      for (let b = a + 1; b < n; b++) {
        const dx = pos[a].x - pos[b].x
        const dy = pos[a].y - pos[b].y
        const d2 = Math.max(dx * dx + dy * dy, 1)
        const d  = Math.sqrt(d2)
        const f  = REPULSE / d2
        const fx = (dx / d) * f
        const fy = (dy / d) * f
        force[a].x += fx; force[a].y += fy
        force[b].x -= fx; force[b].y -= fy
      }
    }

    // spring attraction (edges only)
    edges.forEach(([a, b]) => {
      const dx = pos[b].x - pos[a].x
      const dy = pos[b].y - pos[a].y
      const d  = Math.max(Math.sqrt(dx * dx + dy * dy), 0.1)
      const f  = SPRING_K * (d - SPRING_L)
      const fx = (dx / d) * f
      const fy = (dy / d) * f
      force[a].x += fx; force[a].y += fy
      force[b].x -= fx; force[b].y -= fy
    })

    // integrate + clamp
    for (let i = 0; i < n; i++) {
      vel[i].x = (vel[i].x + force[i].x) * DAMPING
      vel[i].y = (vel[i].y + force[i].y) * DAMPING
      pos[i].x = Math.max(PADDING + NODE_R, Math.min(SVG_W - PADDING - NODE_R, pos[i].x + vel[i].x))
      pos[i].y = Math.max(PADDING + NODE_R, Math.min(SVG_H - PADDING - NODE_R, pos[i].y + vel[i].y))
    }
  }

  const result = new Map<number, Vec>()
  locs.forEach((loc, i) => result.set(loc.id, { x: pos[i].x, y: pos[i].y }))
  nodePositions.value = result
}

watch(() => props.locations, (locs) => { runLayout(locs) }, { immediate: true })

// ── SVG computed data ──────────────────────────────────────

const svgEdges = computed(() => {
  const seen = new Set<string>()
  const result: Array<{
    x1: number; y1: number; x2: number; y2: number
    mx: number; my: number
    label: string
    strokeWidth: number
  }> = []
  props.locations.forEach(loc => {
    const pa = nodePositions.value.get(loc.id)
    if (!pa) return
    loc.connections.forEach(conn => {
      const key = [Math.min(loc.id, conn.target_id), Math.max(loc.id, conn.target_id)].join('-')
      if (seen.has(key)) return
      seen.add(key)
      const pb = nodePositions.value.get(conn.target_id)
      if (!pb) return
      // collect labels from both ends
      const revConn = props.locations.find(l => l.id === conn.target_id)
        ?.connections.find(c => c.target_id === loc.id)
      const label = revConn ? `${conn.direction}/${revConn.direction}` : conn.direction
      // edge thickness inversely proportional to travel_turns (1=thick, 5+=thin)
      const strokeWidth = Math.max(1, 4 - (conn.travel_turns - 1) * 0.7)
      result.push({ x1: pa.x, y1: pa.y, x2: pb.x, y2: pb.y,
        mx: (pa.x + pb.x) / 2, my: (pa.y + pb.y) / 2, label, strokeWidth })
    })
  })
  return result
})
</script>

<template>
  <div class="world-map-panel">

    <!-- Tab toggle -->
    <div class="map-tabs">
      <button :class="['tab-btn', activeTab === 'map' ? 'active' : '']" @click="activeTab = 'map'">地图</button>
      <button :class="['tab-btn', activeTab === 'list' ? 'active' : '']" @click="activeTab = 'list'">列表</button>
    </div>

    <!-- SVG Topology view -->
    <div v-if="activeTab === 'map'" class="svg-container">
      <svg :viewBox="`0 0 ${800} ${420}`" width="100%" height="420" xmlns="http://www.w3.org/2000/svg">
        <!-- edges -->
        <g v-for="(e, idx) in svgEdges" :key="idx">
          <line
            :x1="e.x1" :y1="e.y1" :x2="e.x2" :y2="e.y2"
            stroke="#c0c4cc" :stroke-width="e.strokeWidth" stroke-linecap="round"
          />
          <text
            v-if="e.label"
            :x="e.mx" :y="e.my - 5"
            text-anchor="middle" font-size="10" fill="#909399"
          >{{ e.label }}</text>
        </g>

        <!-- nodes -->
        <g
          v-for="loc in locations"
          :key="loc.id"
          :transform="`translate(${nodePositions.get(loc.id)?.x ?? 0}, ${nodePositions.get(loc.id)?.y ?? 0})`"
          style="cursor:pointer"
          @click="selectedLocation = loc"
        >
          <!-- status ring -->
          <circle
            :r="NODE_R + 4"
            :fill="statusColor(loc)"
            :opacity="isExplored(loc) ? 0.25 : 0.1"
          />
          <!-- main fill -->
          <circle
            :r="NODE_R"
            :fill="loc.id === pcLocationId ? '#67c23a' : (isExplored(loc) ? '#fff' : '#c0c4cc')"
            :stroke="loc.id === pcLocationId ? '#67c23a' : '#dcdfe6'"
            :stroke-width="loc.id === pcLocationId ? 3 : 1.5"
            :opacity="isExplored(loc) ? 1 : 0.5"
          />
          <!-- name label -->
          <text
            text-anchor="middle"
            dominant-baseline="middle"
            font-size="11"
            font-weight="600"
            :fill="loc.id === pcLocationId ? '#fff' : (isExplored(loc) ? '#303133' : '#909399')"
            :opacity="isExplored(loc) ? 1 : 0.7"
          >{{ loc.name }}</text>
          <!-- current indicator -->
          <text
            v-if="loc.id === pcLocationId"
            y="44"
            text-anchor="middle"
            font-size="9"
            fill="#67c23a"
          >▲ 当前</text>
        </g>
      </svg>
    </div>

    <!-- Existing grid list view -->
    <div v-else class="locations-grid">
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

/* tabs */
.map-tabs { display: flex; gap: 4px; margin-bottom: 10px; }
.tab-btn {
  padding: 4px 16px; border-radius: 4px; border: 1px solid #dcdfe6;
  background: #f5f7fa; color: #606266; cursor: pointer; font-size: 13px;
  transition: background 0.15s, color 0.15s, border-color 0.15s;
}
.tab-btn:hover { border-color: #409eff; color: #409eff; }
.tab-btn.active { background: #409eff; color: #fff; border-color: #409eff; }

/* SVG map */
.svg-container {
  border: 1px solid #dcdfe6; border-radius: 8px; overflow: hidden; background: #fafafa;
}

/* grid list */
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
