<script setup lang="ts">
import { computed } from 'vue'
import { ElDialog } from 'element-plus'
import type { MessageEvent } from '@/api/sessions'

const props = defineProps<{
  modelValue: boolean
  events: MessageEvent[]
  turn: number
}>()
const emit = defineEmits<{ 'update:modelValue': [boolean] }>()

const ICONS: Record<string, string> = {
  dice: '🎲',
  state_change: '📊',
  npc_update: '👥',
  plot_event: '🎯',
  character_xp: '⭐',
  era_begin: '📖',
  pc_goal: '🏁',
  pc_mood: '💭',
  npc_relation: '🔗',
  hidden_event: '🌑',
}

const groupedEvents = computed(() => {
  const groups: Record<string, MessageEvent[]> = {}
  for (const ev of props.events ?? []) {
    if (!groups[ev.type]) groups[ev.type] = []
    groups[ev.type].push(ev)
  }
  return groups
})
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    @update:model-value="(v) => emit('update:modelValue', v)"
    :title="`回合 ${turn} 事件明细`"
    width="600px"
  >
    <div v-if="!events || events.length === 0" class="text-center text-slate-500 py-4">
      （这一回合没有事件）
    </div>
    <div v-else>
      <div v-for="(evs, type) in groupedEvents" :key="type" class="mb-4">
        <h3 class="font-bold text-slate-700 mb-2">
          {{ ICONS[type] || '⚙️' }} {{ type }} ({{ evs.length }})
        </h3>
        <div
          v-for="(ev, i) in evs"
          :key="i"
          class="bg-slate-50 border rounded p-2 mb-2 text-sm"
        >
          <pre class="text-xs whitespace-pre-wrap font-mono">{{ JSON.stringify(ev.payload, null, 2) }}</pre>
          <div v-if="ev.content" class="text-slate-600 mt-1">{{ ev.content }}</div>
        </div>
      </div>
    </div>
  </el-dialog>
</template>
