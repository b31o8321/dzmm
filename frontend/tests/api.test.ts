import { describe, it, expect } from 'vitest'
import { worldsApi } from '../src/api/worlds'
import { charactersApi } from '../src/api/characters'
import { modelsApi } from '../src/api/models'
import { sessionsApi } from '../src/api/sessions'

describe('api modules', () => {
  it('exposes expected operations', () => {
    expect(worldsApi).toMatchObject({ list: expect.any(Function), create: expect.any(Function) })
    expect(charactersApi).toMatchObject({ list: expect.any(Function) })
    expect(modelsApi).toMatchObject({ test: expect.any(Function) })
    expect(sessionsApi).toMatchObject({ create: expect.any(Function) })
  })
})
