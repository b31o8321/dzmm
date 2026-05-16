<script setup lang="ts">
import { ref, watch } from 'vue'
import { sessionsApi } from '@/api/sessions'

const props = defineProps<{
  modelValue: boolean
  sessionId: number
  turnNum: number
}>()
const emit = defineEmits<{ (e: 'update:modelValue', v: boolean): void }>()

type ChainData = Awaited<ReturnType<typeof sessionsApi.turnDebugChain>>
const chain = ref<ChainData | null>(null)
const loading = ref(false)
const error = ref('')
const activeTab = ref('director')

watch(
  () => props.modelValue,
  async (open) => {
    if (!open) return
    loading.value = true
    error.value = ''
    chain.value = null
    try {
      chain.value = await sessionsApi.turnDebugChain(props.sessionId, props.turnNum)
      // Auto-select first tab that has data
      if (chain.value.director.length) activeTab.value = 'director'
      else if (chain.value.scene.length) activeTab.value = 'scene'
      else if (chain.value.npcs.length) activeTab.value = `npc-${chain.value.npcs[0].name}`
    } catch (e: any) {
      error.value = e.message ?? '加载失败'
    } finally {
      loading.value = false
    }
  },
  // immediate: true so that when the dialog is mounted with v-if and
  // modelValue already true, the load fires on mount instead of waiting
  // for a value change that never comes.
  { immediate: true },
)

function roleLabel(role: string) {
  return role === 'user' ? '输入' : role === 'assistant' ? '输出' : role
}
function roleClass(role: string) {
  return role === 'user'
    ? 'bg-blue-50 border-blue-200'
    : role === 'assistant'
      ? 'bg-green-50 border-green-200'
      : 'bg-gray-50 border-gray-200'
}
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    @update:model-value="emit('update:modelValue', $event)"
    title=""
    width="860px"
    class="turn-debug-chain-dialog"
    :close-on-click-modal="true"
    destroy-on-close
  >
    <template #header>
      <span class="font-mono text-sm font-bold">🔍 回合 {{ turnNum }} 调试链路</span>
      <span v-if="chain" class="ml-3 text-xs text-slate-400 font-normal">
        tokens ↑{{ chain.tokens_in_total }} ↓{{ chain.tokens_out_total }}
      </span>
    </template>

    <div v-if="loading" class="py-12 text-center text-slate-400">加载中…</div>
    <div v-else-if="error" class="py-8 text-center text-red-500">{{ error }}</div>
    <div v-else-if="chain" class="space-y-3 max-h-[70vh] overflow-auto pr-1">

      <!-- Player action -->
      <div class="rounded border border-slate-200 bg-slate-50 p-3">
        <div class="text-xs font-bold text-slate-500 mb-1">玩家行动</div>
        <pre class="text-xs whitespace-pre-wrap break-words font-mono text-slate-700">{{ chain.player_action || '（无）' }}</pre>
      </div>

      <!-- Tabs for agent chains -->
      <el-tabs v-model="activeTab" type="border-card" class="text-xs">

        <!-- Director tab -->
        <el-tab-pane label="Director" name="director">
          <div v-if="!chain.director.length" class="text-slate-400 text-xs py-4 text-center">本回合 Director 未运行（复用上次指令）</div>
          <div v-for="(msg, i) in chain.director" :key="i" class="mb-3">
            <div class="flex items-center gap-2 mb-1">
              <span class="text-xs font-bold px-1.5 py-0.5 rounded"
                :class="msg.role === 'user' ? 'bg-blue-100 text-blue-700' : 'bg-green-100 text-green-700'">
                {{ roleLabel(msg.role) }}
              </span>
              <span v-if="msg.tokens_in" class="text-xs text-slate-400">↑{{ msg.tokens_in }}</span>
              <span v-if="msg.tokens_out" class="text-xs text-slate-400">↓{{ msg.tokens_out }}</span>
              <span v-if="msg.is_summary" class="text-xs text-amber-600 bg-amber-50 px-1 rounded">摘要</span>
            </div>
            <pre class="text-xs whitespace-pre-wrap break-words font-mono p-2 rounded border"
              :class="roleClass(msg.role)">{{ msg.content }}</pre>
          </div>
        </el-tab-pane>

        <!-- Scene tab -->
        <el-tab-pane label="Scene" name="scene">
          <div v-if="!chain.scene.length" class="text-slate-400 text-xs py-4 text-center">暂无 Scene 数据（旧版回合）</div>
          <div v-for="(msg, i) in chain.scene" :key="i" class="mb-3">
            <div class="flex items-center gap-2 mb-1">
              <span class="text-xs font-bold px-1.5 py-0.5 rounded"
                :class="msg.role === 'user' ? 'bg-blue-100 text-blue-700' : 'bg-green-100 text-green-700'">
                {{ roleLabel(msg.role) }}
              </span>
              <span v-if="msg.tokens_in" class="text-xs text-slate-400">↑{{ msg.tokens_in }}</span>
              <span v-if="msg.tokens_out" class="text-xs text-slate-400">↓{{ msg.tokens_out }}</span>
            </div>
            <pre class="text-xs whitespace-pre-wrap break-words font-mono p-2 rounded border"
              :class="roleClass(msg.role)">{{ msg.content }}</pre>
          </div>
        </el-tab-pane>

        <!-- NPC tabs -->
        <el-tab-pane
          v-for="npc in chain.npcs"
          :key="npc.name"
          :label="npc.name"
          :name="`npc-${npc.name}`"
        >
          <div v-for="(msg, i) in npc.messages" :key="i" class="mb-3">
            <div class="flex items-center gap-2 mb-1">
              <span class="text-xs font-bold px-1.5 py-0.5 rounded"
                :class="msg.role === 'user' ? 'bg-blue-100 text-blue-700' : 'bg-green-100 text-green-700'">
                {{ roleLabel(msg.role) }}
              </span>
              <span v-if="msg.tokens_in" class="text-xs text-slate-400">↑{{ msg.tokens_in }}</span>
              <span v-if="msg.tokens_out" class="text-xs text-slate-400">↓{{ msg.tokens_out }}</span>
            </div>
            <pre class="text-xs whitespace-pre-wrap break-words font-mono p-2 rounded border"
              :class="roleClass(msg.role)">{{ msg.content }}</pre>
          </div>
        </el-tab-pane>

        <!-- Applied events tab -->
        <el-tab-pane label="状态变化" name="events">
          <div v-if="!chain.applied_events.length" class="text-slate-400 text-xs py-4 text-center">本回合无状态变化</div>
          <div v-for="(ev, i) in chain.applied_events" :key="i"
            class="mb-2 text-xs font-mono bg-purple-50 border border-purple-200 rounded p-2">
            <span class="font-bold text-purple-700">{{ (ev as any).type }}</span>
            <pre class="whitespace-pre-wrap break-words text-slate-600 mt-1">{{ JSON.stringify((ev as any).payload ?? ev, null, 2) }}</pre>
          </div>
        </el-tab-pane>
      </el-tabs>
    </div>
  </el-dialog>
</template>

<style scoped>
.turn-debug-chain-dialog :deep(.el-tabs__content) {
  max-height: 50vh;
  overflow-y: auto;
}
</style>
