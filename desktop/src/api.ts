import { consumeSseStream } from './sse'

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
  npc_state?: Record<string, {
    id: string
    name: string
    met: boolean
    location_id: string | null
    state: string
    favor: number
    emotion: Record<string, number>
  }>
  pending_interactions?: Array<{ id: string; kind: 'npc_initiative'; npc_id: string; npc_name: string; instruction: string }>
}

export type ComposedRun = {
  world_id: string
  world_version_id: string
  hero_id: string
  run_id: string
  state: RunState
  opening?: StoryBeat
}

export type StoryBeat = {
  id?: string
  sequence?: number
  kind: 'opening' | 'narrative' | 'ending'
  title: string
  location: string
  narrative: string
  dialogue: { speaker: string; text: string } | null
  dialogues?: Array<{ speaker: string; text: string }>
  objective: string
  guidance: string
  state_feedback?: string[]
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
  world_id: string
  status: 'active' | 'completed'
  state: RunState
  presentation: {
    world_name: string
    locations: Record<string, string>
    resources: Record<string, string>
    relationships: Record<string, string>
    chapters: Record<string, string>
    routes: Record<string, string>
  }
  turns: Turn[]
  story_beats: StoryBeat[]
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

export type WorldSummary = {
  id: string
  name: string
  status: 'active' | 'archived'
  latest_world_version_id: string
  latest_version_number: number
  world_version_count: number
  run_count: number
  lorebook_entry_count: number
  character_card_count: number
  latest_run_id: string | null
}

export type WorldDetail = WorldSummary & {
  definition: Record<string, unknown>
  runs: Array<{
    id: string
    world_version_id: string
    hero_id: string
    hero_name: string
    status: 'active' | 'completed'
    revision: number
    model_profile_id: string | null
    created_at: string
    updated_at: string
  }>
}

export type PurgeManifest = {
  world_id: string
  world_name: string
  tables: Record<string, number>
  file_paths: string[]
  derived_indexes: string[]
  confirmation_token: string
}

export type DiagnosticSnapshot = {
  app: string
  api_version: number
  contract: { version: string; contracts: string[] }
  storage: 'local'
  host: '127.0.0.1'
  database: {
    aggregate_counts: Record<string, number>
    integrity: { clean: boolean; orphans: Record<string, number> }
  }
}

export type ModelProfile = {
  id: string
  name: string
  provider_type: 'ollama' | 'lm_studio' | 'openai_compat'
  base_url: string
  model_name: string
  is_default: boolean
  has_api_key: boolean
}

export type ModelProfileInput = Omit<ModelProfile, 'id' | 'is_default' | 'has_api_key'> & {
  api_key: string
}

export type ModelProbeResult = {
  success: boolean
  endpoint: string
  detail: string
}

export type OperationCancellation = {
  request_id: string
  accepted: boolean
  detail: string
}

export type DraftIssue = { path: string; message: string }

export type AIWorldDraft = {
  valid: boolean
  summary: string | null
  world_definition: Record<string, unknown> | null
  hero: { name: string; profile: Record<string, unknown> } | null
  repairs: string[]
  issues: DraftIssue[]
}

export type TurnStreamEvent = {
  event: string
  data: Record<string, unknown>
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
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

async function streamSse(
  path: string,
  payload: object,
  onEvent: (event: TurnStreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetch(`${apiBase}${path}`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(payload),
    signal,
  })
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as { detail?: string }
    throw new Error(body.detail ?? `请求失败（${response.status}）`)
  }
  if (!response.body) throw new Error('本机模型没有返回可读取的叙事流')

  await consumeSseStream(response.body, onEvent)
}

export function streamTurn(
  runId: string,
  payload: object,
  onEvent: (event: TurnStreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  return streamSse(`/runs/${runId}/turns:stream`, payload, onEvent, signal)
}

export function streamChoice(
  runId: string,
  payload: object,
  onEvent: (event: TurnStreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  return streamSse(`/runs/${runId}/choices:stream`, payload, onEvent, signal)
}

export function composeWorld(payload: object) {
  return request<ComposedRun>('/worlds:compose', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export function createRun(worldId: string, payload: object) {
  return request<ComposedRun>(`/worlds/${worldId}/runs`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export function listModelProfiles() {
  return request<ModelProfile[]>('/model-profiles')
}

export function createModelProfile(payload: ModelProfileInput) {
  return request<ModelProfile>('/model-profiles', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export function updateModelProfile(profileId: string, payload: ModelProfileInput) {
  return request<ModelProfile>(`/model-profiles/${profileId}`, {
    method: 'PUT',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export function setDefaultModelProfile(profileId: string) {
  return request<ModelProfile>(`/model-profiles/${profileId}:default`, { method: 'POST' })
}

export function deleteModelProfile(profileId: string) {
  return request<void>(`/model-profiles/${profileId}`, { method: 'DELETE' })
}

export function probeModelProfile(profileId: string) {
  return request<ModelProbeResult>(`/model-profiles/${profileId}:probe`, { method: 'POST' })
}

export function generateAIWorldDraft(payload: object, signal?: AbortSignal) {
  return request<AIWorldDraft>('/ai-world-drafts:generate', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(payload),
    signal,
  })
}

export function validateAIWorldDraft(payload: object) {
  return request<AIWorldDraft>('/ai-world-drafts:validate', {
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

export function cancelOperation(requestId: string) {
  return request<OperationCancellation>(`/operations/${requestId}:cancel`, { method: 'POST' })
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

export function listWorlds() {
  return request<WorldSummary[]>('/worlds')
}

export function exportWorld(worldId: string) {
  return request<Record<string, unknown>>(`/worlds/${worldId}:export`)
}

export function importWorld(payload: { request_id: string; bundle: Record<string, unknown>; model_profile_id?: string }) {
  return request<ComposedRun>('/worlds:import', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export function exportRun(runId: string) {
  return request<Record<string, unknown>>(`/runs/${runId}:export`)
}

export function cloneRun(payload: { request_id: string; bundle: Record<string, unknown> }) {
  return request<ComposedRun>('/runs:clone', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export function getWorld(worldId: string) {
  return request<WorldDetail>(`/worlds/${worldId}`)
}

export function archiveWorld(worldId: string) {
  return request<{ world_id: string; status: 'archived' }>(`/worlds/${worldId}:archive`, {
    method: 'POST',
  })
}

export function restoreWorld(worldId: string) {
  return request<{ world_id: string; status: 'active' }>(`/worlds/${worldId}:restore`, {
    method: 'POST',
  })
}

export function deleteWorld(worldId: string, payload: { confirmation_token: string; world_name: string }) {
  return request<PurgeManifest>(`/worlds/${worldId}`, {
    method: 'DELETE',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export function getPurgeManifest(worldId: string) {
  return request<PurgeManifest>(`/worlds/${worldId}/purge-manifest`)
}

export function getDiagnostics() {
  return request<DiagnosticSnapshot>('/diagnostics')
}

export function purgeWorld(worldId: string, payload: { confirmation_token: string; world_name: string }) {
  return request<PurgeManifest>(`/worlds/${worldId}`, {
    method: 'DELETE',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export function createWorldVersion(
  worldId: string,
  payload: { base_world_version_id: string; definition: Record<string, unknown> },
) {
  return request<WorldDetail>(`/worlds/${worldId}/versions`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(payload),
  })
}
