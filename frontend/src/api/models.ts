import { api } from './client'
import type { ModelConfig, ModelConfigIn } from './types'

export const modelsApi = {
  list: () => api.get<ModelConfig[]>('/model_configs').then((r) => r.data),
  create: (body: ModelConfigIn) =>
    api.post<ModelConfig>('/model_configs', body).then((r) => r.data),
  test: (id: number) =>
    api.post<{ ok: boolean; info: string }>(`/model_configs/${id}/test`).then((r) => r.data),
}
