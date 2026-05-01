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
  // v0.2.6: which location the NPC is currently in (null = unknown / not set)
  current_location?: string | null
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
  deleteAutoCreatedNpcs: (sid: number) =>
    api.delete(`/sessions/${sid}/npcs/auto_created`).then(() => undefined),
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

  locations: (id: number) =>
    api.get<LocationItem[]>(`/sessions/${id}/locations`).then((r) => r.data),

  async updateGmModel(sessionId: number, gmModelConfigId: number): Promise<void> {
    await api.patch(`/sessions/${sessionId}/gm_model`, {
      gm_model_config_id: gmModelConfigId,
    })
  },

  async suggestActions(
    sessionId: number,
    narrative: string,
    goals: string[] = [],
  ): Promise<string[]> {
    try {
      const r = await api.post<{ suggestions: string[] }>(
        `/sessions/${sessionId}/suggest_actions`,
        { narrative, goals },
      )
      return r.data.suggestions ?? []
    } catch {
      return []
    }
  },

  async npcTick(
    sessionId: number,
    npcName: string,
    handlers: {
      onNarrative?: (text: string) => void
      onTag?: (name: string, attrs: Record<string, string>, content: string) => void
      onDone?: () => void
    },
    signal?: AbortSignal,
  ): Promise<void> {
    const { backendOrigin } = await import('@/api/client')
    const resp = await fetch(`${backendOrigin}/sessions/${sessionId}/npc_tick`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
      body: JSON.stringify({ npc_name: npcName }),
      signal,
    })
    if (!resp.ok || !resp.body) return
    const reader = resp.body.getReader()
    const decoder = new TextDecoder('utf-8')
    let buf = ''
    while (true) {
      const { value, done } = await reader.read()
      if (done) break
      buf += decoder.decode(value, { stream: true }).replace(/\r\n/g, '\n')
      let nl: number
      while ((nl = buf.indexOf('\n\n')) >= 0) {
        const block = buf.slice(0, nl)
        buf = buf.slice(nl + 2)
        _dispatchBlock(block, handlers)
      }
    }
    if (buf.trim()) _dispatchBlock(buf, handlers)
  },
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

export interface LocationItem {
  id: number
  name: string
  description: string
  first_visited_turn: number
  last_visited_turn: number
  is_current: boolean
  // v0.2.6: items present in this location
  items: { name: string; description: string }[]
}

function _dispatchBlock(
  block: string,
  h: { onNarrative?: (t: string) => void; onTag?: (n: string, a: Record<string, string>, c: string) => void; onDone?: () => void },
) {
  let event = 'message'
  let data = ''
  for (const line of block.split('\n')) {
    if (line.startsWith('event: ')) event = line.slice(7).trim()
    else if (line.startsWith('data: ')) data += line.slice(6)
  }
  if (!data) return
  let parsed: any
  try { parsed = JSON.parse(data) } catch { return }
  if (event === 'narrative') h.onNarrative?.(parsed.text ?? '')
  else if (event === 'tag') h.onTag?.(parsed.name, parsed.attrs ?? {}, parsed.content ?? '')
  else if (event === 'done') h.onDone?.()
}
