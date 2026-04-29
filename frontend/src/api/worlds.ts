import type { World, WorldIn } from './types'

export const worldsApi = {
  list: async (): Promise<World[]> => { throw new Error('not implemented') },
  get: async (_id: number): Promise<World> => { throw new Error('not implemented') },
  create: async (_body: WorldIn): Promise<World> => { throw new Error('not implemented') },
}
