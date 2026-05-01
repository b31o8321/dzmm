import { api } from './client'
import type { GameSession, SessionIn } from './types'

export interface MessageEvent {
  type: string
  payload: Record<string, any>
  content?: string
}

export interface MessageRow {
  id: number
  role: 'user' | 'assistant' | 'system'
  content: string
  turn: number
  tokens_in: number
  tokens_out: number
  events?: MessageEvent[]
  parts_json?: string | null
}

export interface SessionState {
  stats: Record<string, number>
  inventory: string[]
  pc_mood?: Record<string, number>
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
  emotion?: Record<string, number>
  pinned: boolean
  notes: NpcNote[]
  // v0.11: progressive reveal map. Each key is a field name (e.g.
  // "description", "purpose", "archetype", "state", "favor", "affinity",
  // "emotion") whose value is true when the player has learned it.
  // Optional for backwards-compat: if missing (legacy backend / mock), the
  // UI treats every field as revealed.
  revealed?: Record<string, boolean>
}

export interface RelationItem {
  id: number
  npc_a: string
  npc_b: string
  kind: string
  description: string
  introduced_turn: number
}

export interface TimelineItem {
  id: number
  turn: number
  event_text: string
  importance: number
  created_at?: string
}

export interface EraItem {
  id: number
  name: string
  started_turn: number
  description: string
}

export interface PCGoalItem {
  id: number
  description: string
  priority: 'high' | 'normal' | 'low'
  status: 'active' | 'completed' | 'abandoned'
  introduced_turn: number
  completed_turn: number | null
  completion_note: string
}

export const sessionsApi = {
  list: () => api.get<GameSession[]>('/sessions').then((r) => r.data),
  get: (id: number) => api.get<GameSession>(`/sessions/${id}`).then((r) => r.data),
  delete: (id: number) => api.delete(`/sessions/${id}`).then(() => undefined),
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
  goals: (id: number) =>
    api.get<PCGoalItem[]>(`/sessions/${id}/goals`).then((r) => r.data),
  updateGoalStatus: (
    sessionId: number, goalId: number,
    status: 'active' | 'completed' | 'abandoned', note?: string,
  ) =>
    api.put<PCGoalItem>(
      `/sessions/${sessionId}/goals/${goalId}/status`,
      { status, ...(note !== undefined ? { note } : {}) },
    ).then((r) => r.data),
  deleteLastTurn: (id: number) =>
    api.delete(`/sessions/${id}/last_turn`).then(() => undefined),
  warmup: (id: number) =>
    api.post(`/sessions/${id}/warmup`).then(() => undefined),
  timeline: (id: number) =>
    api.get<TimelineItem[]>(`/sessions/${id}/timeline`).then((r) => r.data),
  eras: (id: number) =>
    api.get<EraItem[]>(`/sessions/${id}/eras`).then((r) => r.data),
  relations: (id: number) =>
    api.get<RelationItem[]>(`/sessions/${id}/relations`).then((r) => r.data),
  exportSession: (id: number, format: 'json' | 'md' = 'json') =>
    api
      .get(`/sessions/${id}/export`, {
        params: { format },
        responseType: 'blob',
      })
      .then((r) => r.data as Blob),

  // v0.13.1 — player feedback
  postFeedback: (
    id: number,
    body: { content: string; kind?: 'bug' | 'suggestion' | 'praise' | 'other'; message_id?: number },
  ) =>
    api
      .post(`/sessions/${id}/feedback`, body)
      .then((r) => r.data as FeedbackItem),
  hiddenEvents: (id: number, includeResolved = false) =>
    api.get<HiddenEventItem[]>(`/sessions/${id}/hidden_events`, {
      params: includeResolved ? { include_resolved: true } : {},
    }).then((r) => r.data),

  listFeedback: (id: number) =>
    api.get<FeedbackItem[]>(`/sessions/${id}/feedback`).then((r) => r.data),
}

export interface FeedbackItem {
  id: number
  turn: number
  message_id: number | null
  kind: 'bug' | 'suggestion' | 'praise' | 'other'
  content: string
  created_at: string
}

export interface HiddenEventItem {
  id: number
  subject: string
  kind: string
  severity: number
  description: string
  consequence: string
  introduced_turn: number
  status: string
}
