<script setup lang="ts">
import { computed } from 'vue'
import SpeakerBubble, { type Part } from '@/components/SpeakerBubble.vue'
import MarkdownView from '@/components/MarkdownView.vue'
import DiceShowcase from '@/components/game/DiceShowcase.vue'
import type { Turn } from '@/composables/useGameTurn'
import { useDebugStore } from '@/stores/debug'
import { parseDiceEvent } from '@/utils/diceParse'

const props = defineProps<{
  turn: Turn
  turnIdx: number        // index in the full turns array
  totalTurns: number     // total length of turns array (to detect last turn)
  isLastTurnLoading: boolean
  recentPlotEvents: string[]
  characterName?: string
  sessionId: number
  debug?: boolean
}>()

const emit = defineEmits<{
  (e: 'choose', choice: string): void
  (e: 'open-events', turn: Turn): void
  (e: 'open-debug', turn: Turn): void
  (e: 'open-debug-chain', turn: Turn): void
}>()

const debugStore = useDebugStore()

const PARTS_TAG_RE =
  /<(narrative|narriative|say|pc_action)\b([^>]*)>([\s\S]*?)<\/(?:narrative|narriative|say|pc_action)>/gi
const SPEAKER_ATTR_RE = /speaker="([^"]*)"/i

function parseParts(content: string): Part[] {
  const parts: Part[] = []
  PARTS_TAG_RE.lastIndex = 0
  let m: RegExpExecArray | null
  while ((m = PARTS_TAG_RE.exec(content)) !== null) {
    const tag = m[1].toLowerCase()
    const attrs = m[2] ?? ''
    const text = (m[3] ?? '').trim()
    if (!text) continue
    if (tag === 'narrative' || tag === 'narriative') {
      parts.push({ type: 'narration', text })
    } else if (tag === 'say') {
      const sm = SPEAKER_ATTR_RE.exec(attrs)
      parts.push({ type: 'dialogue', speaker: sm?.[1], text })
    } else if (tag === 'pc_action') {
      parts.push({ type: 'pc_action', text })
    }
  }
  if (parts.length === 0) {
    const cleaned = content.trim()
    if (cleaned) parts.push({ type: 'narration', text: cleaned })
  }
  return parts
}

function displayParts(t: Turn): Part[] {
  const parts: Part[] = []
  const liveNarrative = t.narrative && t.narrative.trim()
  if (liveNarrative) {
    parts.push({ type: 'narration', text: t.narrative })
  }
  if (t.rawContent) {
    for (const p of parseParts(t.rawContent)) {
      if (liveNarrative && p.type === 'narration') continue
      parts.push(p)
    }
  }
  return parts
}

const isLast = computed(() => props.turnIdx === props.totalTurns - 1)
const parts = computed(() => displayParts(props.turn))
const diceEvents = computed(() => props.turn.events?.filter(ev => ev.type === 'dice') ?? [])
const nonDiceEvents = computed(() => props.turn.events?.filter(ev => ev.type !== 'dice') ?? [])
</script>

<template>
  <article class="space-y-2">
    <div class="text-sm text-slate-500 font-medium">
      ▶ {{ turn.action }}
      <button
        v-if="(debug || debugStore.enabled) && turn.msgId"
        class="text-xs text-slate-400 hover:text-slate-600 ml-1"
        title="查看LLM原始数据（单条）"
        @click="emit('open-debug', turn)"
      >
        🐛
      </button>
      <button
        v-if="(debug || debugStore.enabled) && turn.turn > 0"
        class="text-xs text-slate-400 hover:text-slate-600 ml-1"
        title="查看完整链路（Director+Scene+NPC）"
        @click="emit('open-debug-chain', turn)"
      >
        🔍
      </button>
    </div>
    <div class="relative bg-white rounded shadow-sm p-4">
      <el-alert
        v-if="turn.diagnostics?.length"
        type="warning"
        :closable="false"
        show-icon
        title="本回合部分结构化内容未应用"
        class="mb-3"
      >
        {{ turn.diagnostics.join('；') }}
      </el-alert>
      <!-- Loading state: waiting for first LLM token -->
      <template v-if="isLast && isLastTurnLoading">
        <div class="space-y-3">
          <div class="flex items-center gap-2 text-slate-500 text-sm animate-pulse">
            <span>⚔️ 行动中…</span>
          </div>
          <div v-if="recentPlotEvents.length" class="border-t pt-2 space-y-1">
            <div class="text-xs text-slate-400 mb-1">— 近期事件 —</div>
            <div
              v-for="(ev, ei) in recentPlotEvents"
              :key="ei"
              class="text-xs text-slate-500 leading-relaxed"
            >{{ ev }}</div>
          </div>
        </div>
      </template>
      <template v-else-if="parts.length">
        <SpeakerBubble
          v-for="(part, pi) in parts"
          :key="pi"
          :part="part"
          :pc-name="characterName"
        />
      </template>
      <MarkdownView v-else :source="turn.narrative" />

      <!-- Inline dice showcase -->
      <template v-if="diceEvents.length">
        <DiceShowcase
          v-for="(ev, ei) in diceEvents"
          :key="'dice-' + ei"
          :dice="parseDiceEvent(ev)"
        />
      </template>

      <el-button
        v-if="nonDiceEvents.length > 0"
        size="small"
        link
        class="!absolute bottom-1 right-1 text-xs"
        @click="emit('open-events', turn)"
      >
        ⚙️ {{ nonDiceEvents.length }}
      </el-button>
    </div>
    <div v-if="turn.choices.length && isLast" class="space-y-1">
      <button
        v-for="(c, ci) in turn.choices"
        :key="ci"
        type="button"
        class="block w-full text-left bg-blue-50 hover:bg-blue-100 border border-blue-200 rounded px-3 py-2 text-sm text-slate-700 transition"
        @click="emit('choose', c)"
      >
        ▶ {{ c }}
      </button>
    </div>
  </article>
</template>
