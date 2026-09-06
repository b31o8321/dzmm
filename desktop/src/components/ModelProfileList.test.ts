// @vitest-environment jsdom

import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import type { ModelProfile } from '../local_host_port'
import ModelProfileList from './ModelProfileList.vue'

const profiles: ModelProfile[] = [
  {
    id: 'default-model',
    name: '默认模型',
    provider_type: 'ollama',
    base_url: 'http://127.0.0.1:11434',
    model_name: 'qwen3:8b',
    is_default: true,
    has_api_key: false,
  },
  {
    id: 'backup-model',
    name: '备用模型',
    provider_type: 'openai_compat',
    base_url: 'https://example.test/v1',
    model_name: 'story-model',
    is_default: false,
    has_api_key: true,
  },
]

describe('ModelProfileList', () => {
  it('keeps model actions and probe result presentation in a reusable boundary', async () => {
    const wrapper = mount(ModelProfileList, {
      props: {
        profiles,
        busy: false,
        probingProfileId: 'backup-model',
        probeResults: {
          'default-model': {
            success: true,
            endpoint: 'http://127.0.0.1:11434/api/chat',
            detail: 'protocol response contains content',
          },
        },
      },
    })

    expect(wrapper.text()).toContain('默认')
    expect(wrapper.text()).toContain('可用 · protocol response contains content')
    expect(wrapper.text()).toContain('测试中…')
    expect(wrapper.findAll('button').map((button) => button.text())).toEqual([
      '测试连接',
      '编辑',
      '删除',
      '测试中…',
      '编辑',
      '设为默认',
      '删除',
    ])

    await wrapper.findAll('button')[1].trigger('click')
    await wrapper.findAll('button')[5].trigger('click')
    await wrapper.findAll('button')[6].trigger('click')
    expect(wrapper.emitted('edit')?.[0]).toEqual([profiles[0]])
    expect(wrapper.emitted('makeDefault')?.[0]).toEqual([profiles[1]])
    expect(wrapper.emitted('remove')?.[0]).toEqual([profiles[1]])
  })
})
