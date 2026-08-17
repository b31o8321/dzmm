export type RunState = {
  revision: number
  hero: { id: string; name: string }
  ruleset: { id: string; enabled_capabilities: string[] }
  location_id: string
  inventory: Array<{ id: string; quantity: number }>
  chapter: { id: string; status: 'active' | 'completed'; resolved_choice_ids: string[] } | null
  route: { id: string; status: 'locked' } | null
  flags: Record<string, boolean>
  relationships: Record<string, {
    dimensions: Record<string, number>
    applied_events: Record<string, { reason_key: string }>
  }>
  ending: { id: string; kind: 'good' | 'normal' | 'bad' | 'hidden'; narrative_key: string } | null
}

export type ComposedRun = {
  world_id: string
  world_version_id: string
  hero_id: string
  run_id: string
  state: RunState
}

export type Turn = {
  id: string
  kind: 'turn' | 'rollback'
  rollback_target_id: string | null
  sequence: number
  player_input: string
  narrative: string
  before_revision: number
  after_revision: number
}

export type RunSnapshot = {
  run_id: string
  state: RunState
  turns: Turn[]
  available_choices: Array<{ id: string; label: string }>
}

export type WorldTemplate = {
  world_definition: Record<string, unknown>
  hero: { name: string; profile: Record<string, unknown> }
}

export type ImportedContent = {
  suggested_hero: { name: string; profile: Record<string, unknown> } | null
  lorebook: { entries: Array<Record<string, unknown>> }
  character_cards: Array<Record<string, unknown>>
  report: {
    source_format: string
    supported_fields: string[]
    preserved_fields: string[]
    ignored_fields: string[]
    warnings: string[]
  }
}

let apiBase = import.meta.env.VITE_API_BASE ?? '/api/v2'

export function setApiBase(base: string) {
  apiBase = base
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${apiBase}${path}`, init)
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as { detail?: string }
    throw new Error(body.detail ?? `请求失败（${response.status}）`)
  }
  return response.json() as Promise<T>
}

export function composeWorld(payload: object) {
  return request<ComposedRun>('/worlds:compose', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export function getRun(runId: string) {
  return request<RunSnapshot>(`/runs/${runId}`)
}

export function createTurn(runId: string, payload: object) {
  return request<{ state: RunState }>(`/runs/${runId}/turns`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export function chooseTurn(runId: string, payload: object) {
  return request<{ state: RunState }>(`/runs/${runId}/choices`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export function getFogHarborTemplate() {
  return request<WorldTemplate>('/world-templates/fog-harbor')
}

export function rollbackTurn(runId: string, payload: object) {
  return request<{ state: RunState }>(`/runs/${runId}/rollbacks`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export function importSillyTavern(content: object) {
  return request<ImportedContent>('/content/sillytavern:import', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ content }),
  })
}

export function importSillyTavernPng(pngBase64: string) {
  return request<ImportedContent>('/content/sillytavern:import', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ png_base64: pngBase64 }),
  })
}

export function exportLorebook(worldVersionId: string) {
  return request<Record<string, unknown>>(`/world-versions/${worldVersionId}/lorebook:export`)
}

export function exportCharacterCard(worldVersionId: string, characterCardId: string) {
  return request<Record<string, unknown>>(
    `/world-versions/${worldVersionId}/character-cards/${characterCardId}:export`,
  )
}
