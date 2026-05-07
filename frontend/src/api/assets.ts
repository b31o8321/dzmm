import { api } from './client'

export interface Asset {
  id: number
  kind: 'image' | 'audio' | 'font'
  source: 'local' | 'http' | 'builtin'
  mime: string
  width: number
  height: number
  duration_ms: number
  tag: Record<string, unknown>
  title: string
  uploaded_by: string
  url: string
  created_at: string | null
}

export interface AttachedAsset {
  slot: string
  extra: Record<string, unknown>
  asset: Asset
}

export const assetsApi = {
  list: (params: { kind?: string; category?: string; source?: string } = {}) =>
    api.get<Asset[]>('/assets', { params }).then((r) => r.data),

  upload: (file: File, kind: 'image' | 'audio', category: string, title?: string) => {
    const fd = new FormData()
    fd.append('file', file)
    fd.append('kind', kind)
    fd.append('category', category)
    if (title) fd.append('title', title)
    return api
      .post<Asset>('/assets/upload', fd, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      .then((r) => r.data)
  },

  delete: (id: number) => api.delete(`/assets/${id}`),

  attach: (
    assetId: number,
    ownerType: string,
    ownerId: number,
    slot: string,
    extra?: Record<string, unknown>,
  ) =>
    api
      .post(`/assets/${assetId}/attach`, {
        owner_type: ownerType,
        owner_id: ownerId,
        slot,
        extra: extra ?? {},
      })
      .then((r) => r.data),

  byOwner: (ownerType: string, ownerId: number, slot?: string) =>
    api
      .get<AttachedAsset[]>(`/assets/by_owner/${ownerType}/${ownerId}`, {
        params: slot ? { slot } : {},
      })
      .then((r) => r.data),
}
