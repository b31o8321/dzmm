import { api } from './client'
import type { World, WorldIn } from './types'

export const worldsApi = {
  list: () => api.get<World[]>('/worlds').then((r) => r.data),
  get: (id: number) => api.get<World>(`/worlds/${id}`).then((r) => r.data),
  create: (body: WorldIn) => api.post<World>('/worlds', body).then((r) => r.data),
}
