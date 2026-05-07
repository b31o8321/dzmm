import { api } from './client'

export interface Faction {
  id: number
  name: string
  ideology: string
  description: string
  leader_npc_id: number | null
  pc_reputation: number
  hostile_to: string[]
  allied_to: string[]
}

export const factionsApi = {
  list: (sessionId: number) =>
    api.get<Faction[]>(`/sessions/${sessionId}/factions`).then((r) => r.data),
}
