import { describe, expect, it } from 'vitest'

import { shouldResetRetriableAction } from './useRunBoundary'

describe('useRunBoundary', () => {
  it('resets a retry when entering another Run', () => {
    expect(shouldResetRetriableAction('run-a', 'run-b')).toBe(true)
    expect(shouldResetRetriableAction(undefined, 'run-a')).toBe(true)
  })

  it('keeps the retry boundary stable while refreshing the same Run', () => {
    expect(shouldResetRetriableAction('run-a', 'run-a')).toBe(false)
  })
})
