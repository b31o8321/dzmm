<script lang="ts">
export interface Part {
  type: 'narration' | 'dialogue' | 'pc_action'
  speaker?: string
  text: string
}
</script>

<script setup lang="ts">
import MarkdownView from './MarkdownView.vue'

defineProps<{ part: Part; pcName?: string }>()
</script>

<template>
  <!-- narration: 居中灰色无气泡 -->
  <div
    v-if="part.type === 'narration'"
    class="text-slate-600 italic px-2 py-1"
  >
    <MarkdownView :source="part.text" />
  </div>

  <!-- pc_action: 右侧蓝色气泡（PC 视角） -->
  <div v-else-if="part.type === 'pc_action'" class="flex justify-end my-2">
    <div
      class="max-w-[75%] bg-blue-50 border border-blue-200 rounded-lg p-3 text-slate-800"
    >
      <div class="text-xs text-blue-700 font-bold mb-1">
        {{ pcName ?? 'PC' }}
      </div>
      <MarkdownView :source="part.text" />
    </div>
  </div>

  <!-- dialogue: 左侧琥珀色气泡（NPC 对白） -->
  <div v-else class="flex justify-start my-2">
    <div
      class="max-w-[75%] bg-amber-50 border border-amber-200 rounded-lg p-3 text-slate-800"
    >
      <div class="text-xs text-amber-800 font-bold mb-1">
        {{ part.speaker || '???' }}
      </div>
      <MarkdownView :source="part.text" />
    </div>
  </div>
</template>
