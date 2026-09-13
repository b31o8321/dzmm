import { describe, expect, it } from 'vitest'

import { draftGateReason } from './aiDraftGate'

describe('draftGateReason', () => {
  it('explains how to create the first profile when none exist', () => {
    expect(draftGateReason(0, '')).toContain('设置 → 本地模型')
  })

  it('asks to select when profiles exist but none chosen', () => {
    expect(draftGateReason(2, '')).toContain('选择一个已配置的模型档案')
  })

  it('returns null once a profile is chosen', () => {
    expect(draftGateReason(2, 'abc')).toBeNull()
  })
})
