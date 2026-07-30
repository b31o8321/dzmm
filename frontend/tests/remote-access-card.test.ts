import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  fetchHealth: vi.fn(),
  invoke: vi.fn(),
  qrToDataUrl: vi.fn(),
  status: vi.fn(),
  pairRequests: vi.fn(),
  devices: vi.fn(),
  approveRequest: vi.fn(),
  denyRequest: vi.fn(),
  revokeDevice: vi.fn(),
  openPin: vi.fn(),
  createQr: vi.fn(),
}))

vi.mock('@/api/client', () => ({ fetchHealth: mocks.fetchHealth }))
vi.mock('@tauri-apps/api/core', () => ({ invoke: mocks.invoke }))
vi.mock('qrcode', () => ({ default: { toDataURL: mocks.qrToDataUrl } }))
vi.mock('@/api/remote', () => ({
  remoteApi: {
    status: mocks.status,
    pairRequests: mocks.pairRequests,
    devices: mocks.devices,
    approveRequest: mocks.approveRequest,
    denyRequest: mocks.denyRequest,
    revokeDevice: mocks.revokeDevice,
    openPin: mocks.openPin,
    createQr: mocks.createQr,
  },
}))

import RemoteAccessCard from '@/components/RemoteAccessCard.vue'
import { useAppStore } from '@/stores/app'

function buttonByText(wrapper: ReturnType<typeof mount>, text: string) {
  const button = wrapper.findAll('button').find((item) => item.text().includes(text))
  if (!button) throw new Error(`button not found: ${text}`)
  return button
}

describe('RemoteAccessCard', () => {
  let mode: 'local' | 'remote'

  beforeEach(() => {
    setActivePinia(createPinia())
    mode = 'local'
    vi.clearAllMocks()
    mocks.fetchHealth.mockImplementation(async () => ({
      ok: true,
      status: 'ok',
      version: '0.16.0',
      api_version: 1,
      remote_access: mode === 'remote',
    }))
    mocks.invoke.mockImplementation(async (command: string, args?: { remoteAccess?: boolean }) => {
      if (command === 'restart_backend') mode = args?.remoteAccess ? 'remote' : 'local'
      if (command === 'get_backend_status') {
        return {
          mode,
          pid: 4321,
          lan_addresses: ['http://192.168.31.242:8765'],
          error: null,
        }
      }
      return undefined
    })
    mocks.status.mockResolvedValue({
      server_id: 'server-1',
      pairing: { pin_open: false, qr_open: false, request_open: true },
      pending_count: 0,
      device_count: 0,
    })
    mocks.pairRequests.mockResolvedValue([])
    mocks.devices.mockResolvedValue([])
    mocks.qrToDataUrl.mockResolvedValue('data:image/png;base64,qr')
  })

  afterEach(() => {
    document.body.innerHTML = ''
  })

  it('requires trusted-network confirmation before switching to remote mode', async () => {
    const store = useAppStore()
    store.isTauri = true
    const wrapper = mount(RemoteAccessCard, {
      attachTo: document.body,
      global: { plugins: [ElementPlus] },
    })
    await flushPromises()

    expect(wrapper.get('[data-testid="backend-mode"]').text()).toContain('仅本机')
    expect(buttonByText(wrapper, '开启局域网访问').attributes('disabled')).toBeDefined()

    await wrapper.get('input[type="checkbox"]').setValue(true)
    await buttonByText(wrapper, '开启局域网访问').trigger('click')
    await flushPromises()

    expect(mocks.invoke).toHaveBeenCalledWith('restart_backend', { remoteAccess: true })
    expect(wrapper.get('[data-testid="backend-mode"]').text()).toContain('局域网已开放')
    expect(wrapper.text()).toContain('http://192.168.31.242:8765')
    wrapper.unmount()
  })

  it('creates a one-time QR payload without an admin or device token', async () => {
    mode = 'remote'
    const store = useAppStore()
    store.isTauri = true
    mocks.createQr.mockResolvedValue({
      claim: 'one-time-claim',
      expires_at: new Date(Date.now() + 300_000).toISOString(),
    })
    const wrapper = mount(RemoteAccessCard, {
      attachTo: document.body,
      global: { plugins: [ElementPlus] },
    })
    await flushPromises()

    await buttonByText(wrapper, '生成二维码').trigger('click')
    await flushPromises()

    const payload = String(mocks.qrToDataUrl.mock.calls[0][0])
    expect(payload).toContain('one-time-claim')
    expect(payload).toContain('server-1')
    expect(payload).not.toContain('device_token')
    expect(payload).not.toContain('admin')
    expect(wrapper.get('img[alt="dzmm 手机配对二维码"]').attributes('src'))
      .toBe('data:image/png;base64,qr')
    wrapper.unmount()
  })

  it('shows an actionable error and recovers on refresh', async () => {
    const store = useAppStore()
    store.isTauri = true
    mocks.status.mockRejectedValueOnce(new Error('状态接口暂时不可用'))
    const wrapper = mount(RemoteAccessCard, {
      attachTo: document.body,
      global: { plugins: [ElementPlus] },
    })
    await flushPromises()

    expect(wrapper.text()).toContain('状态接口暂时不可用')
    await buttonByText(wrapper, '重新读取').trigger('click')
    await flushPromises()

    expect(wrapper.text()).not.toContain('状态接口暂时不可用')
    expect(wrapper.text()).toContain('还没有配对设备')
    wrapper.unmount()
  })
})
