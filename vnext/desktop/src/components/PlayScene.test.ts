// @vitest-environment jsdom

import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import type { RunSnapshot } from '../local_host_port'
import PlayScene from './PlayScene.vue'

function runSnapshot(): RunSnapshot {
  return {
    run_id: 'run-1',
    world_id: 'world-1',
    status: 'active',
    state: {
      revision: 1,
      hero: { id: 'hero-1', name: '米拉' },
      ruleset: { id: 'hybrid', enabled_capabilities: ['choices'] },
      location_id: 'harbor',
      inventory: [],
      chapter: { id: 'arrival', status: 'active', resolved_choice_ids: [] },
      route: null,
      flags: {},
      relationships: {},
      ending: null,
    },
    presentation: {
      world_name: '雾港',
      locations: { harbor: '雾港码头', lighthouse: '旧灯塔' },
      resources: { 'fog-lantern': '雾灯' },
      relationships: {},
      chapters: { arrival: '潮雾抵港' },
      routes: {},
    },
    turns: [],
    story_beats: [
      {
        kind: 'opening',
        title: '潮雾抵港',
        location: '雾港码头',
        narrative: '米拉抵达雾港码头，潮雾中的灯火忽明忽暗。',
        dialogue: { speaker: '岚', text: '别让这里替你作出第一个决定。' },
        objective: '确认眼前的局势。',
        guidance: '你可以先救下岚，或调查异常灯号。',
        state_feedback: ['位置：雾港码头'],
      },
    ],
    available_choices: [{ id: 'save-lan', label: '救下岚' }],
  }
}

function mountScene(run = runSnapshot()) {
  return mount(PlayScene, {
    props: {
      run,
      busy: false,
      hostReady: true,
      harborName: '雾港码头',
      lighthouseName: '旧灯塔',
      playerInput: '',
      destination: 'lighthouse',
    },
  })
}

