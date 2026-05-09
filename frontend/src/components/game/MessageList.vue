<script setup lang="ts">
import { watch, nextTick, ref, computed } from 'vue'
import { ElButton, ElMessage } from 'element-plus'
import CombatPanel from '@/components/game/CombatPanel.vue'
import TurnArticle from '@/components/game/TurnArticle.vue'
import type { Turn } from '@/composables/useGameTurn'
import { useDebugStore } from '@/stores/debug'
import { sessionsApi } from '@/api/sessions'

const props = defineProps<{
  turns: Turn[]
  characterName?: string
  sending?: boolean
  sessionId: number
  stats?: Record<string, number>
  debug?: boolean
}>()

const emit = defineEmits<{
  (e: 'choose', choice: string): void
  (e: 'open-events', turn: Turn): void
  (e: 'open-debug-chain', turn: Turn): void
}>()

const logEl = ref<HTMLElement | null>(null)

const debugStore = useDebugStore()
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

// ── Combat segment types ───────────────────────────────────

interface CombatBlock {
  kind: 'combat'
  startTurn: number
  endTurn: number | null
  enemies: Array<{ name: string; hp: number; max_hp?: number }>
  winner?: string
  turnIndices: number[]
}

interface NormalSeg {
  kind: 'turn'
  turnIdx: number
}

type Segment = CombatBlock | NormalSeg

function parseEnemies(content: string): Array<{ name: string; hp: number; max_hp?: number }> {
  try {
    const arr = JSON.parse((content || '').trim())
    if (Array.isArray(arr)) {
      return arr
        .map((e: any) => ({
          name: String(e.name ?? ''),
          hp: Number(e.hp ?? 0),
          max_hp: e.max_hp != null ? Number(e.max_hp) : Number(e.hp ?? 0),
        }))
        .filter((e) => e.name)
    }
  } catch { /* malformed or legacy — return empty */ }
  return []
}

const segments = computed<Segment[]>(() => {
  const out: Segment[] = []
  let combat: CombatBlock | null = null
  for (let i = 0; i < props.turns.length; i++) {
    const t = props.turns[i]
    let openedThisTurn = false
    for (const ev of t.events ?? []) {
      if (ev.type === 'combat_start' && combat == null) {
        combat = {
          kind: 'combat',
          startTurn: t.turn,
          endTurn: null,
          enemies: parseEnemies(String(ev.content ?? '')),
          turnIndices: [i],
        }
        out.push(combat)
        openedThisTurn = true
      }
      if (ev.type === 'combat_end' && combat != null) {
        combat.endTurn = t.turn
        combat.winner = ev.payload?.winner
        combat = null
      }
    }
    if (combat != null && !openedThisTurn) {
      // Still in combat — add this turn to the block
      combat.turnIndices.push(i)
    } else if (combat == null && !openedThisTurn) {
      // Normal (non-combat) turn
      out.push({ kind: 'turn', turnIdx: i })
    }
    // If openedThisTurn: turn is already registered inside the combat block
  }
  return out
})

const recentPlotEvents = computed(() => {
  const events: string[] = []
  const slice = props.turns.slice(0, -1).slice(-5)
  for (const t of slice) {
    for (const e of t.events ?? []) {
      if (e.type === 'plot_event' && e.content) {
        events.push(e.content)
      }
    }
  }
  return events.slice(-3)
})

const isLastTurnLoading = computed(() => {
  if (!props.sending) return false
  const last = props.turns[props.turns.length - 1]
  return !!last && !last.narrative
})

// PC HP from stats
const pcHp = computed(() => props.stats?.hp ?? props.stats?.HP ?? 0)
const pcMaxHp = computed(() => props.stats?.max_hp ?? props.stats?.maxHp ?? props.stats?.max_HP ?? 0)

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

    <template v-for="(seg, si) in segments" :key="si">
      <!-- Combat block: wrap covered turn cards in CombatPanel -->
      <CombatPanel
        v-if="seg.kind === 'combat'"
        :enemies="seg.enemies"
        :pc-hp="pcHp"
        :pc-max-hp="pcMaxHp"
        :ended="seg.endTurn != null"
        :winner="seg.winner"
        :turn-span="{ start: seg.startTurn, end: seg.endTurn }"
      >
        <TurnArticle
          v-for="ti in seg.turnIndices"
          :key="ti"
          :turn="turns[ti]"
          :turn-idx="ti"
          :total-turns="turns.length"
          :is-last-turn-loading="isLastTurnLoading"
          :recent-plot-events="recentPlotEvents"
          :character-name="characterName"
          :session-id="sessionId"
          :debug="debug"
          @choose="emit('choose', $event)"
          @open-events="emit('open-events', $event)"
          @open-debug="openDebug($event)"
          @open-debug-chain="emit('open-debug-chain', $event)"
        />
      </CombatPanel>

      <!-- Normal turn -->
      <TurnArticle
        v-else
        :turn="turns[seg.turnIdx]"
        :turn-idx="seg.turnIdx"
        :total-turns="turns.length"
        :is-last-turn-loading="isLastTurnLoading"
        :recent-plot-events="recentPlotEvents"
        :character-name="characterName"
        :session-id="sessionId"
        :debug="debug"
        @choose="emit('choose', $event)"
        @open-events="emit('open-events', $event)"
        @open-debug="openDebug($event)"
        @open-debug-chain="emit('open-debug-chain', $event)"
      />
    </template>
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
              <span
                class="font-bold"
                :class="
                  (msg as any).role === 'system'
                    ? 'text-purple-600'
                    : (msg as any).role === 'user'
                    ? 'text-blue-600'
                    : 'text-green-600'
                "
              >
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
