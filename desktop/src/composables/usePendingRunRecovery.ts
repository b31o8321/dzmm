const PENDING_RUN_OPERATION_KEY = 'dzmm-pending-run-operation'
const LEGACY_PENDING_RUN_OPERATION_KEY = 'dzmm-next-pending-run-operation'

export function markPendingRunOperation(pending: boolean, storage: Storage = localStorage) {
  if (pending) storage.setItem(PENDING_RUN_OPERATION_KEY, '1')
  else storage.removeItem(PENDING_RUN_OPERATION_KEY)
  storage.removeItem(LEGACY_PENDING_RUN_OPERATION_KEY)
}

export function consumePendingRunOperation(storage: Storage = localStorage): boolean {
  const interrupted = storage.getItem(PENDING_RUN_OPERATION_KEY) === '1'
    || storage.getItem(LEGACY_PENDING_RUN_OPERATION_KEY) === '1'
  storage.removeItem(PENDING_RUN_OPERATION_KEY)
  storage.removeItem(LEGACY_PENDING_RUN_OPERATION_KEY)
  return interrupted
}
