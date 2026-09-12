import { describe, expect, it } from 'vitest'

import { modelProviderBaseUrl, resolveBaseUrlOnProviderChange, useModelProfiles, validateModelProfileDraft } from './useModelProfiles'

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


describe('resolveBaseUrlOnProviderChange', () => {
  it('preserves a user-typed URL when switching provider', () => {
    const result = resolveBaseUrlOnProviderChange('ollama', 'http://192.168.31.169:1234/v1', 'lm_studio')
    expect(result).toEqual({ url: 'http://192.168.31.169:1234/v1', urlReset: false })
  })

  it('resets the URL when it was the previous provider default', () => {
    const result = resolveBaseUrlOnProviderChange('ollama', 'http://127.0.0.1:11434', 'lm_studio')
    expect(result).toEqual({ url: 'http://127.0.0.1:1234/v1', urlReset: true })
  })

  it('fills the default when the field was empty', () => {
    const result = resolveBaseUrlOnProviderChange('openai_compat', '  ', 'ollama')
    expect(result.url).toBe('http://127.0.0.1:11434')
    expect(result.urlReset).toBe(true)
  })
})
