import { defineStore } from 'pinia'
import { ref } from 'vue'
import { standaloneScreenplayApi } from '@/api/screenplays'
import type { StandaloneScreenplay, StandaloneScreenplayIn } from '@/api/types'

export const useScreenplaysStore = defineStore('screenplays', () => {
  const byWorld = ref<Map<number, StandaloneScreenplay[]>>(new Map())

  async function fetchByWorld(worldId: number) {
    const items = await standaloneScreenplayApi.listByWorld(worldId)
    byWorld.value.set(worldId, items)
    return items
  }

  async function create(worldId: number, body: StandaloneScreenplayIn) {
    const sp = await standaloneScreenplayApi.create(worldId, body)
    const existing = byWorld.value.get(worldId) ?? []
    byWorld.value.set(worldId, [sp, ...existing])
    return sp
  }

  async function remove(id: number, worldId: number) {
    await standaloneScreenplayApi.remove(id)
    const existing = byWorld.value.get(worldId) ?? []
    byWorld.value.set(worldId, existing.filter(sp => sp.id !== id))
  }

  return { byWorld, fetchByWorld, create, remove }
})
