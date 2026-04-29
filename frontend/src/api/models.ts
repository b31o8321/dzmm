import type { ModelConfig, ModelConfigIn } from './types'

export const modelsApi = {
  list: async (): Promise<ModelConfig[]> => { throw new Error('not implemented') },
  create: async (_body: ModelConfigIn): Promise<ModelConfig> => { throw new Error('not implemented') },
  test: async (_id: number): Promise<{ ok: boolean; info: string }> => { throw new Error('not implemented') },
}
