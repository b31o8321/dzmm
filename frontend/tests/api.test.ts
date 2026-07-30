import { describe, it, expect } from 'vitest'
import { worldsApi } from '../src/api/worlds'
import { charactersApi } from '../src/api/characters'
import { modelsApi } from '../src/api/models'
import { sessionsApi } from '../src/api/sessions'
import { remoteApi } from '../src/api/remote'

describe('api modules', () => {
  it('exposes expected operations', () => {
    expect(worldsApi).toMatchObject({ list: expect.any(Function), create: expect.any(Function) })
    expect(charactersApi).toMatchObject({ list: expect.any(Function) })
    expect(modelsApi).toMatchObject({ test: expect.any(Function) })
    expect(sessionsApi).toMatchObject({
      create: expect.any(Function),
      createTurnRun: expect.any(Function),
      turnRun: expect.any(Function),
    })
    expect(remoteApi).toMatchObject({
      status: expect.any(Function),
      openPin: expect.any(Function),
      createQr: expect.any(Function),
      revokeDevice: expect.any(Function),
    })
  })
})
