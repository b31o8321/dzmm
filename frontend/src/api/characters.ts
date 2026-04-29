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
  update: (id: number, body: CharacterIn) =>
    api.put<Character>(`/characters/${id}`, body).then((r) => r.data),
  remove: (id: number) => api.delete(`/characters/${id}`).then(() => undefined),
  uploadPortrait: (id: number, file: File) => {
    const fd = new FormData()
    fd.append('file', file)
    return api
      .post<Character>(`/characters/${id}/portrait`, fd, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      .then((r) => r.data)
  },
  levelup: (id: number, stat: string) =>
    api
      .post<Character>(`/characters/${id}/levelup`, { stat })
      .then((r) => r.data),
}
