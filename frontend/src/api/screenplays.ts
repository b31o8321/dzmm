import { api } from './client'
import type { StandaloneScreenplay, StandaloneScreenplayIn } from './types'

export const standaloneScreenplayApi = {
  listByWorld: (worldId: number) =>
    api.get<StandaloneScreenplay[]>(`/worlds/${worldId}/screenplays`).then(r => r.data),

  create: (worldId: number, body: StandaloneScreenplayIn) =>
    api.post<StandaloneScreenplay>(`/worlds/${worldId}/screenplays`, body).then(r => r.data),

  refs: (id: number) =>
    api.get<{ sessions: number }>(`/screenplays/${id}/refs`).then(r => r.data),

  remove: (id: number) =>
    api.delete(`/screenplays/${id}`),
}
