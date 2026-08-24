<script setup lang="ts">
import {
  OPERATION_STAGE_LABELS,
  OPERATION_STAGE_STEPS,
  isOperationStageTerminal,
} from '../composables/operationStages'
import type { VisibleOperation } from '../composables/useOperationStatus'

defineProps<{
  operation: VisibleOperation
  cancellable: boolean
  cancelLabel?: string
}>()

defineEmits<{ cancel: [] }>()
</script>

<template>
  <section class="operation-status" :class="operation.stage" role="status" aria-live="polite">
    <div><i></i><b>{{ operation.label }}</b><span>{{ (operation.elapsedMs / 1000).toFixed(1) }} 秒</span></div>
    <ol><li v-for="stage in OPERATION_STAGE_STEPS" :key="stage" :class="{ active: operation.stage === stage }">{{ OPERATION_STAGE_LABELS[stage] }}</li></ol>
    <small v-if="operation.elapsedMs > 8000 && !isOperationStageTerminal(operation.stage)">本地模型可能仍在加载或生成；你可以继续等待，失败前不会写入半个回合。</small>
    <button v-if="cancellable" class="minor-action operation-cancel" type="button" @click="$emit('cancel')">{{ cancelLabel ?? '取消本次行动' }}</button>
  </section>
</template>
