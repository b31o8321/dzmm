const ACTIVE_RUN_KEY = 'dzmm-next-active-run'

export function rememberActiveRun(runId: string, storage: Storage = localStorage) {
  storage.setItem(ACTIVE_RUN_KEY, runId)
}

export function readActiveRun(storage: Storage = localStorage): string | null {
  return storage.getItem(ACTIVE_RUN_KEY)
}

export function forgetActiveRun(storage: Storage = localStorage) {
  storage.removeItem(ACTIVE_RUN_KEY)
}
