import { api } from './client'

export interface RemoteAdminStatus {
  server_id: string
  pairing: {
    pin_open: boolean
    qr_open: boolean
    request_open: boolean
  }
  pending_count: number
  device_count: number
}

export interface RemotePairRequest {
  request_id: string
  device_id: string
  device_name: string
  client_ip: string
  created_at: string
  expires_at: string
}

export interface PairedDevice {
  device_id: string
  name: string
  paired_at: string
  last_seen: string | null
}

export interface PairingWindow {
  expires_at: string
}

export interface PinPairingWindow extends PairingWindow {
  pin: string
}

export interface QrPairingWindow extends PairingWindow {
  claim: string
}

export const remoteApi = {
  async status(): Promise<RemoteAdminStatus> {
    const response = await api.get<RemoteAdminStatus>('/remote/admin/status')
    return response.data
  },

  async pairRequests(): Promise<RemotePairRequest[]> {
    const response = await api.get<RemotePairRequest[]>('/remote/admin/pair-requests')
    return response.data
  },

  async approveRequest(requestId: string): Promise<void> {
    await api.post(`/remote/admin/pair-requests/${encodeURIComponent(requestId)}/approve`)
  },

  async denyRequest(requestId: string): Promise<void> {
    await api.post(`/remote/admin/pair-requests/${encodeURIComponent(requestId)}/deny`)
  },

  async devices(): Promise<PairedDevice[]> {
    const response = await api.get<PairedDevice[]>('/remote/admin/devices')
    return response.data
  },

  async revokeDevice(deviceId: string): Promise<void> {
    await api.delete(`/remote/admin/devices/${encodeURIComponent(deviceId)}`)
  },

  async openPin(): Promise<PinPairingWindow> {
    const response = await api.post<PinPairingWindow>('/remote/admin/pairing/pin')
    return response.data
  },

  async createQr(): Promise<QrPairingWindow> {
    const response = await api.post<QrPairingWindow>('/remote/admin/pairing/qr')
    return response.data
  },
}
