import { api } from './client'
import type { StandaloneScreenplay, StandaloneScreenplayIn } from './types'

export const standaloneScreenplayApi = {
  listByWorld: (worldId: number) =>
    api.get<StandaloneScreenplay[]>(`/worlds/${worldId}/screenplays`).then(r => r.data),

  create: (worldId: number, body: StandaloneScreenplayIn) =>
    api.post<StandaloneScreenplay>(`/worlds/${worldId}/screenplays`, body).then(r => r.data),

  get: (id: number) =>
    api.get<StandaloneScreenplay>(`/screenplays/${id}`).then(r => r.data),

  update: (id: number, body: Partial<StandaloneScreenplayIn>) =>
    api.patch<StandaloneScreenplay>(`/screenplays/${id}`, body).then(r => r.data),

  remove: (id: number) =>
    api.delete(`/screenplays/${id}`),
}
