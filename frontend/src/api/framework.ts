import { api } from './client'

// ── DB-backed types (match ORM fields) ──────────────────

export interface WorldLocationData {
  id: number
  framework_id: number
  name: string
  description_md: string
  location_type: 'city' | 'dungeon' | 'wilderness' | 'landmark'
  connections: Array<{
    target_id: number
    direction: string
    distance: number
    travel_turns: number
  }>
  initial_state: 'normal' | 'damaged' | 'destroyed'
  session_status?: 'normal' | 'damaged' | 'destroyed'
}

export interface WorldFactionData {
  id: number
  name: string
  description_md: string
  tension: number
  pc_reputation: number
}

export interface WorldNPCStateData {
  npc_template_id: number
  name: string
  gender: string
  role: string
  current_location_id: number | null
  favor: number
  is_companion: boolean
  is_revealed: boolean
  is_alive: boolean
}

export interface WorldEventStateData {
  event_id: number
  name: string
  summary_md: string
  importance: number
  scope_type: string
  scope_ref: string
  status: 'pending' | 'triggered' | 'completed'
  triggered_turn: number
}

export interface LocationDetail {
  location: WorldLocationData
  npcs_here: WorldNPCStateData[]
  triggered_events: WorldEventStateData[]
  controlling_faction: string | null
}

export interface CampaignPhaseProgress {
  phase_id: number
  name: string
  description: string
  status: 'locked' | 'active' | 'completed'
  triggered_count: number
  required_count: number
  triggered_key_events: Array<{ event_id: number; name: string }>
}

export interface CampaignProgress {
  campaign_name: string
  phases: CampaignPhaseProgress[]
}

// ── Wizard payload types ─────────────────────────────────

export interface FwLocationInput {
  name: string
  description_md: string
  location_type: string
  connections: Array<{
    target_name: string
    direction: string
    distance: number
    travel_turns: number
  }>
  initial_state: string
}

export interface FwFactionInput {
  name: string
  description_md: string
  rival_faction_names: string[]
  ally_faction_names: string[]
  tension_rules: { passive_gain_per_turn: number; threshold_conflict: number }
}

export interface FwNpcTemplateInput {
  name: string
  gender: 'male' | 'female' | ''
  role: string
  description_md: string
  motivation: string
  home_location_name: string
  faction_name: string | null
  contact_favor_threshold: number
  contact_cooldown_turns: number
}

export interface FwEventInput {
  name: string
  summary_md: string
  scope_type: 'location' | 'faction' | 'global'
  scope_location_name?: string
  scope_faction_name?: string
  importance: number
  trigger_conditions: unknown[]
  is_repeatable: boolean
  cooldown_turns: number
}

export interface FwCampaignPhaseInput {
  phase_id: number
  name: string
  description: string
  prerequisite_phase_ids: number[]
  key_event_names: string[]
  required_count: number
}

export interface FwCampaignInput {
  name: string
  phases: FwCampaignPhaseInput[]
}

export interface FwFinalizePayload {
  name: string
  genre: string
  style: string
  description_md: string
  locations: FwLocationInput[]
  factions: FwFactionInput[]
  npc_templates: FwNpcTemplateInput[]
  events: FwEventInput[]
  campaign: FwCampaignInput | null
}

// ── API calls ────────────────────────────────────────────

export const frameworkApi = {
  generateLocations: (b: { model_config_id: number; genre: string; world_brief_md: string }) =>
    api.post<FwLocationInput[]>('/wizard/fw/locations', b, { timeout: 600_000 }).then(r => r.data),

  generateFactions: (b: {
    model_config_id: number; genre: string; world_brief_md: string; locations: FwLocationInput[]
  }) =>
    api.post<FwFactionInput[]>('/wizard/fw/factions', b, { timeout: 600_000 }).then(r => r.data),

  generateNpcTemplates: (b: {
    model_config_id: number; genre: string; world_brief_md: string
    locations: FwLocationInput[]; factions: FwFactionInput[]
  }) =>
    api.post<FwNpcTemplateInput[]>('/wizard/fw/npc_templates', b, { timeout: 600_000 }).then(r => r.data),

  generateEvents: (b: {
    model_config_id: number; genre: string; world_brief_md: string
    locations: FwLocationInput[]; factions: FwFactionInput[]; npc_templates: FwNpcTemplateInput[]
  }) =>
    api.post<FwEventInput[]>('/wizard/fw/events', b, { timeout: 600_000 }).then(r => r.data),

  generateCampaign: (b: {
    model_config_id: number; genre: string; world_brief_md: string; events: FwEventInput[]
  }) =>
    api.post<FwCampaignInput>('/wizard/fw/campaign', b, { timeout: 600_000 }).then(r => r.data),

  finalize: (b: FwFinalizePayload) =>
    api.post<{ framework_id: number }>('/wizard/fw/finalize', b).then(r => r.data),

  getWorldState: (sessionId: number) =>
    api.get<{
      locations: WorldLocationData[]
      factions: WorldFactionData[]
      npcs: WorldNPCStateData[]
      events: WorldEventStateData[]
      pc_location_id: number | null
      campaign: CampaignProgress | null
    }>(`/sessions/${sessionId}/world_state`).then(r => r.data),
}
