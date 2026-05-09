import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import type { ModelConfig, ModelConfigIn } from '@/api/types'
import { modelsApi } from '@/api/models'

export const useModelConfigsStore = defineStore('modelConfigs', () => {
  const items = ref<ModelConfig[]>([])
  const loading = ref(false)

  const defaultModel = computed<ModelConfig | null>(
    () => items.value.find((m) => m.is_default) ?? null,
  )
  const defaultModelId = computed<number | null>(() => defaultModel.value?.id ?? null)

  async function refresh() {
    loading.value = true
    try {
      items.value = await modelsApi.list()
    } finally {
      loading.value = false
    }
  }

  async function create(body: ModelConfigIn) {
    const m = await modelsApi.create(body)
    items.value.push(m)
    return m
  }

  async function update(id: number, body: ModelConfigIn) {
    const m = await modelsApi.update(id, body)
    const idx = items.value.findIndex((x) => x.id === id)
    if (idx >= 0) items.value[idx] = m
    return m
  }

  async function remove(id: number) {
    await modelsApi.remove(id)
    items.value = items.value.filter((x) => x.id !== id)
  }

  async function test(id: number) {
    return modelsApi.test(id)
  }

  async function setDefault(id: number) {
    const m = await modelsApi.setDefault(id)
    // Single-source-of-truth on backend; client mirrors it locally so the UI
    // updates immediately without a full refetch.
    for (const x of items.value) {
      x.is_default = x.id === m.id
    }
    return m
  }

  /** First-choice picker for "无 session 上下文的 LLM 调用"（wizard 等）：
   * 优先用户显式标记的默认模型；若未设置，回退到列表里第一条。返回 null
   * 表示尚无任何模型。 */
  function preferredId(): number | null {
    if (defaultModelId.value !== null) return defaultModelId.value
    return items.value[0]?.id ?? null
  }

  return {
    items, loading, refresh, create, update, remove, test, setDefault,
    defaultModel, defaultModelId, preferredId,
  }
})
