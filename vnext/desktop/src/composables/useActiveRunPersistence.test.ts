import { describe, expect, it } from 'vitest'

import { forgetActiveRun, readActiveRun, rememberActiveRun } from './useActiveRunPersistence'

describe('active Run persistence', () => {
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

  it('remembers and reads the Run that should reopen after restart', () => {
    const local = storage()

    rememberActiveRun('run-imported', local)

    expect(readActiveRun(local)).toBe('run-imported')
  })

  it('replaces an old Run and can forget it explicitly', () => {
    const local = storage()
    rememberActiveRun('run-old', local)
    rememberActiveRun('run-new', local)

    expect(readActiveRun(local)).toBe('run-new')
    forgetActiveRun(local)
    expect(readActiveRun(local)).toBeNull()
  })
})
