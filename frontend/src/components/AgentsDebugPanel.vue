<script setup lang="ts">
import { ref, watch } from 'vue'
import { sessionsApi, type AgentStreamInfo } from '@/api/sessions'

const props = defineProps<{ sessionId: number }>()
const streams = ref<AgentStreamInfo[]>([])
const loading = ref(false)

async function refresh() {
  loading.value = true
  try {
    const data = await sessionsApi.agents(props.sessionId)
    streams.value = data.streams
  } finally {
    loading.value = false
  }
}

watch(() => props.sessionId, refresh, { immediate: true })

function kindLabel(k: string, ref: string): string {
  if (k === 'gm_director') return '🎬 Director'
  if (k === 'npc') return `🎭 NPC: ${ref}`
  return `${k} ${ref}`
}
</script>

<template>
  <div class="p-4">
    <div class="flex items-center justify-between mb-3">
      <h3 class="font-semibold">多 Agent 状态（v0.10）</h3>
      <el-button size="small" :loading="loading" @click="refresh">刷新</el-button>
    </div>
    <div v-if="streams.length === 0" class="text-slate-400 text-sm">
      尚无 agent stream（首回合还没跑完，或者用的是 v0.9 legacy 模式）
    </div>
    <el-collapse v-else>
      <el-collapse-item
        v-for="st in streams"
        :key="st.id"
        :name="st.id"
      >
        <template #title>
          <span class="font-medium">{{ kindLabel(st.kind, st.ref) }}</span>
          <span class="text-xs text-slate-400 ml-2">
            上次运行：第 {{ st.last_run_turn }} 回合 · {{ st.recent_messages.length }} 条历史
          </span>
        </template>
        <div class="space-y-2 max-h-96 overflow-y-auto">
          <div
            v-for="(m, idx) in st.recent_messages"
            :key="idx"
            class="border-l-2 pl-2 text-xs"
            :class="{
              'border-amber-400 bg-amber-50': m.is_summary,
              'border-blue-400': m.role === 'user',
              'border-emerald-400': m.role === 'assistant',
              'border-slate-400': m.role === 'system' && !m.is_summary,
            }"
          >
            <div class="text-slate-500">
              turn {{ m.turn }} · {{ m.role }}
              <span v-if="m.is_summary" class="text-amber-600 font-semibold ml-1">
                [SUMMARY]
              </span>
            </div>
            <pre class="whitespace-pre-wrap font-mono text-slate-700">{{ m.content }}</pre>
          </div>
        </div>
      </el-collapse-item>
    </el-collapse>
  </div>
</template>
