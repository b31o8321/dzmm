import { api } from './client'

export interface ScreenplayChapter {
  title: string
  summary: string
  main_events: string[]
  optional_events: string[]
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
    api.get(`/sessions/${id}/screenplay/revisions`).then((r) => r.data),
}

export const KNOWN_GENRES: { key: string; label: string; desc: string }[] = [
  { key: '悬疑探案', label: '🔍 悬疑探案', desc: '解谜 / 调查 / 真相揭露' },
  { key: '英雄成长', label: '⚔️ 英雄成长', desc: '从凡人到救世' },
  { key: '政治阴谋', label: '🎭 政治阴谋', desc: '势力斡旋 / 立场抉择' },
  { key: '灾难求生', label: '🌋 灾难求生', desc: '资源稀缺 / 生死逃亡' },
  { key: '恋爱攻略', label: '💕 恋爱攻略', desc: '关系养成 / 情感试炼' },
  { key: '自定义', label: '✏️ 自定义', desc: '你说想要什么样的故事' },
]
