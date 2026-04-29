import type { Character, CharacterIn } from './types'

export const charactersApi = {
  list: async (_worldId?: number): Promise<Character[]> => { throw new Error('not implemented') },
  get: async (_id: number): Promise<Character> => { throw new Error('not implemented') },
  create: async (_body: CharacterIn): Promise<Character> => { throw new Error('not implemented') },
}
