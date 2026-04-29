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

  return { items, loading, refresh, create }
})
