import { api } from './client'
import type { Character, CharacterIn } from './types'

export const charactersApi = {
  list: (worldId?: number) =>
    api
      .get<Character[]>('/characters', { params: { world_id: worldId } })
      .then((r) => r.data),
  get: (id: number) => api.get<Character>(`/characters/${id}`).then((r) => r.data),
  create: (body: CharacterIn) =>
    api.post<Character>('/characters', body).then((r) => r.data),
}
