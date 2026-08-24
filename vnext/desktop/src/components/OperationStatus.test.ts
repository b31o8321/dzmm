// @vitest-environment jsdom

import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import OperationStatus from './OperationStatus.vue'

describe('OperationStatus', () => {
  it('keeps model progress and cancellation visible to the player', async () => {
    const wrapper = mount(OperationStatus, {
      props: {
        operation: {
          stage: 'generating',
          label: '正在生成后续故事；成功前不会写入半个回合。',
          elapsedMs: 9200,
        },
        cancellable: true,
        cancelLabel: '取消本次起草',
      },
    })

    expect(wrapper.attributes('role')).toBe('status')
    expect(wrapper.text()).toContain('正在生成后续故事')
    expect(wrapper.text()).toContain('9.2 秒')
    expect(wrapper.text()).toContain('本地模型可能仍在加载或生成')
    expect(wrapper.text()).toContain('准备')
    expect(wrapper.text()).toContain('模型生成')
    expect(wrapper.text()).toContain('状态写入')
    expect(wrapper.text()).toContain('取消本次起草')

    await wrapper.get('button').trigger('click')
    expect(wrapper.emitted('cancel')).toHaveLength(1)
  })

  it('does not offer cancellation after state application starts', () => {
    const wrapper = mount(OperationStatus, {
      props: {
        operation: { stage: 'applying', label: '正在写入状态…', elapsedMs: 1200 },
        cancellable: false,
      },
    })

    expect(wrapper.find('button').exists()).toBe(false)
    expect(wrapper.get('li.active').text()).toBe('状态写入')
  })
})
