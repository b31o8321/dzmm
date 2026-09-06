// @vitest-environment jsdom

import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import ModelProfileEditor from './ModelProfileEditor.vue'

function mountEditor() {
  return mount(ModelProfileEditor, {
    props: {
      legend: '新建模型档案',
      submitLabel: '保存模型档案',
      namePrefix: 'profile',
      errors: { base_url: '请输入 Base URL' },
      busy: false,
      showCancel: true,
      name: '本机模型',
      providerType: 'ollama',
      baseUrl: '',
      modelName: 'qwen3',
      apiKey: '',
      hasSavedCredential: true,
    },
  })
}

describe('ModelProfileEditor', () => {
  it('keeps connection fields typed, named and announced', () => {
    const wrapper = mountEditor()
    const baseUrl = wrapper.get('input[name="profile-base-url"]')

    expect(baseUrl.attributes('type')).toBe('url')
    expect(baseUrl.attributes('inputmode')).toBe('url')
    expect(baseUrl.attributes('aria-invalid')).toBe('true')
    expect(wrapper.get('input[name="profile-api-key"]').attributes('type')).toBe('password')
    expect(wrapper.text()).toContain('系统安全存储')
    expect(wrapper.get('.field-error').attributes('role')).toBe('alert')
    expect(wrapper.get('select[name="profile-provider"]').element).toBeInstanceOf(HTMLSelectElement)
  })

  it('emits the shared save and cancel actions', async () => {
    const wrapper = mountEditor()
    const buttons = wrapper.findAll('button')

    await buttons[0].trigger('click')
    await buttons[1].trigger('click')
    expect(wrapper.emitted('save')).toHaveLength(1)
    expect(wrapper.emitted('cancel')).toHaveLength(1)
  })

  it('reports protocol changes so the complete connection profile can update together', async () => {
    const wrapper = mountEditor()

    await wrapper.get('select').setValue('lm_studio')
    expect(wrapper.emitted('providerChange')).toEqual([['lm_studio']])
  })
})