describe('PlayScene', () => {
  it('presents opening narrative, dialogue, guidance, state and choices as one scene', async () => {
    const wrapper = mountScene()

    expect(wrapper.text()).toContain('潮雾抵港')
    expect(wrapper.text()).toContain('米拉抵达雾港码头')
    expect(wrapper.text()).toContain('岚')
    expect(wrapper.text()).toContain('别让这里替你作出第一个决定')
    expect(wrapper.text()).toContain('确认眼前的局势')
    expect(wrapper.text()).toContain('位置：雾港码头')

    await wrapper.get('.choice-deck button').trigger('click')
    expect(wrapper.emitted('choose')).toEqual([[{ id: 'save-lan', label: '救下岚' }]])
  })

  it('shows player-visible narrative while a free action is streaming', () => {
    const wrapper = mount(PlayScene, {
      props: {
        run: runSnapshot(),
        busy: true,
        hostReady: true,
        streamingNarrative: '潮水在脚边退去，远处传来一声钟响。',
        harborName: '雾港码头',
        lighthouseName: '旧灯塔',
        playerInput: '',
        destination: 'lighthouse',
      },
    })

    expect(wrapper.find('.streaming-story-beat').text()).toContain('潮水在脚边退去')
  })

  it('builds the free-action destination list from the current world presentation', () => {
    const run = runSnapshot()
    run.state.location_id = 'salt-cove'
    run.presentation.locations = {
      'salt-cove': '盐湾',
      'glass-tower': '玻璃塔',
    }
    run.available_choices = []
    const wrapper = mountScene(run)

    expect(wrapper.findAll('option').map((option) => option.text())).toEqual(['盐湾', '玻璃塔'])
  })

  it('does not add a destination control when the world has one location', () => {
    const run = runSnapshot()
    run.presentation.locations = { harbor: '唯一地点' }
    run.available_choices = []
    const wrapper = mountScene(run)

    expect(wrapper.find('select').exists()).toBe(false)
  })

  it('shows formal ending actions and no further choice controls', async () => {
    const run = runSnapshot()
    run.status = 'completed'
    run.state.ending = { id: 'safe-harbor', kind: 'good', narrative_key: 'ending.safe' }
    run.state.route = { id: 'lan-route', status: 'locked' }
    run.state.inventory = [{ id: 'fog-lantern', quantity: 1 }]
    run.state.relationships = {
      lan: { dimensions: { affection: 45, trust: 40 }, applied_events: {} },
    }
    run.presentation.routes = { 'lan-route': '岚路线' }
    run.presentation.relationships = { lan: '岚' }
    run.turns = [{
      id: 'turn-1',
      kind: 'turn',
      rollback_target_id: null,
      sequence: 1,
      player_input: '点亮雾灯',
      narrative: '潮门在晨光中开启。',
      before_revision: 0,
      after_revision: 1,
    }, {
      id: 'rollback-1',
      kind: 'rollback',
      rollback_target_id: 'turn-1',
      sequence: 2,
      player_input: '恢复历史',
      narrative: '状态已恢复。',
      before_revision: 1,
      after_revision: 2,
    }]
    run.story_beats.push({
      kind: 'ending',
      title: '潮门归于沉静',
      location: '旧灯塔',
      narrative: '晨光穿过雾港。',
      dialogue: null,
      objective: '旅程完成。',
      guidance: '可以回到世界，或开始新的 Run。',
    })
    run.available_choices = []
    const wrapper = mountScene(run)

    expect(wrapper.text()).toContain('旅程完成 · 好结局')
    expect(wrapper.text()).toContain('潮门归于沉静')
    expect(wrapper.text()).toContain('晨光穿过雾港。')
    expect(wrapper.text()).toContain('这段旅程留下了')
    expect(wrapper.text()).toContain('岚路线')
    expect(wrapper.text()).toContain('雾灯 ×1')
    expect(wrapper.text()).toContain('岚：好感 45、信任 40')
    expect(wrapper.text()).toContain('点亮雾灯')
    expect(wrapper.text()).toContain('已恢复至回合 1 后')
    expect(wrapper.text()).not.toContain('turn-1')
    expect(wrapper.find('.choice-deck').exists()).toBe(false)
    expect(wrapper.find('.turn-form').exists()).toBe(false)

    const actions = wrapper.findAll('.ending-actions button')
    await actions[0].trigger('click')
    await actions[1].trigger('click')
    expect(wrapper.emitted('newRun')).toHaveLength(1)
    expect(wrapper.emitted('returnWorld')).toHaveLength(1)
  })

  it('does not leak an internal ending key when the narrative beat is unavailable', () => {
    const run = runSnapshot()
    run.status = 'completed'
    run.state.ending = { id: 'safe-harbor', kind: 'good', narrative_key: 'ending.safe' }
    run.story_beats = []
    run.available_choices = []
    const wrapper = mountScene(run)

    expect(wrapper.text()).toContain('旅程完成 · 好结局')
    expect(wrapper.text()).toContain('这段旅程已经抵达正式结局。')
    expect(wrapper.text()).not.toContain('ending.safe')
  })

  it('keeps internal state identifiers out of the player chronicle', () => {
    const run = runSnapshot()
    run.state.inventory = [{ id: 'fog-lantern', quantity: 1 }]
    run.state.relationships = {
      lan: {
        dimensions: { trust: 2 },
        applied_events: { rescue: { reason_key: 'relationship.lan.rescued' } },
      },
    }
    run.presentation.relationships = { lan: '岚' }
    run.turns = [{
      id: 'turn-1',
      kind: 'turn',
      rollback_target_id: null,
      sequence: 1,
      player_input: '我点亮雾灯。',
      narrative: '灯芯在潮雾中亮起。',
      before_revision: 0,
      after_revision: 1,
    }]
    const wrapper = mountScene(run)

    expect(wrapper.text()).toContain('雾灯 ×1')
    expect(wrapper.text()).toContain('回合 1')
    expect(wrapper.text()).not.toContain('fog-lantern')
    expect(wrapper.text()).not.toContain('ARRIVAL')
    expect(wrapper.text()).not.toContain('状态版本')
    expect(wrapper.text()).not.toContain('状态 0 → 1')
    expect(wrapper.text()).not.toContain('relationship.lan.rescued')
  })
})
