<script setup lang="ts">
import { computed } from 'vue'
import type { RunSnapshot, Turn } from '../local_host_port'

const props = defineProps<{
  run: RunSnapshot
  busy: boolean
  hostReady: boolean
  streamingNarrative?: string
  harborName: string
  lighthouseName: string
}>()

const emit = defineEmits<{
  choose: [choice: { id: string; label: string }]
  rollback: [turn: Turn]
  send: []
  newRun: []
  returnWorld: []
}>()

const playerInput = defineModel<string>('playerInput', { required: true })
const destination = defineModel<string>('destination', { required: true })

const activeChapter = computed(() => props.run.state.chapter)
const activeChapterTitle = computed(() => {
  const chapter = activeChapter.value
  return chapter ? props.run.presentation.chapters[chapter.id] ?? '未命名章节' : ''
})
const locationLabel = computed(
  () => props.run.presentation.locations[props.run.state.location_id] ?? props.harborName,
)
const locationOptions = computed(() => {
  const entries = Object.entries(props.run.presentation.locations)
  return entries.length
    ? entries
    : [['harbor', props.harborName], ['lighthouse', props.lighthouseName]] as Array<[string, string]>
})
const relationshipEntries = computed(() => Object.entries(props.run.state.relationships))
const endingLabel = computed(() => {
  const ending = props.run.state.ending
  return ending
    ? { good: '好结局', normal: '普通结局', bad: '坏结局', hidden: '隐藏结局' }[ending.kind]
    : ''
})
const endingBeat = computed(() => props.run.story_beats.find((beat) => beat.kind === 'ending'))
const visibleStoryBeats = computed(() => props.run.story_beats.filter((beat) => !props.run.state.ending || beat.kind !== 'ending'))
const completedTurns = computed(() => props.run.turns.filter((turn) => turn.kind === 'turn'))
const recentActions = computed(() => completedTurns.value.slice(-3).map((turn) => turn.player_input))
const inventorySummary = computed(() => props.run.state.inventory.map((item) => `${resourceName(item.id)} ×${item.quantity}`).join('，'))
const relationshipSummary = computed(() => relationshipEntries.value.map(([characterId, relationship]) => {
  const dimensions = Object.entries(relationship.dimensions)
    .map(([dimension, value]) => `${relationshipDimensionName(dimension)} ${value}`)
    .join('、')
  return `${relationshipName(characterId)}：${dimensions}`
}))

function relationshipName(relationshipId: string) {
  return props.run.presentation.relationships[relationshipId] ?? '未知角色'
}

function routeName(routeId: string) {
  return props.run.presentation.routes[routeId] ?? '未命名路线'
}

function resourceName(resourceId: string) {
  return props.run.presentation.resources[resourceId] ?? '未知物品'
}

function relationshipDimensionName(dimension: string) {
  return { affection: '好感', trust: '信任' }[dimension] ?? '关系'
}

function rollbackLabel(targetId: string | null) {
  const target = props.run.turns.find((turn) => turn.id === targetId)
  return target ? `已恢复至回合 ${target.sequence} 后` : '已恢复至先前回合'
}
</script>

