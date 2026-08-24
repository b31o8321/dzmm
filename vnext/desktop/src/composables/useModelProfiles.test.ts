import { describe, expect, it } from 'vitest'

import { modelProviderBaseUrl, useModelProfiles, validateModelProfileDraft } from './useModelProfiles'

describe('model profile validation', () => {
  it('returns field-level Chinese guidance before a host request', () => {
    expect(
      validateModelProfileDraft({
        name: ' ',
        provider_type: 'ollama',
        base_url: '',
        model_name: '',
        api_key: '',
      }),
    ).toEqual({
      name: '请输入模型名称',
      base_url: '请输入 Base URL',
      model_name: '请输入模型名',
    })
  })

  it('accepts a complete protocol profile', () => {
    expect(
      validateModelProfileDraft({
        name: '本机模型',
        provider_type: 'lm_studio',
        base_url: 'http://127.0.0.1:1234/v1',
        model_name: 'qwen3',
        api_key: '',
      }),
    ).toEqual({})
  })

  it('starts without a developer-specific model and applies provider URL presets as one profile', () => {
    const profiles = useModelProfiles()

    expect(profiles.draft.value).toEqual({
      name: '本机模型',
      provider_type: 'ollama',
      base_url: modelProviderBaseUrl('ollama'),
      model_name: '',
      api_key: '',
    })
    profiles.selectProvider('lm_studio')
    expect(profiles.draft.value.provider_type).toBe('lm_studio')
    expect(profiles.draft.value.base_url).toBe('http://127.0.0.1:1234/v1')
    profiles.selectProvider('openai_compat')
    expect(profiles.draft.value.base_url).toBe('')
  })
})
