import { describe, expect, it } from 'vitest'

import { consumePendingRunOperation, markPendingRunOperation } from './usePendingRunRecovery'

describe('pending Run recovery marker', () => {
  function storage(): Storage {
    const values = new Map<string, string>()
    return {
      getItem: (key) => values.get(key) ?? null,
      setItem: (key, value) => values.set(key, value),
      removeItem: (key) => values.delete(key),
      clear: () => values.clear(),
      key: (index) => [...values.keys()][index] ?? null,
      get length() { return values.size },
    } as Storage
  }

  it('records a pending operation and consumes it exactly once', () => {
    const local = storage()
    markPendingRunOperation(true, local)

    expect(consumePendingRunOperation(local)).toBe(true)
    expect(consumePendingRunOperation(local)).toBe(false)
  })

  it('clears the marker when the operation finishes normally', () => {
    const local = storage()
    markPendingRunOperation(true, local)
    markPendingRunOperation(false, local)

    expect(consumePendingRunOperation(local)).toBe(false)
  })
})
