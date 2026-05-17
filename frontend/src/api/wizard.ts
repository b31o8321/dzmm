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

  fwCharacter: (b: {
    model_config_id: number
    world_md: string
    archetype: string
  }) =>
    api
      .post<WizardCharacter>('/wizard/fw/character', b, { timeout: 600_000 })
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

}
