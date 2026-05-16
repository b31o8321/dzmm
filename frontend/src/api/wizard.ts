import { api } from './client'

// ---- types ----

export interface WorldBrief {
  name: string
  setting: string
  conflict: string
  raw_md: string
}

export interface WizardNPC {
  name: string
  gender?: '' | 'male' | 'female'
  role: string
  description: string
  motivation: string
  avatarAssetId?: number | null
}

export interface WizardScreenplayChapter {
  title?: string
  summary?: string
  main_events?: string[]
  optional_events?: string[]
  main_npcs?: string[]
  [k: string]: any
}

export interface WizardScreenplayMainCharacter {
  name?: string
  role?: string
  description?: string
  intro_chapter?: number
  [k: string]: any
}

export interface WizardScreenplay {
  chapters: WizardScreenplayChapter[]
  main_characters: WizardScreenplayMainCharacter[]
  ending_md?: string
  ending?: string
  opening_hook: string
}

export interface SingleNpcResponse {
  name: string
  gender?: '' | 'male' | 'female'
  description: string
  archetype: string
  purpose: string
}

export interface WizardCharacter {
  name: string
  gender?: '' | 'male' | 'female'
  profile_md: string
}

export interface ThemeSuggestion {
  genre: string
  theme: string
  archetype: string
}

export interface ArchetypeSuggestion {
  description: string
  hook: string
}

export interface FinalizePayload {
  world: { name: string; content_md: string }
  character: { name: string; gender?: '' | 'male' | 'female'; profile_md: string }
  pinned_npcs: WizardNPC[]
  screenplay: WizardScreenplay
  session_name: string
  gm_model_config_id: number
  summarizer_model_config_id: number
  genre: string
}

// ---- api calls ----
//
// All wizard LLM calls are single-shot generations that can take 30-60s
// (and on slow local models 5+ minutes). Override axios's 30s default
// to 600_000ms = 10 min.

export const wizardApi = {
  worldBrief: (b: { model_config_id: number; genre: string; theme: string }) =>
    api
      .post<WorldBrief>('/wizard/world_brief', b, { timeout: 600_000 })
      .then((r) => r.data),

  worldDetails: (b: { model_config_id: number; brief_md: string }) =>
    api
      .post<{ world_md: string }>('/wizard/world_details', b, {
        timeout: 600_000,
      })
      .then((r) => r.data),

  /**
   * @deprecated Use `fwCharacter` instead. Kept for backwards compatibility.
   */
  character: (b: {
    model_config_id: number
    world_md: string
    archetype: string
  }) =>
    api
      .post<WizardCharacter>('/wizard/character', b, { timeout: 600_000 })
      .then((r) => r.data),

  fwCharacter: (b: {
    model_config_id: number
    world_md: string
    archetype: string
  }) =>
    api
      .post<WizardCharacter>('/wizard/fw/character', b, { timeout: 600_000 })
      .then((r) => r.data),

  npcs: (b: {
    model_config_id: number
    world_md: string
    character_md: string
  }) =>
    api
      .post<{ npcs: WizardNPC[] }>('/wizard/npcs', b, { timeout: 600_000 })
      .then((r) => r.data),

  generateSingleNpc: (b: {
    model_config_id: number
    world_md: string
    character_md: string
    hint: string
  }) =>
    api
      .post<SingleNpcResponse>('/wizard/npc/single', b, { timeout: 600_000 })
      .then((r) => r.data),

  screenplay: (b: {
    model_config_id: number
    world_md: string
    character_md: string
    npcs: WizardNPC[]
    genre: string
  }) =>
    api
      .post<WizardScreenplay>('/wizard/screenplay', b, { timeout: 600_000 })
      .then((r) => r.data),

  suggest: (b: { model_config_id: number; genre?: string }) =>
    api
      .post<{ suggestions: ThemeSuggestion[] }>('/wizard/suggest', b, { timeout: 120_000 })
      .then((r) => r.data),

  suggestArchetypes: (b: { model_config_id: number; world_md: string }) =>
    api
      .post<{ archetypes: ArchetypeSuggestion[] }>('/wizard/suggest_archetypes', b, { timeout: 120_000 })
      .then((r) => r.data),

  suggestNpcs: (b: { model_config_id: number; world_md: string; character_md: string }) =>
    api
      .post<{ npcs: WizardNPC[] }>('/wizard/suggest_npcs', b, { timeout: 120_000 })
      .then((r) => r.data),

  refineTheme: (b: { model_config_id: number; genre: string; rough: string }) =>
    api
      .post<{ theme: string }>('/wizard/refine_theme', b, { timeout: 60_000 })
      .then((r) => r.data),

  finalize: (b: FinalizePayload) =>
    api.post<{ session_id: number; world_id: number; npc_ids: Record<string, number> }>('/wizard/finalize', b).then((r) => r.data),
}
