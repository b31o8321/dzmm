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

function loadTtsSetting<T>(key: string, defaultVal: T): T {
  try {
    const v = typeof localStorage !== 'undefined' && localStorage.getItem(`dzmm.tts.${key}`)
    if (!v) return defaultVal
    if (typeof defaultVal === 'boolean') return (v === '1') as unknown as T
    if (typeof defaultVal === 'number') { const n = Number(v); return (isNaN(n) ? defaultVal : n) as unknown as T }
    return v as unknown as T
  } catch {
    return defaultVal
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

  const ttsEnabled = ref(loadTtsSetting('enabled', false))
  const _rawMode = loadTtsSetting('mode', 'edge')
  const ttsMode = ref<'edge' | 'cosyvoice' | 'local'>(
    (['edge', 'cosyvoice', 'local'].includes(_rawMode) ? _rawMode : 'edge') as 'edge' | 'cosyvoice' | 'local'
  )
  const ttsModelConfigId = ref(loadTtsSetting('model_config_id', 0))
  const ttsGmVoice = ref(loadTtsSetting('gm_voice', ''))
  const ttsPcVoice = ref(loadTtsSetting('pc_voice', ''))
  // Direct URL for external/LAN TTS service (OpenAI-compatible base URL, e.g. http://192.168.1.5:5001)
  const ttsDirectUrl = ref(loadTtsSetting('direct_url', ''))
  const ttsNarratorEnabled = ref(loadTtsSetting('narrator_enabled', true))
  const ttsPcEnabled = ref(loadTtsSetting('pc_enabled', true))
  const ttsNpcEnabled = ref(loadTtsSetting('npc_enabled', true))

  function saveTtsSettings() {
    try {
      localStorage.setItem('dzmm.tts.enabled', ttsEnabled.value ? '1' : '0')
      localStorage.setItem('dzmm.tts.mode', ttsMode.value)
      localStorage.setItem('dzmm.tts.model_config_id', String(ttsModelConfigId.value))
      localStorage.setItem('dzmm.tts.gm_voice', ttsGmVoice.value)
      localStorage.setItem('dzmm.tts.pc_voice', ttsPcVoice.value)
      localStorage.setItem('dzmm.tts.direct_url', ttsDirectUrl.value)
      localStorage.setItem('dzmm.tts.narrator_enabled', ttsNarratorEnabled.value ? '1' : '0')
      localStorage.setItem('dzmm.tts.pc_enabled', ttsPcEnabled.value ? '1' : '0')
      localStorage.setItem('dzmm.tts.npc_enabled', ttsNpcEnabled.value ? '1' : '0')
    } catch { /* ignore */ }
  }

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
    ttsEnabled,
    ttsMode,
    ttsModelConfigId,
    ttsGmVoice,
    ttsPcVoice,
    ttsDirectUrl,
    ttsNarratorEnabled,
    ttsPcEnabled,
    ttsNpcEnabled,
    saveTtsSettings,
  }
})
