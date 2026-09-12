import { describe, expect, it } from 'vitest'

import { matchChoiceByInput } from './choiceMatch'

const choices = [
  { id: 'help-lan', label: '援手李明' },
  { id: 'keep-secret', label: '替苏菲亚保守秘密' },
  { id: 'investigate', label: '在钟楼追查新线索' },
]

describe('matchChoiceByInput', () => {
  it('matches normalized identical labels ignoring punctuation', () => {
    expect(matchChoiceByInput('援手李明', choices)?.id).toBe('help-lan')
    expect(matchChoiceByInput('  援手 李明。', choices)?.id).toBe('help-lan')
  })

  it('matches containment in either direction', () => {
    expect(matchChoiceByInput('我选择：替苏菲亚保守秘密', choices)?.id).toBe('keep-secret')
    expect(matchChoiceByInput('保守秘密', choices)?.id).toBe('keep-secret')
  })

  it('returns null for unrelated free-form input or short noise', () => {
    expect(matchChoiceByInput('我去码头喝一杯酒', choices)).toBeNull()
    expect(matchChoiceByInput('嗯', choices)).toBeNull()
    expect(matchChoiceByInput('', choices)).toBeNull()
  })
})
