<script setup lang="ts">
import { watch, nextTick, ref, computed } from 'vue'
import { ElButton, ElMessage } from 'element-plus'
import SpeakerBubble, { type Part } from '@/components/SpeakerBubble.vue'
import MarkdownView from '@/components/MarkdownView.vue'
import DiceShowcase from '@/components/game/DiceShowcase.vue'
import type { Turn } from '@/composables/useGameTurn'
import { useDebugStore } from '@/stores/debug'
import { sessionsApi } from '@/api/sessions'
import { parseDiceEvent } from '@/utils/diceParse'

const props = defineProps<{
  turns: Turn[]
  characterName?: string
  sending?: boolean
  sessionId: number
}>()

const emit = defineEmits<{
  (e: 'choose', choice: string): void
  (e: 'open-events', turn: Turn): void
}>()

const logEl = ref<HTMLElement | null>(null)

const debug = useDebugStore()
const debugDialogOpen = ref(false)
interface DebugInfo { prompt: object[]; response: string; tokensIn: number; tokensOut: number }
const debugInfo = ref<DebugInfo | null>(null)

async function openDebug(turn: Turn) {
  if (!turn.msgId) return
  try {
    const d = await sessionsApi.messageDebug(props.sessionId, turn.msgId)
    debugInfo.value = {
      prompt: d.prompt_json ? JSON.parse(d.prompt_json) : [],
      response: d.content,
      tokensIn: d.tokens_in,
      tokensOut: d.tokens_out,
    }
    debugDialogOpen.value = true
  } catch (e: any) {
    ElMessage.error('加载调试数据失败: ' + (e?.message ?? ''))
  }
}

// Parse <narrative>, <say speaker="..">, <pc_action> tags from raw GM content
// into an ordered list of parts. Falls back to a single narration block when
// no tags are found, so legacy messages still render.
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

// Compose what the chat bubble actually renders. Two states must coexist:
//   - Streaming: t.narrative grows token-by-token via onNarrative; once GM
//     emits the first <say>/<pc_action> close, onTag populates t.rawContent
//     (which does NOT contain narrative). We must keep showing t.narrative
//     so the live text doesn't vanish mid-stream.
//   - Rehydrated history (onMounted) / post-onDone: rawContent holds the full
//     payload including <narrative>...</narrative>. parseParts handles it; we
//     skip its narration parts when t.narrative is already non-empty to avoid
//     double-rendering.
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

const recentPlotEvents = computed(() => {
  const events: string[] = []
  const slice = props.turns.slice(0, -1).slice(-5)  // last 5 prior turns
  for (const t of slice) {
    for (const e of t.events ?? []) {
      if (e.type === 'plot_event' && e.content) {
        events.push(e.content)
      }
    }
  }
  return events.slice(-3)  // most recent 3 plot events
})

const isLastTurnLoading = computed(() => {
  if (!props.sending) return false
  const last = props.turns[props.turns.length - 1]
  return !!last && !last.narrative
})

// Auto-scroll to bottom whenever a new turn appears.
watch(
  () => props.turns.length,
  async () => {
    await nextTick()
    if (logEl.value) logEl.value.scrollTop = logEl.value.scrollHeight
  },
)

defineExpose({ logEl })
</script>

<template>
  <div ref="logEl" class="flex-1 overflow-auto px-6 py-4 space-y-6">
    <div v-if="!turns.length" class="text-slate-400 italic">
      输入第一个行动开始跑团（例如：「(开始游戏)」让 GM 给你开局描写）
    </div>
    <article v-for="(t, i) in turns" :key="i" class="space-y-2">
      <div class="text-sm text-slate-500 font-medium">
        ▶ {{ t.action }}
        <button
          v-if="debug.enabled && t.msgId"
          class="text-xs text-slate-400 hover:text-slate-600 ml-1"
          title="查看LLM原始数据"
          @click="openDebug(t)"
        >
          🐛
        </button>
      </div>
      <div class="relative bg-white rounded shadow-sm p-4">
        <!-- Loading state: waiting for first LLM token -->
        <template v-if="i === turns.length - 1 && isLastTurnLoading">
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
        <template v-else-if="displayParts(t).length">
          <SpeakerBubble
            v-for="(part, pi) in displayParts(t)"
            :key="pi"
            :part="part"
            :pc-name="characterName"
          />
        </template>
        <MarkdownView v-else :source="t.narrative" />
        <!-- Inline dice showcase: one card per dice event, rendered sequentially -->
        <template v-if="t.events && t.events.some(ev => ev.type === 'dice')">
          <DiceShowcase
            v-for="(ev, ei) in t.events.filter(ev => ev.type === 'dice')"
            :key="'dice-' + ei"
            :dice="parseDiceEvent(ev)"
          />
        </template>
        <el-button
          v-if="t.events && t.events.filter(ev => ev.type !== 'dice').length > 0"
          size="small"
          link
          class="!absolute bottom-1 right-1 text-xs"
          @click="emit('open-events', t)"
        >
          ⚙️ {{ t.events.filter(ev => ev.type !== 'dice').length }}
        </el-button>
      </div>
      <div v-if="t.choices.length && i === turns.length - 1" class="space-y-1">
        <button
          v-for="(c, ci) in t.choices"
          :key="ci"
          type="button"
          class="block w-full text-left bg-blue-50 hover:bg-blue-100 border border-blue-200 rounded px-3 py-2 text-sm text-slate-700 transition"
          @click="emit('choose', c)"
        >
          ▶ {{ c }}
        </button>
      </div>
    </article>
  </div>

  <el-dialog
    v-model="debugDialogOpen"
    title="LLM 原始数据"
    width="80%"
  >
    <div v-if="debugInfo" class="space-y-4 text-xs font-mono">
      <div>
        <div class="font-bold text-slate-600 mb-1">
          发送给 LLM（{{ debugInfo.tokensIn }} tokens in）
        </div>
        <div class="bg-slate-50 border rounded p-2 max-h-64 overflow-auto whitespace-pre-wrap">
          <template v-if="debugInfo.prompt.length">
            <div
              v-for="(msg, i) in debugInfo.prompt"
              :key="i"
              class="mb-2 border-b border-slate-200 pb-2"
            >
              <span class="font-bold" :class="(msg as any).role === 'system' ? 'text-purple-600' : (msg as any).role === 'user' ? 'text-blue-600' : 'text-green-600'">
                [{{ (msg as any).role }}]
              </span>
              {{ (msg as any).content }}
            </div>
          </template>
          <span v-else class="text-slate-400">未记录（需开启 debug_mode 会话设置）</span>
        </div>
      </div>
      <div>
        <div class="font-bold text-slate-600 mb-1">
          LLM 返回（{{ debugInfo.tokensOut }} tokens out）
        </div>
        <div class="bg-slate-50 border rounded p-2 max-h-64 overflow-auto whitespace-pre-wrap">
          {{ debugInfo.response }}
        </div>
      </div>
    </div>
  </el-dialog>
</template>
