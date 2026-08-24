import { describe, expect, it } from 'vitest'

import {
  OPERATION_CANCELLABLE_STAGES,
  OPERATION_STAGE_LABELS,
  OPERATION_STAGES,
  OPERATION_TERMINAL_STAGES,
  isOperationStageCancellable,
  isOperationStageTerminal,
} from './operationStages'

describe('operation stage contract', () => {
  it('keeps one ordered stage vocabulary for the player', () => {
    expect(OPERATION_STAGES).toEqual([
      'preparing',
      'connecting',
      'generating',
      'applying',
      'completed',
      'failed',
      'cancelled',
      'restored',
    ])
    expect(Object.keys(OPERATION_STAGE_LABELS)).toEqual(OPERATION_STAGES)
  })

  it('makes cancellation and terminal boundaries explicit', () => {
    expect(OPERATION_CANCELLABLE_STAGES).toEqual([
      'preparing',
      'connecting',
      'generating',
    ])
    expect(OPERATION_TERMINAL_STAGES).toEqual([
      'completed',
      'failed',
      'cancelled',
      'restored',
    ])
    expect(isOperationStageCancellable('generating')).toBe(true)
    expect(isOperationStageCancellable('applying')).toBe(false)
    expect(isOperationStageTerminal('restored')).toBe(true)
    expect(isOperationStageTerminal('connecting')).toBe(false)
  })
})
