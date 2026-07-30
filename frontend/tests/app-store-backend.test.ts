import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const invoke = vi.hoisted(() => vi.fn())
vi.mock('@tauri-apps/api/core', () => ({ invoke }))

import { useAppStore } from '@/stores/app'

describe('app backend lifecycle', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('starts every desktop launch in local-only mode', async () => {
    invoke.mockImplementation(async (command: string) => {
      if (command === 'get_backend_status') {
        return { mode: 'local', pid: 123, lan_addresses: [], error: null }
      }
      return undefined
    })
    const store = useAppStore()
    store.isTauri = true

    await store.startLocalBackend()

    expect(invoke).toHaveBeenNthCalledWith(1, 'start_backend', { lanMode: false })
    expect(store.backendMode).toBe('local')
    expect(store.lanMode).toBe(false)
  })

  it('tracks the restarting transition and resulting remote addresses', async () => {
    let releaseRestart: (() => void) | undefined
    invoke.mockImplementation((command: string) => {
      if (command === 'restart_backend') {
        return new Promise<void>((resolve) => { releaseRestart = resolve })
      }
      if (command === 'get_backend_status') {
        return Promise.resolve({
          mode: 'remote',
          pid: 456,
          lan_addresses: ['http://192.168.1.20:8765'],
          error: null,
        })
      }
      return Promise.resolve()
    })
    const store = useAppStore()
    store.isTauri = true

    const transition = store.setRemoteAccess(true)
    await vi.waitFor(() => {
      expect(invoke).toHaveBeenCalledWith('restart_backend', { remoteAccess: true })
    })
    expect(store.backendMode).toBe('restarting')
    expect(releaseRestart).toBeTypeOf('function')
    releaseRestart!()
    await transition

    expect(store.backendMode).toBe('remote')
    expect(store.lanAddresses).toEqual(['http://192.168.1.20:8765'])
  })
})
