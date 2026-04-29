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

export interface PlotThreadItem {
  id: number
  type: string
  description: string
  importance: number
  status: 'active' | 'resolved' | 'abandoned'
  introduced_turn: number
  resolution: string
}

export interface NpcNote {
  turn: number
  text: string
}

export interface Npc {
  id: number
  name: string
  description: string
  favor: number
  state: string
  last_seen_turn: number
  purpose: string
  archetype: string
  affinity: Record<string, number>
  pinned: boolean
  notes: NpcNote[]
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
  threads: (id: number) =>
    api.get<PlotThreadItem[]>(`/sessions/${id}/threads`).then((r) => r.data),
  npcs: (id: number) =>
    api.get<Npc[]>(`/sessions/${id}/npcs`).then((r) => r.data),
  pinNpc: (sid: number, npcId: number, pinned: boolean) =>
    api.put<Npc>(`/sessions/${sid}/npcs/${npcId}/pin`, { pinned }).then((r) => r.data),
  deleteLastTurn: (id: number) =>
    api.delete(`/sessions/${id}/last_turn`).then(() => undefined),
  warmup: (id: number) =>
    api.post(`/sessions/${id}/warmup`).then(() => undefined),
}