<template>
  <section class="scene play-scene">
    <aside class="run-state">
      <p class="eyebrow">{{ activeChapter ? '当前章节' : '当前坐标' }}</p>
      <h2 v-if="activeChapter">{{ activeChapterTitle }}</h2>
      <h2>{{ locationLabel }}</h2>
      <dl>
        <div><dt>角色</dt><dd>{{ run.state.hero.name }}</dd></div>
        <div v-if="run.state.route"><dt>路线</dt><dd>{{ routeName(run.state.route.id) }}</dd></div>
        <div><dt>物品</dt><dd>{{ inventorySummary || '无' }}</dd></div>
      </dl>
      <section v-if="relationshipEntries.length" class="relationship-ledger" aria-label="关系状态">
        <p class="eyebrow">关系账本</p>
        <article v-for="[characterId, relationship] in relationshipEntries" :key="characterId">
          <b>{{ relationshipName(characterId) }}</b>
          <span v-for="[dimension, value] in Object.entries(relationship.dimensions)" :key="dimension">{{ relationshipDimensionName(dimension) }} {{ value }}</span>
        </article>
      </section>
    </aside>
    <div class="chronicle" aria-live="polite">
      <section v-if="run.state.ending" class="ending-card" :class="run.state.ending.kind">
        <p class="eyebrow">旅程完成 · {{ endingLabel }}</p>
        <h2>{{ endingBeat?.title ?? '旅程完成' }}</h2>
        <p>{{ endingBeat?.narrative ?? '这段旅程已经抵达正式结局。' }}</p>
        <blockquote v-if="endingBeat?.dialogue"><b>{{ endingBeat.dialogue.speaker }}</b><span>{{ endingBeat.dialogue.text }}</span></blockquote>
        <p>共完成 {{ completedTurns.length }} 个回合，旅程已经正式结算。</p>
        <section class="journey-summary" aria-label="旅程回顾">
          <h3>这段旅程留下了</h3>
          <dl>
            <div v-if="run.state.route"><dt>最终路线</dt><dd>{{ routeName(run.state.route.id) }}</dd></div>
            <div v-if="inventorySummary"><dt>持有物品</dt><dd>{{ inventorySummary }}</dd></div>
            <div v-for="summary in relationshipSummary" :key="summary"><dt>人物关系</dt><dd>{{ summary }}</dd></div>
          </dl>
          <div v-if="recentActions.length" class="key-actions"><b>关键行动</b><ol><li v-for="action in recentActions" :key="action">{{ action }}</li></ol></div>
        </section>
        <div class="ending-actions"><button type="button" :disabled="busy" @click="emit('newRun')">从同一世界开始新旅程</button><button class="minor-action" type="button" :disabled="busy" @click="emit('returnWorld')">返回世界</button></div>
      </section>
      <article v-for="(beat, index) in visibleStoryBeats" :key="`${beat.kind}-${index}`" class="story-beat" :class="beat.kind">
        <small>{{ beat.location }}</small>
        <h2>{{ beat.title }}</h2>
        <p>{{ beat.narrative }}</p>
        <template v-if="beat.dialogues?.length">
          <blockquote v-for="dialogue in beat.dialogues" :key="`${dialogue.speaker}-${dialogue.text}`"><b>{{ dialogue.speaker }}</b><span>{{ dialogue.text }}</span></blockquote>
        </template>
        <blockquote v-else-if="beat.dialogue"><b>{{ beat.dialogue.speaker }}</b><span>{{ beat.dialogue.text }}</span></blockquote>
        <div class="story-guidance"><b>{{ beat.objective }}</b><span>{{ beat.guidance }}</span></div>
        <div v-if="beat.state_feedback?.length" class="state-feedback" aria-label="状态反馈"><span v-for="item in beat.state_feedback" :key="item">{{ item }}</span></div>
      </article>
      <article v-if="streamingNarrative" class="story-beat streaming-story-beat" aria-live="polite">
        <small>正在讲述</small>
        <h2>故事正在继续…</h2>
        <p>{{ streamingNarrative }}</p>
      </article>
      <p class="eyebrow">回合记录</p>
      <article v-for="turn in run.turns" :key="turn.id">
        <small>回合 {{ turn.sequence }}</small>
        <p class="player">{{ turn.player_input }}</p>
        <p v-if="!run.story_beats.some(beat => beat.sequence === turn.sequence)">{{ turn.narrative }}</p>
        <button v-if="turn.kind === 'turn'" class="rollback" :disabled="busy" @click="emit('rollback', turn)">恢复到此回合后</button>
        <p v-else class="rollback-note">{{ rollbackLabel(turn.rollback_target_id) }}</p>
      </article>
      <p v-if="!run.turns.length" class="empty">开场已经发生。选择下一步，或写下你的行动。</p>
    </div>
    <section v-if="run.available_choices.length" class="choice-deck" aria-label="当前可选行动">
      <p class="eyebrow">此刻可做的选择</p>
      <button v-for="choice in run.available_choices" :key="choice.id" type="button" :disabled="busy || !hostReady" @click="emit('choose', choice)">{{ choice.label }}</button>
    </section>
    <form v-else-if="!run.state.ending" class="turn-form" @submit.prevent="emit('send')">
      <label>行动<input v-model="playerInput" name="player-action" autocomplete="off" placeholder="我检查码头的灯火…" required maxlength="4000" /></label>
      <label v-if="locationOptions.length > 1">目的地<select v-model="destination" name="destination"><option v-for="[locationId, name] in locationOptions" :key="locationId" :value="locationId">{{ name }}</option></select></label>
      <button :disabled="busy || !hostReady || !playerInput.trim()">{{ busy ? '正在结算回合…' : '执行回合' }}</button>
    </form>
  </section>
</template>
