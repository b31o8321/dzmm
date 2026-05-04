<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { sessionsApi } from '@/api/sessions'
import { ElMessage } from 'element-plus'

const props = defineProps<{ sessionId: number }>()

interface DebugState {
  doom_score: number
  turn_count: number
  scene_turn_count: number
  settings: Record<string, unknown>
  stats: Record<string, number>
  inventory: string[]
}

const state = ref<DebugState | null>(null)
const saving = ref(false)

async function load() {
  try {
    state.value = await sessionsApi.debugState(props.sessionId)
  } catch (e: any) {
    ElMessage.error('加载调试状态失败: ' + (e.message ?? ''))
  }
}

async function saveDoom() {
  if (!state.value) return
  saving.value = true
  try {
    await sessionsApi.patchDebugState(props.sessionId, {
      doom_score: state.value.doom_score,
    })
    ElMessage.success('厄运值已更新')
  } catch (e: any) {
    ElMessage.error(e.message ?? '保存失败')
  } finally {
    saving.value = false
  }
}

async function saveStats() {
  if (!state.value) return
  saving.value = true
  try {
    await sessionsApi.patchDebugState(props.sessionId, {
      stats_json: JSON.stringify(state.value.stats),
      inventory_json: JSON.stringify(state.value.inventory),
    })
    ElMessage.success('数值已更新')
  } catch (e: any) {
    ElMessage.error(e.message ?? '保存失败')
  } finally {
    saving.value = false
  }
}

async function saveTurns() {
  if (!state.value) return
  saving.value = true
  try {
    await sessionsApi.patchDebugState(props.sessionId, {
      turn_count: state.value.turn_count,
      scene_turn_count: state.value.scene_turn_count,
    })
    ElMessage.success('回合数已更新')
  } catch (e: any) {
    ElMessage.error(e.message ?? '保存失败')
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="text-xs font-mono bg-yellow-50 border border-yellow-300 rounded p-3 space-y-3">
    <div class="flex items-center justify-between">
      <span class="font-bold text-yellow-800">🐛 Debug 数值编辑器</span>
      <button class="text-slate-400 hover:text-slate-600 text-xs" @click="load">↺ 刷新</button>
    </div>

    <template v-if="state">
      <!-- Doom score -->
      <div class="space-y-1">
        <div class="text-slate-600 font-medium">厄运值 (doom_score): {{ state.doom_score }}</div>
        <div class="flex gap-2 items-center">
          <el-slider
            v-model="state.doom_score"
            :min="0"
            :max="100"
            :step="5"
            size="small"
            class="flex-1"
          />
          <el-button size="small" :loading="saving" @click="saveDoom">保存</el-button>
        </div>
      </div>

      <!-- Turn counts -->
      <div class="space-y-1">
        <div class="text-slate-600 font-medium">回合计数</div>
        <div class="flex gap-2 items-center">
          <span class="text-slate-500 w-20">turn_count</span>
          <el-input-number v-model="state.turn_count" :min="0" size="small" controls-position="right" />
        </div>
        <div class="flex gap-2 items-center">
          <span class="text-slate-500 w-20">scene_turn</span>
          <el-input-number v-model="state.scene_turn_count" :min="0" size="small" controls-position="right" />
        </div>
        <el-button size="small" :loading="saving" @click="saveTurns">保存回合数</el-button>
      </div>

      <!-- PC stats -->
      <div class="space-y-1">
        <div class="text-slate-600 font-medium">PC 属性</div>
        <div
          v-for="(val, key) in state.stats"
          :key="key"
          class="flex gap-2 items-center"
        >
          <span class="text-slate-500 w-20">{{ key }}</span>
          <el-input-number
            v-model="(state.stats as Record<string, number>)[key as string]"
            size="small"
            controls-position="right"
          />
        </div>
        <el-button size="small" :loading="saving" @click="saveStats">保存属性</el-button>
      </div>

      <!-- Settings flags -->
      <div class="space-y-1">
        <div class="text-slate-600 font-medium">会话设置</div>
        <div v-for="(val, key) in state.settings" :key="key" class="text-slate-500">
          {{ key }}: <span class="text-slate-800">{{ JSON.stringify(val) }}</span>
        </div>
      </div>
    </template>

    <div v-else class="text-slate-400 italic">加载中…</div>
  </div>
</template>
