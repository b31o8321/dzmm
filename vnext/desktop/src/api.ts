export type RunState = {
  revision: number
  hero: { id: string; name: string }
  location_id: string
  inventory: Array<{ id: string; quantity: number }>
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
}

const apiBase = import.meta.env.VITE_API_BASE ?? '/api/v2'

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

export function rollbackTurn(runId: string, payload: object) {
  return request<{ state: RunState }>(`/runs/${runId}/rollbacks`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(payload),
  })
}
