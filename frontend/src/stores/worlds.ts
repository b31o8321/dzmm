import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { World, WorldIn } from '@/api/types'
import { worldsApi } from '@/api/worlds'

export const useWorldsStore = defineStore('worlds', () => {
  const items = ref<World[]>([])
  const loading = ref(false)

  async function refresh() {
    loading.value = true
    try {
      items.value = await worldsApi.list()
    } finally {
      loading.value = false
    }
  }

  async function create(body: WorldIn) {
    const w = await worldsApi.create(body)
    items.value.push(w)
    return w
  }

  async function update(id: number, body: WorldIn) {
    const w = await worldsApi.update(id, body)
    const idx = items.value.findIndex((x) => x.id === id)
    if (idx >= 0) items.value[idx] = w
    return w
  }

  async function remove(id: number) {
    await worldsApi.remove(id)
    items.value = items.value.filter((x) => x.id !== id)
  }

  return { items, loading, refresh, create, update, remove }
})
