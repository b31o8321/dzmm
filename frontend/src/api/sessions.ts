import type { GameSession, SessionIn } from './types'

export const sessionsApi = {
  list: async (): Promise<GameSession[]> => { throw new Error('not implemented') },
  get: async (_id: number): Promise<GameSession> => { throw new Error('not implemented') },
  create: async (_body: SessionIn): Promise<GameSession> => { throw new Error('not implemented') },
}
