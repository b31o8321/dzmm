import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { Character, CharacterIn } from '@/api/types'
import { charactersApi } from '@/api/characters'

export const useCharactersStore = defineStore('characters', () => {
  const items = ref<Character[]>([])
  const loading = ref(false)

  async function refresh(worldId?: number) {
    loading.value = true
    try {
      items.value = await charactersApi.list(worldId)
    } finally {
      loading.value = false
    }
  }

  async function create(body: CharacterIn) {
    const c = await charactersApi.create(body)
    items.value.push(c)
    return c
  }

  async function update(id: number, body: CharacterIn) {
    const c = await charactersApi.update(id, body)
    const idx = items.value.findIndex((x) => x.id === id)
    if (idx >= 0) items.value[idx] = c
    return c
  }

  async function remove(id: number) {
    await charactersApi.remove(id)
    items.value = items.value.filter((x) => x.id !== id)
  }

  return { items, loading, refresh, create, update, remove }
})
