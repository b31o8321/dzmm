// @vitest-environment jsdom

import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import type { WorldDetail } from '../local_host_port'
import WorldRunLauncher from './WorldRunLauncher.vue'

const world: WorldDetail = {
  id: 'world-1',
  name: '雾港',
  status: 'active',
  latest_world_version_id: 'world-version-2',
  latest_version_number: 2,
  world_version_count: 2,
  run_count: 2,
  lorebook_entry_count: 3,
  character_card_count: 2,
  latest_run_id: 'run-latest',
  definition: {},
  runs: [
    {
      id: 'run-latest',
      world_version_id: 'world-version-2',
      hero_id: 'hero-1',
      hero_name: '米拉',
      status: 'active',
      revision: 4,
      model_profile_id: null,
      created_at: '2026-08-21T00:00:00Z',
      updated_at: '2026-08-21T00:00:00Z',
    },
  ],
}

function mountLauncher() {
  return mount(WorldRunLauncher, {
    props: {
      world,
      modelProfiles: [
        {
          id: 'model-1',
          name: 'Qwen%2030B',
          provider_type: 'ollama',
          base_url: 'http://127.0.0.1:11434',
          model_name: 'qwen3:30b',
          is_default: true,
          has_api_key: false,
        },
      ],
      busy: false,
      open: false,
      heroName: '旅行者',
      modelProfileId: '',
    },
  })
}

function mountArchivedLauncher() {
  return mount(WorldRunLauncher, {
    props: {
      world: { ...world, status: 'archived' },
      modelProfiles: [],
      busy: false,
      open: false,
      heroName: '旅行者',
      modelProfileId: '',
    },
  })
}

describe('WorldRunLauncher', () => {
  it('makes continuing and starting independent Runs explicit', async () => {
    const wrapper = mountLauncher()

    expect(wrapper.text()).toContain('已有旅程保留创建时的世界内容')
    expect(wrapper.text()).toContain('旅程进行中')
    expect(wrapper.text()).not.toContain('状态版本')
    expect(wrapper.text()).not.toContain('run-latest')
    await wrapper.get('.world-primary-actions .minor-action').trigger('click')
    expect(wrapper.emitted('continue')).toEqual([['run-latest']])

    const startToggle = wrapper.findAll('.world-primary-actions button')[1]
    await startToggle.trigger('click')
    expect(wrapper.emitted('update:open')).toEqual([[true]])
  })

  it('collects hero and model before entering a new opening', async () => {
    const wrapper = mountLauncher()
    await wrapper.setProps({ open: true })

    expect(wrapper.text()).toContain('新的独立旅程')
    expect(wrapper.text()).toContain('不会覆盖已有旅程')
    expect(wrapper.text()).toContain('Qwen 30B · qwen3:30b')
    await wrapper.get('form').trigger('submit')
    expect(wrapper.emitted('start')).toHaveLength(1)
  })

  it('makes archived runs view-only instead of offering a failing continue action', () => {
    const wrapper = mountArchivedLauncher()

    expect(wrapper.text()).toContain('已归档')
    expect(wrapper.findAll('button').every((button) => (button.element as HTMLButtonElement).disabled)).toBe(true)
    expect(wrapper.findAll('button').some((button) => button.text() === '开始新旅程')).toBe(false)
  })
})
