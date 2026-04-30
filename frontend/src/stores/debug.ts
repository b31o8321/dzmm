import { defineStore } from 'pinia'
import { ref, watch } from 'vue'

const STORAGE_KEY = 'dzmm.debugMode'

// Konami-style activation sequence: ↑↑↓↓←→←→
// 8 keys, memorable, won't accidentally trigger via typing.
const SEQUENCE = [
  'ArrowUp', 'ArrowUp', 'ArrowDown', 'ArrowDown',
  'ArrowLeft', 'ArrowRight', 'ArrowLeft', 'ArrowRight',
] as const

export const useDebugStore = defineStore('debug', () => {
  const enabled = ref(loadFromStorage())
  const buffer: string[] = []

  watch(enabled, (v) => {
    try {
      if (v) localStorage.setItem(STORAGE_KEY, '1')
      else localStorage.removeItem(STORAGE_KEY)
    } catch { /* private mode etc. */ }
  })

  function loadFromStorage(): boolean {
    try {
      return localStorage.getItem(STORAGE_KEY) === '1'
    } catch {
      return false
    }
  }

  function feedKey(key: string): boolean {
    // Returns true if the sequence just completed (toggled).
    buffer.push(key)
    if (buffer.length > SEQUENCE.length) buffer.shift()
    if (
      buffer.length === SEQUENCE.length &&
      buffer.every((k, i) => k === SEQUENCE[i])
    ) {
      enabled.value = !enabled.value
      buffer.length = 0
      return true
    }
    return false
  }

  return { enabled, feedKey }
})
