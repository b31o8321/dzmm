import { onUnmounted, ref } from 'vue'
import type { OperationStage } from './operationStages'

export type { OperationStage } from './operationStages'

export type VisibleOperation = {
  stage: OperationStage
  label: string
  elapsedMs: number
}

export function useOperationStatus() {
  const visibleOperation = ref<VisibleOperation | null>(null)
  let ticker: ReturnType<typeof setInterval> | null = null
  let startedAt = 0

  function clearTicker() {
    if (ticker) clearInterval(ticker)
    ticker = null
  }

  function begin(label: string, stage: OperationStage = 'preparing') {
    clearTicker()
    startedAt = Date.now()
    visibleOperation.value = { stage, label, elapsedMs: 0 }
    ticker = setInterval(() => {
      if (visibleOperation.value) {
        visibleOperation.value.elapsedMs = Date.now() - startedAt
      }
    }, 250)
  }

  function advance(stage: OperationStage, label: string) {
    if (visibleOperation.value) visibleOperation.value = { ...visibleOperation.value, stage, label }
  }

  function end(stage: Extract<OperationStage, 'completed' | 'failed' | 'cancelled'>, label: string) {
    clearTicker()
    if (!visibleOperation.value) return
    const completed = { ...visibleOperation.value, stage, label }
    visibleOperation.value = completed
    setTimeout(() => {
      if (visibleOperation.value === completed) visibleOperation.value = null
    }, stage === 'completed' ? 900 : 4000)
  }

  onUnmounted(clearTicker)
  return { visibleOperation, begin, advance, end }
}
