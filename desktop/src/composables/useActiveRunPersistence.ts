const ACTIVE_RUN_KEY = 'dzmm-active-run'
const LEGACY_ACTIVE_RUN_KEY = 'dzmm-next-active-run'

export function rememberActiveRun(runId: string, storage: Storage = localStorage) {
  storage.setItem(ACTIVE_RUN_KEY, runId)
  storage.removeItem(LEGACY_ACTIVE_RUN_KEY)
}

export function readActiveRun(storage: Storage = localStorage): string | null {
  const activeRun = storage.getItem(ACTIVE_RUN_KEY)
  if (activeRun) return activeRun
  const legacyRun = storage.getItem(LEGACY_ACTIVE_RUN_KEY)
  if (legacyRun) {
    storage.setItem(ACTIVE_RUN_KEY, legacyRun)
    storage.removeItem(LEGACY_ACTIVE_RUN_KEY)
  }
  return legacyRun
}

export function forgetActiveRun(storage: Storage = localStorage) {
  storage.removeItem(ACTIVE_RUN_KEY)
  storage.removeItem(LEGACY_ACTIVE_RUN_KEY)
}
