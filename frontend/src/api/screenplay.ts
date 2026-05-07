import { api } from './client'

// v0.9: events are objects {description, keywords, criteria}.
// v0.8 and earlier: events were plain strings. Renderers must handle both.
export interface ScreenplayEventObj {
  description: string
  keywords?: string[]
  criteria?: string
}
export type ScreenplayEvent = string | ScreenplayEventObj

export function eventDescription(ev: ScreenplayEvent): string {
  if (typeof ev === 'string') return ev
  if (ev && typeof ev === 'object' && 'description' in ev) {
    return String((ev as ScreenplayEventObj).description ?? '')
  }
  return ''
}

export function eventCriteria(ev: ScreenplayEvent): string {
  if (typeof ev === 'string') return ''
  if (ev && typeof ev === 'object' && 'criteria' in ev) {
    return String((ev as ScreenplayEventObj).criteria ?? '')
  }
  return ''
}

export function eventKeywords(ev: ScreenplayEvent): string[] {
  if (typeof ev === 'string') return []
  if (ev && typeof ev === 'object' && Array.isArray((ev as ScreenplayEventObj).keywords)) {
    return (ev as ScreenplayEventObj).keywords ?? []
  }
  return []
}

export interface ScreenplayChapter {
  title: string
  summary: string
  main_events: ScreenplayEvent[]
  optional_events: ScreenplayEvent[]
  main_npcs: string[]
}

export interface ScreenplayMainCharacter {
  name: string
  role: string
  description: string
  intro_chapter: number
}

export interface CompletedEvent {
  chapter: number
  event_idx: number
  type: 'main' | 'optional'
}

export interface Screenplay {
  id: number
  session_id: number
  version: number
  genre: string
  chapters: ScreenplayChapter[]
  main_characters: ScreenplayMainCharacter[]
  ending_md: string
  opening_hook: string
  current_chapter: number
  completed_events: CompletedEvent[]
  parent_screenplay_id: number | null
  status: 'active' | 'concluded' | 'superseded'
  created_at: string
  concluded_at: string | null
}

export const screenplayApi = {
  // Outliner generation is a long single-shot LLM call (typically 30-90s,
  // can be 5+ min on slower local models). Override axios's 30s default.
  generate: (id: number, body: { genre: string; custom_prompt?: string }) =>
    api
      .post<Screenplay>(`/sessions/${id}/screenplay/generate`, body, {
        timeout: 600_000,
      })
      .then((r) => r.data),
  getActive: (id: number) =>
    api.get<Screenplay>(`/sessions/${id}/screenplay`).then((r) => r.data),
  markDecision: (id: number, description: string) =>
    api
      .post(`/sessions/${id}/screenplay/mark_decision`, { description })
      .then((r) => r.data),
  continueNext: (id: number) =>
    api
      .post<Screenplay>(`/sessions/${id}/screenplay/continue`, {}, {
        timeout: 600_000,
      })
      .then((r) => r.data),
  revisions: (id: number) =>
    api
      .get<ScreenplayRevision[]>(`/sessions/${id}/screenplay/revisions`)
      .then((r) => r.data),
  processRevision: (id: number, revId: number) =>
    api
      .post<{ ok: boolean; revision_id: number; diff_summary: string }>(
        `/sessions/${id}/screenplay/revisions/${revId}/process`,
        {},
        { timeout: 600_000 },
      )
      .then((r) => r.data),
}

export interface ScreenplayRevision {
  id: number
  revision_num: number
  trigger_turn: number
  trigger_description: string
  diff_summary: string
  pending: boolean
  created_at: string | null
}

export const KNOWN_GENRES: { key: string; label: string; desc: string }[] = [
  { key: '悬疑探案', label: '🔍 悬疑探案', desc: '解谜 / 调查 / 真相揭露' },
  { key: '英雄成长', label: '⚔️ 英雄成长', desc: '从凡人到救世' },
  { key: '政治阴谋', label: '🎭 政治阴谋', desc: '势力斡旋 / 立场抉择' },
  { key: '灾难求生', label: '🌋 灾难求生', desc: '资源稀缺 / 生死逃亡' },
  { key: '恋爱攻略', label: '💕 恋爱攻略', desc: '关系养成 / 情感试炼' },
  { key: '自定义', label: '✏️ 自定义', desc: '你说想要什么样的故事' },
]
