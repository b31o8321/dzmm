import { ref } from 'vue'
import {
  createModelProfile,
  deleteModelProfile,
  listModelProfiles,
  probeModelProfile,
  setDefaultModelProfile,
  updateModelProfile,
  type ModelProfile,
  type ModelProfileInput,
  type ModelProbeResult,
} from '../local_host_port'

export function modelProviderBaseUrl(provider: ModelProfileInput['provider_type']) {
  return {
    ollama: 'http://127.0.0.1:11434',
    lm_studio: 'http://127.0.0.1:1234/v1',
    openai_compat: '',
  }[provider]
}

const emptyDraft = (): ModelProfileInput => ({
  name: '本机模型',
  provider_type: 'ollama',
  base_url: modelProviderBaseUrl('ollama'),
  model_name: '',
  api_key: '',
})

export type ModelProfileField = 'name' | 'base_url' | 'model_name'
export type ModelProfileFieldErrors = Partial<Record<ModelProfileField, string>>

export function validateModelProfileDraft(draft: ModelProfileInput): ModelProfileFieldErrors {
  const errors: ModelProfileFieldErrors = {}
  if (!draft.name.trim()) errors.name = '请输入模型名称'
  if (!draft.base_url.trim()) errors.base_url = '请输入 Base URL'
  if (!draft.model_name.trim()) errors.model_name = '请输入模型名'
  return errors
}

export function useModelProfiles() {
  const profiles = ref<ModelProfile[]>([])
  const probeResults = ref<Record<string, ModelProbeResult>>({})
  const probingProfileId = ref<string | null>(null)
  const editorOpen = ref(false)
  const editingProfileId = ref<string | null>(null)
  const draft = ref<ModelProfileInput>(emptyDraft())
  const validationErrors = ref<ModelProfileFieldErrors>({})

  async function refresh() {
    profiles.value = await listModelProfiles()
    return profiles.value
  }

  function beginAdd() {
    editingProfileId.value = null
    draft.value = emptyDraft()
    validationErrors.value = {}
    editorOpen.value = true
  }

  function beginEdit(profile: ModelProfile) {
    editingProfileId.value = profile.id
    draft.value = {
      name: profile.name,
      provider_type: profile.provider_type,
      base_url: profile.base_url,
      model_name: profile.model_name,
      api_key: '',
    }
    validationErrors.value = {}
    editorOpen.value = true
  }

  function selectProvider(provider: ModelProfileInput['provider_type']) {
    draft.value.provider_type = provider
    draft.value.base_url = modelProviderBaseUrl(provider)
    validationErrors.value = {}
  }

  async function save() {
    validationErrors.value = validateModelProfileDraft(draft.value)
    if (Object.keys(validationErrors.value).length) return null
    const profile = editingProfileId.value
      ? await updateModelProfile(editingProfileId.value, draft.value)
      : await createModelProfile(draft.value)
    await refresh()
    editingProfileId.value = null
    editorOpen.value = false
    validationErrors.value = {}
    return profile
  }

  async function makeDefault(profile: ModelProfile) {
    await setDefaultModelProfile(profile.id)
    await refresh()
  }

  async function remove(profile: ModelProfile) {
    await deleteModelProfile(profile.id)
    await refresh()
    return profiles.value.find((item) => item.is_default) ?? profiles.value[0]
  }

  async function probe(profile: ModelProfile) {
    probingProfileId.value = profile.id
    try {
      const result = await probeModelProfile(profile.id)
      probeResults.value = { ...probeResults.value, [profile.id]: result }
      return result
    } finally {
      probingProfileId.value = null
    }
  }

  return {
    profiles,
    probeResults,
    probingProfileId,
    editorOpen,
    editingProfileId,
    draft,
    validationErrors,
    refresh,
    beginAdd,
    beginEdit,
    selectProvider,
    save,
    makeDefault,
    remove,
    probe,
  }
}
