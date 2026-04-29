import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { ModelConfig, ModelConfigIn } from '@/api/types'
import { modelsApi } from '@/api/models'

export const useModelConfigsStore = defineStore('modelConfigs', () => {
  const items = ref<ModelConfig[]>([])
  const loading = ref(false)

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

  async function test(id: number) {
    return modelsApi.test(id)
  }

  return { items, loading, refresh, create, test }
})
