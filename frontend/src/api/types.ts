export interface World {
  id: number
  name: string
  content_md: string
  style: string
  rules_mode: string
}

export type WorldIn = Omit<World, 'id'>

export interface Character {
  id: number
  world_id: number
  name: string
  profile_md: string
  base_stats_json: string
  portrait_path?: string
  xp?: number
  level?: number
}

export type CharacterIn = Omit<Character, 'id' | 'portrait_path' | 'xp' | 'level'>

export interface ModelConfig {
  id: number
  name: string
  type: 'openai_compat' | 'ollama'
  base_url: string
  model_name: string
  api_key_ref: string | null
  timeout: number
}

export interface ModelConfigIn {
  name: string
  type: 'openai_compat' | 'ollama'
  base_url: string
  model_name: string
  api_key?: string
  timeout?: number
}

export interface GameSession {
  id: number
  name: string
  world_id: number
  character_id: number
  gm_model_config_id: number
  summarizer_model_config_id: number
  turn_count: number
}

export type SessionIn = Omit<GameSession, 'id' | 'turn_count'>

export type TurnEvent =
  | { type: 'narrative'; text: string }
  | { type: 'tag'; name: string; attrs: Record<string, string>; content: string }
  | { type: 'parse_error'; message: string }
  | { type: 'summarize_error'; message: string }
  | { type: 'done' }
