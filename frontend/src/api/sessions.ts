import { api } from './client'
import type { GameSession, SessionIn } from './types'

export interface MessageRow {
  id: number
  role: 'user' | 'assistant' | 'system'
  content: string
  turn: number
  tokens_in: number
  tokens_out: number
}

export interface SessionState {
  stats: Record<string, number>
  inventory: string[]
  npcs: { name: string; favor: number; state: string }[]
  threads: { type: string; description: string; importance: number }[]
}

export const sessionsApi = {
  list: () => api.get<GameSession[]>('/sessions').then((r) => r.data),
  get: (id: number) => api.get<GameSession>(`/sessions/${id}`).then((r) => r.data),
  create: (body: SessionIn) =>
    api.post<GameSession>('/sessions', body).then((r) => r.data),
  messages: (id: number) =>
    api.get<MessageRow[]>(`/sessions/${id}/messages`).then((r) => r.data),
  state: (id: number) =>
    api.get<SessionState>(`/sessions/${id}/state`).then((r) => r.data),
}
