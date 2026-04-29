import { defineStore } from 'pinia'
import { ref } from 'vue'

function loadMuted(): boolean {
  try {
    return typeof localStorage !== 'undefined' &&
      localStorage.getItem('dzmm.muted') === '1'
  } catch {
    return false
  }
}

/**
 * App-level UI state that doesn't fit cleanly into resource stores:
 *  - whether we're running inside the Tauri webview
 *  - whether LAN mode is enabled (backend bound 0.0.0.0)
 *  - the LAN URL to advertise to the user (so phones can connect)
 *  - whether BGM/SFX is muted (persisted to localStorage)
 */
export const useAppStore = defineStore('app', () => {
  const isTauri = ref(
    typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window,
  )
  const lanMode = ref(false)
  const lanUrl = ref<string | null>(null)
  const muted = ref(loadMuted())

  return { isTauri, lanMode, lanUrl, muted }
})
