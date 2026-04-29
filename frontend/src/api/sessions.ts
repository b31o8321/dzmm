import { api } from './client'
import type { GameSession, SessionIn } from './types'

export const sessionsApi = {
  list: () => api.get<GameSession[]>('/sessions').then((r) => r.data),
  get: (id: number) => api.get<GameSession>(`/sessions/${id}`).then((r) => r.data),
  create: (body: SessionIn) =>
    api.post<GameSession>('/sessions', body).then((r) => r.data),
}
