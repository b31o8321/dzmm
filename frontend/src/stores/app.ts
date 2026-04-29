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

function loadTourCompleted(): boolean {
  try {
    return typeof localStorage !== 'undefined' &&
      localStorage.getItem('dzmm.tour_completed') === '1'
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
 *  - whether the first-launch onboarding tour has been completed
 *  - the current tour step (0 = inactive, 1..N = active step)
 */
export const useAppStore = defineStore('app', () => {
  const isTauri = ref(
    typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window,
  )
  const lanMode = ref(false)
  const lanUrl = ref<string | null>(null)
  const muted = ref(loadMuted())
  const tourCompleted = ref(loadTourCompleted())
  const tourStep = ref<number>(0) // 0 = hidden, 1..N = active step

  function completeTour() {
    tourCompleted.value = true
    tourStep.value = 0
    try {
      localStorage.setItem('dzmm.tour_completed', '1')
    } catch {
      /* ignore */
    }
  }

  function restartTour() {
    tourCompleted.value = false
    tourStep.value = 1
    try {
      localStorage.removeItem('dzmm.tour_completed')
    } catch {
      /* ignore */
    }
  }

  return {
    isTauri,
    lanMode,
    lanUrl,
    muted,
    tourCompleted,
    tourStep,
    completeTour,
    restartTour,
  }
})
