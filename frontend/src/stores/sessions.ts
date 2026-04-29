import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { GameSession, SessionIn } from '@/api/types'
import { sessionsApi } from '@/api/sessions'

export const useSessionsStore = defineStore('sessions', () => {
  const items = ref<GameSession[]>([])
  const loading = ref(false)

  async function refresh() {
    loading.value = true
    try {
      items.value = await sessionsApi.list()
    } finally {
      loading.value = false
    }
  }

  async function create(body: SessionIn) {
    const s = await sessionsApi.create(body)
    items.value.push(s)
    return s
  }

  async function get(id: number) {
    return sessionsApi.get(id)
  }

  return { items, loading, refresh, create, get }
})
