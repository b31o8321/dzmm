import { ref, computed, watch } from 'vue'
import type { Ref } from 'vue'
import { modelsApi } from '@/api/models'
import type { ModelCheckResult } from '@/api/models'

export function useModelCheck(cfgId: Ref<number | null | undefined>) {
  const result = ref<ModelCheckResult | null>(null)
  const checking = ref(false)
  const error = ref(false)

  async function check() {
    const id = cfgId.value
    if (!id) {
      result.value = null
      return
    }
    checking.value = true
    error.value = false
    try {
      result.value = await modelsApi.check(id)
    } catch {
      error.value = true
      result.value = null
    } finally {
      checking.value = false
    }
  }

  watch(cfgId, () => check(), { immediate: true })

  const isOk = computed(() => {
    if (!result.value) return null
    const embedOk = result.value.embed_ok ?? true
    return result.value.narrative_ok && embedOk
  })

  const pullCommands = computed<string[]>(() =>
    (result.value?.missing ?? []).map((m) => `ollama pull ${m}`)
  )

  return { result, checking, error, isOk, pullCommands, check }
}
