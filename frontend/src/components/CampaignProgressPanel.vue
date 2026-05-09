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
