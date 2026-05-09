<script setup lang="ts">
import { computed, ref } from 'vue'
import type { WorldLocationData, WorldNPCStateData, WorldEventStateData, LocationDetail } from '@/api/framework'

const props = defineProps<{
  locations: WorldLocationData[]
  npcStates: WorldNPCStateData[]
  eventStates: WorldEventStateData[]
  pcLocationId: number | null
  factionNames: Record<number, string>
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
