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
  screenplay_id: number | null
  world_id: number
  character_id: number
  gm_model_config_id: number
  summarizer_model_config_id: number
  turn_count: number
}

export interface SessionIn {
  name: string
  screenplay_id?: number
  world_id?: number
  character_id?: number
  gm_model_config_id: number
  summarizer_model_config_id: number
}

export interface StandaloneScreenplay {
  id: number
  world_id: number
  session_id: number | null
  title: string
  genre: string
  pc_name: string
  pc_profile_md: string
  pc_base_stats_json: string
  custom_prompt: string
  outline_md: string
  chapters_json: string
  main_characters_json: string
  ending_md: string
  opening_hook: string
  version: number
  current_chapter: number
  completed_events_json: string
  status: 'active' | 'concluded' | 'superseded'
  created_at: string
}

export type StandaloneScreenplayIn = Omit<StandaloneScreenplay,
  'id' | 'world_id' | 'session_id' | 'version' | 'current_chapter' |
  'completed_events_json' | 'status' | 'created_at'>

export type TurnEvent =
  | { type: 'narrative'; text: string }
  | { type: 'tag'; name: string; attrs: Record<string, string>; content: string }
  | { type: 'parse_error'; message: string }
  | { type: 'summarize_error'; message: string }
  | { type: 'done' }

// ── Dice Event types ──────────────────────────────────────────

export type DiceCategory =
  | 'combat' | 'stealth' | 'persuasion' | 'arcane'
  | 'athletics' | 'perception' | 'knowledge' | 'generic'

export type DiceOutcome = 'crit_success' | 'success' | 'fail' | 'crit_fail'

export interface DiceReaction {
  speaker: string
  mood: string
  text: string
}

export interface DiceEvent {
  category: DiceCategory
  outcome: DiceOutcome
  dc: number
  pc_roll: number
  modifier: number
  scene_text: string
  reactions: DiceReaction[]
  description: string  // legacy fallback
}
