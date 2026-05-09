import { api } from './client'
import type { ModelConfig, ModelConfigIn } from './types'

export interface ModelCheckResult {
  narrative_ok: boolean
  embed_ok: boolean | null
  missing: string[]
}

export const modelsApi = {
  list: () => api.get<ModelConfig[]>('/model_configs').then((r) => r.data),
  create: (body: ModelConfigIn) =>
    api.post<ModelConfig>('/model_configs', body).then((r) => r.data),
  update: (id: number, body: ModelConfigIn) =>
    api.put<ModelConfig>(`/model_configs/${id}`, body).then((r) => r.data),
  remove: (id: number) => api.delete(`/model_configs/${id}`).then(() => undefined),
  test: (id: number) =>
    api.post<{ ok: boolean; info: string }>(`/model_configs/${id}/test`).then((r) => r.data),
  check: (id: number) =>
    api.get<ModelCheckResult>(`/model_configs/${id}/check`).then((r) => r.data),
  setDefault: (id: number) =>
    api.post<ModelConfig>(`/model_configs/${id}/default`).then((r) => r.data),
}
