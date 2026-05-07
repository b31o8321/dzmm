<script setup lang="ts">
import { computed } from 'vue'

interface PlotEvent {
  type: string
  description: string
  importance: number
  introduced_turn?: number
  resolution?: string | null
  status?: 'active' | 'resolved'
}

const props = defineProps<{ events: PlotEvent[] }>()

const sorted = computed(() =>
  [...props.events].sort((a, b) => (a.introduced_turn ?? 0) - (b.introduced_turn ?? 0)),
)

const TYPE_META: Record<string, { icon: string; color: string }> = {
  new_quest:        { icon: '🎯', color: 'blue' },
  hook_introduced:  { icon: '🪝', color: 'purple' },
  major_event:      { icon: '⚡', color: 'amber' },
  location_entered: { icon: '📍', color: 'green' },
  hook_resolved:    { icon: '✅', color: 'slate' },
}
</script>

<template>
  <div class="space-y-2 max-h-96 overflow-auto">
    <div v-if="!sorted.length" class="text-slate-400 italic text-sm">还没有大事件</div>
    <div
      v-for="(e, i) in sorted" :key="i"
      class="flex gap-2 text-xs border-l-2 pl-2 py-1.5"
      :class="
        e.status === 'resolved'
          ? 'border-slate-300 opacity-60'
          : (e.type === 'new_quest' ? 'border-blue-400'
             : e.type === 'hook_introduced' ? 'border-purple-400'
             : e.type === 'major_event' ? 'border-amber-400'
             : e.type === 'location_entered' ? 'border-green-400'
             : 'border-slate-300')
      "
    >
      <span class="flex-shrink-0">{{ TYPE_META[e.type]?.icon ?? '·' }}</span>
      <div class="flex-1 min-w-0">
        <div v-if="e.introduced_turn != null" class="text-slate-400">回合 {{ e.introduced_turn }}</div>
        <div class="text-slate-700">{{ e.description }}</div>
        <div v-if="e.resolution" class="text-slate-500 italic mt-0.5">→ {{ e.resolution }}</div>
      </div>
    </div>
  </div>
</template>
