<script setup lang="ts">
import { ref, reactive, computed, nextTick, onMounted, onUnmounted, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { streamTurn } from '@/composables/useTurnStream'
import { useSessionsStore } from '@/stores/sessions'
import { useWorldsStore } from '@/stores/worlds'
import { sessionsApi, type MessageRow, type MessageEvent, type Npc, type PCGoalItem } from '@/api/sessions'
import { charactersApi } from '@/api/characters'
import type { Character } from '@/api/types'
import { useAudio } from '@/composables/useAudio'
import StatePanel from '@/components/StatePanel.vue'
import MarkdownView from '@/components/MarkdownView.vue'
import CharacterAvatar from '@/components/CharacterAvatar.vue'
import LevelUpDialog from '@/components/LevelUpDialog.vue'
import NpcDetailDialog from '@/components/NpcDetailDialog.vue'
import CharacterCardDrawer from '@/components/CharacterCardDrawer.vue'
import SpeakerBubble, { type Part } from '@/components/SpeakerBubble.vue'
import MessageEventsDialog from '@/components/MessageEventsDialog.vue'
import FeedbackDialog from '@/components/FeedbackDialog.vue'
import { screenplayApi, type Screenplay } from '@/api/screenplay'

const props = defineProps<{ id: string }>()
const sessionId = Number(props.id)
const sessionsStore = useSessionsStore()
const worldsStore = useWorldsStore()
const audio = useAudio()
const version = __APP_VERSION__

interface Turn {
  action: string
  narrative: string
  choices: string[]
  events: MessageEvent[]
  turn: number
  rawContent?: string
}
const turns = ref<Turn[]>([])
const currentTurn = ref<Turn | null>(null)
const action = ref('')
const sending = ref(false)
const composing = ref(false)
const eventsDialogOpen = ref(false)
const eventsDialogEvents = ref<MessageEvent[]>([])
const eventsDialogTurn = ref(0)
const turnCount = ref(0)
const tokensIn = ref(0)
const tokensOut = ref(0)
const panelOpen = ref(false)
const character = ref<Character | null>(null)
const levelUpDialogOpen = ref(false)
const levelUpAutoShown = ref(false)

const xpThreshold = computed(() => {
  const lv = character.value?.level ?? 1
  return (100 * lv * (lv + 1)) / 2
})
const xpPct = computed(() => {
  const xp = character.value?.xp ?? 0
  if (!xpThreshold.value) return 0
  return Math.min(100, (xp / xpThreshold.value) * 100)
})
const canLevelUp = computed(
  () => !!character.value && (character.value.xp ?? 0) >= xpThreshold.value,
)

async function refreshCharacter() {
  if (!character.value) return
  try {
    character.value = await charactersApi.get(character.value.id)
  } catch {
    /* ignore */
  }
}

// Auto-pop the level-up dialog the first time we cross the threshold.
watch(canLevelUp, (v) => {
  if (v && !levelUpAutoShown.value && !levelUpDialogOpen.value) {
    levelUpAutoShown.value = true
    levelUpDialogOpen.value = true
  }
  if (!v) {
    // Re-arm so a future threshold crossing pops the dialog again.
    levelUpAutoShown.value = false
  }
})

function onLeveled(updated: Character) {
  character.value = updated
}

async function refreshTokens() {
  try {
    const msgs = await sessionsApi.messages(sessionId)
    let ti = 0, to = 0
    for (const m of msgs) {
      if (m.role === 'assistant') {
        ti += m.tokens_in
        to += m.tokens_out
      }
    }
    tokensIn.value = ti
    tokensOut.value = to
  } catch { /* ignore */ }
}

const stats = reactive<Record<string, number>>({})
const inventory = ref<string[]>([])
const npcs = ref<{ name: string; favor: number; state: string; pinned?: boolean }[]>([])
const dice = ref<{ skill: string; target: string; result: string }[]>([])
const threads = ref<{ type: string; description: string; importance: number }[]>([])
const pcMood = ref<Record<string, number>>({})

const goals = ref<PCGoalItem[]>([])

async function refreshGoals() {
  try {
    goals.value = await sessionsApi.goals(sessionId)
  } catch { /* ignore */ }
}

async function updateGoal(goalId: number, status: 'active' | 'completed' | 'abandoned') {
  try {
    await sessionsApi.updateGoalStatus(sessionId, goalId, status)
    await refreshGoals()
  } catch (e: any) {
    ElMessage.error(e.message ?? '更新失败')
  }
}

const npcDialogOpen = ref(false)
const selectedNpc = ref<Npc | null>(null)
const characterCardOpen = ref(false)
const feedbackOpen = ref(false)
const screenplay = ref<Screenplay | null>(null)

async function openNpcDetail(name: string) {
  try {
    const all = await sessionsApi.npcs(sessionId)
    const found = all.find((n) => n.name === name) ?? null
    selectedNpc.value = found
    npcDialogOpen.value = !!found
    if (!found) ElMessage.warning(`未找到 NPC：${name}`)
  } catch (e: any) {
    ElMessage.error(e.message ?? '加载失败')
  }
}

function onNpcUpdated(updated: Npc) {
  // Reflect pin state into the side-panel list immediately.
  const existing = npcs.value.find((n) => n.name === updated.name)
  if (existing) existing.pinned = updated.pinned
  selectedNpc.value = updated
}

const MAX_DICE = 8

const logEl = ref<HTMLElement | null>(null)
async function scrollToBottom() {
  await nextTick()
  if (logEl.value) logEl.value.scrollTop = logEl.value.scrollHeight
}

function applyStateChange(content: string) {
  try {
    const obj = JSON.parse(content)
    for (const [k, v] of Object.entries(obj)) {
      if (k === 'inventory_add' && Array.isArray(v)) {
        inventory.value.push(...(v as string[]))
      } else if (k === 'inventory_remove' && Array.isArray(v)) {
        for (const item of v as string[]) {
          const idx = inventory.value.indexOf(item)
          if (idx >= 0) inventory.value.splice(idx, 1)
        }
      } else if (typeof v === 'number') {
        stats[k] = (stats[k] ?? 0) + v
      }
    }
  } catch {
    /* ignore malformed */
  }
}

function applyNpcUpdate(content: string) {
  try {
    const obj = JSON.parse(content)
    if (!obj.name) return
    const existing = npcs.value.find((n) => n.name === obj.name)
    if (existing) {
      if (typeof obj.favor_delta === 'number') existing.favor += obj.favor_delta
      if (obj.state) existing.state = obj.state
    } else {
      npcs.value.push({
        name: obj.name,
        favor: obj.favor_delta ?? 0,
        state: obj.state ?? '未知',
      })
    }
  } catch {
    /* ignore */
  }
}

function applyPcMood(content: string) {
  try {
    const obj = JSON.parse(content)
    if (!obj || typeof obj !== 'object') return
    const next = { ...pcMood.value }
    for (const [k, v] of Object.entries(obj)) {
      if (typeof v !== 'number') continue
      const cur = next[k] ?? 0
      next[k] = Math.max(0, Math.min(100, cur + v))
    }
    pcMood.value = next
  } catch {
    /* ignore */
  }
}

async function send() {
  const userAction = action.value.trim()
  if (!userAction || sending.value) return
  action.value = ''
  await sendAction(userAction)
}

function onKey(e: KeyboardEvent) {
  if (e.key !== 'Enter') return
  // While the user is composing a CJK candidate, never intercept Enter.
  if (composing.value) return
  // Any modifier => keep default newline behaviour.
  if (e.shiftKey || e.ctrlKey || e.metaKey || e.altKey) return
  e.preventDefault()
  send()
}

function openEvents(t: Turn) {
  eventsDialogEvents.value = t.events ?? []
  eventsDialogTurn.value = t.turn
  eventsDialogOpen.value = true
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
    // Backwards-compat: messages predating the new tags fall through here, as
    // do any messages where every tag is empty. Render the whole thing as a
    // narration so nothing is lost.
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

async function sendAction(userAction: string) {
  sending.value = true

  const turn: Turn = {
    action: userAction,
    narrative: '',
    choices: [],
    events: [],
    turn: turnCount.value + 1,
  }
  currentTurn.value = turn
  // Clear previous turn's choices — they're stale once the user sends.
  for (const t of turns.value) t.choices = []
  turns.value.push(turn)
  await scrollToBottom()

  try {
    await streamTurn(sessionId, userAction, {
      onNarrative: (text) => {
        turn.narrative += text
        scrollToBottom()
      },
      onTag: (name, attrs, content) => {
        // Build a running rawContent so parseParts() can reconstruct speaker
        // bubbles after the turn finishes (and on the live frame for non-
        // streaming say/pc_action tags).
        if (name === 'say') {
          const speakerAttr = attrs.speaker ? ` speaker="${attrs.speaker}"` : ''
          turn.rawContent =
            (turn.rawContent ?? '') + `<say${speakerAttr}>${content}</say>`
        } else if (name === 'pc_action') {
          turn.rawContent = (turn.rawContent ?? '') + `<pc_action>${content}</pc_action>`
        }
        // Record any structured tag (besides `narrative`/`say`/`pc_action`/`choices`)
        // as an event so it shows up in the per-message events dialog.
        const skipForEvents = new Set(['narrative', 'narriative', 'say', 'pc_action', 'choices'])
        if (!skipForEvents.has(name)) {
          let payload: Record<string, any> = { ...attrs }
          const trimmed = content.trim()
          if (trimmed) {
            try {
              const parsed = JSON.parse(trimmed)
              if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
                payload = { ...payload, ...parsed }
              } else {
                payload = { ...payload, value: parsed }
              }
            } catch {
              payload = { ...payload, content: trimmed }
            }
          }
          turn.events.push({ type: name, payload, content: trimmed || undefined })
        }
        if (name === 'state_change') {
          try {
            const obj = JSON.parse(content)
            let totalDelta = 0
            for (const [, v] of Object.entries(obj)) {
              if (typeof v === 'number') totalDelta += v
            }
            if (totalDelta < 0) audio.playSfx('state_down')
            else if (totalDelta > 0) audio.playSfx('state_up')
          } catch { /* ignore */ }
          applyStateChange(content)
        }
        else if (name === 'npc_update') applyNpcUpdate(content)
        else if (name === 'pc_mood') applyPcMood(content)
        else if (name === 'choices') {
          const opts: string[] = []
          for (const line of content.split('\n')) {
            const trimmed = line.trim().replace(/^[-*•・·]\s*/, '')
            if (trimmed) opts.push(trimmed)
          }
          turn.choices = opts
        }
        else if (name === 'dice') {
          audio.playSfx('dice')
          dice.value.unshift({
            skill: attrs.skill ?? '判定',
            target: attrs.target ?? '?',
            result: content.trim() || '?',
          })
          if (dice.value.length > MAX_DICE) dice.value.length = MAX_DICE
        }
        else if (name === 'plot_event') {
          let importance = 2
          const parsed = parseInt(attrs.importance ?? '2', 10)
          if (!isNaN(parsed)) importance = Math.max(1, Math.min(3, parsed))
          threads.value.push({
            type: attrs.type ?? 'major_event',
            description: content.trim(),
            importance,
          })
        }
      },
      onError: (msg) => {
        ElMessage.warning(msg)
      },
      onDone: () => {
        turnCount.value += 1
        // GM may have forgotten </narrative> and embedded choices into the
        // streamed narrative buffer; recover them here.
        if (!turn.choices.length) {
          const leaked = extractChoices(turn.narrative)
          if (leaked.length) turn.choices = leaked
        }
        turn.narrative = cleanNarrative(turn.narrative)
        // Synthesize a rawContent that parseParts can chew on. We always
        // prepend the cleaned narrative (wrapped) so backwards-compat is
        // preserved when GM didn't emit any speaker tags at all.
        if (turn.narrative) {
          turn.rawContent =
            `<narrative>${turn.narrative}</narrative>` + (turn.rawContent ?? '')
        }
        refreshTokens()  // fire-and-forget
        refreshCharacter()  // pick up XP gains from <character_xp>
        refreshGoals()  // pick up <pc_goal> add/complete
      },
    })
  } catch (e: any) {
    ElMessage.error(e.message ?? '请求失败')
    turn.narrative += `\n\n[出错：${e.message ?? '未知错误'}]`
  } finally {
    sending.value = false
    currentTurn.value = null
  }
}

async function regenerate() {
  if (!turns.value.length || sending.value) return
  const last = turns.value[turns.value.length - 1]
  const oldAction = last.action
  try {
    await sessionsApi.deleteLastTurn(sessionId)
  } catch (e: any) {
    ElMessage.error(e.message ?? '删除失败')
    return
  }
  turns.value.pop()
  turnCount.value = Math.max(0, turnCount.value - 1)
  await refreshTokens()
  await sendAction(oldAction)
}

async function editPrev() {
  if (!turns.value.length || sending.value) return
  const last = turns.value[turns.value.length - 1]
  const oldAction = last.action
  try {
    await sessionsApi.deleteLastTurn(sessionId)
  } catch (e: any) {
    ElMessage.error(e.message ?? '删除失败')
    return
  }
  turns.value.pop()
  turnCount.value = Math.max(0, turnCount.value - 1)
  action.value = oldAction
  await refreshTokens()
}

const quickActions = ['环顾四周', '探索', '搭话', '潜行', '战斗', '使用物品']

function quick(act: string) {
  action.value = act
}

// Extract narrative text from a stored assistant message (which contains
// raw <narrative>...</narrative> tags interleaved with state tags).
//
// Robustness note: weak models sometimes forget to close <narrative> before
// emitting the next tag (e.g. <choices>). We defensively strip any embedded
// child tags from the narrative content so options/state/dice blocks don't
// leak into the chat log.
const NARRATIVE_RE = /<narrative\b[^>]*>([\s\S]*?)(?:<\/narrative>|(?=<(?:choices|state_change|npc_update|plot_event|dice)\b))/g
const CHOICES_RE = /<choices\b[^>]*>([\s\S]*?)<\/choices>/g
const DICE_RE = /<dice\s+([^>]*)>([\s\S]*?)<\/dice>/g
const ATTR_RE = /(\w+)="([^"]*)"/g
const ANY_KNOWN_CHILD_RE = /<(?:choices|state_change|npc_update|plot_event|dice)\b[^>]*>[\s\S]*?(?:<\/(?:choices|state_change|npc_update|plot_event|dice)>|$)/g

function cleanNarrative(raw: string): string {
  return raw
    .replace(ANY_KNOWN_CHILD_RE, '')   // any embedded child tag block
    .replace(/<think\b[^>]*>[\s\S]*?<\/think>/gi, '')
    .replace(/<\/?\w+\b[^>]*>/g, '')   // any stray tag fragment
    .trim()
}

function extractNarrative(content: string): string {
  const parts: string[] = []
  let m: RegExpExecArray | null
  NARRATIVE_RE.lastIndex = 0
  while ((m = NARRATIVE_RE.exec(content))) parts.push(cleanNarrative(m[1]))
  if (!parts.length) {
    // Plain-text fallback (deepseek-r1-style). Strip <think> + any leftover tags.
    return cleanNarrative(content)
  }
  return parts.filter((p) => p).join('\n\n')
}

function extractChoices(content: string): string[] {
  const out: string[] = []
  let m: RegExpExecArray | null
  CHOICES_RE.lastIndex = 0
  while ((m = CHOICES_RE.exec(content))) {
    for (const line of m[1].split('\n')) {
      const trimmed = line.trim().replace(/^[-*•・·]\s*/, '')
      if (trimmed) out.push(trimmed)
    }
  }
  return out
}

function extractDiceFromHistory(messages: MessageRow[]) {
  const out: { skill: string; target: string; result: string }[] = []
  for (const m of messages) {
    if (m.role !== 'assistant') continue
    DICE_RE.lastIndex = 0
    let dm: RegExpExecArray | null
    while ((dm = DICE_RE.exec(m.content))) {
      const attrsStr = dm[1]
      const inner = dm[2]
      const attrs: Record<string, string> = {}
      ATTR_RE.lastIndex = 0
      let am: RegExpExecArray | null
      while ((am = ATTR_RE.exec(attrsStr))) attrs[am[1]] = am[2]
      out.push({
        skill: attrs.skill ?? '判定',
        target: attrs.target ?? '?',
        result: inner.trim() || '?',
      })
    }
  }
  return out.slice(-MAX_DICE).reverse()
}

onMounted(async () => {
  // Fire-and-forget GM model warmup so the first turn isn't cold.
  sessionsApi.warmup(sessionId).catch(() => { /* ignore */ })

  // Pull screenplay state (legacy sessions without one are fine).
  try {
    screenplay.value = await screenplayApi.getActive(sessionId)
  } catch {
    screenplay.value = null
  }

  try {
    const sess = await sessionsStore.get(sessionId)
    turnCount.value = sess.turn_count
    try {
      character.value = await charactersApi.get(sess.character_id)
    } catch {
      /* ignore */
    }
  } catch {
    /* ignore */
  }

  // Start BGM matching the world style
  try {
    const sess = await sessionsStore.get(sessionId)
    await worldsStore.refresh()
    const world = worldsStore.items.find((w) => w.id === sess.world_id)
    if (world) audio.playBgm(world.style)
  } catch { /* ignore */ }

  // Rehydrate conversation log
  try {
    const msgs = await sessionsApi.messages(sessionId)
    const reconstructed: Turn[] = []
    let pendingUser: string | null = null
    for (const m of msgs) {
      if (m.role === 'user') {
        pendingUser = m.content
      } else if (m.role === 'assistant' && pendingUser !== null) {
        reconstructed.push({
          action: pendingUser,
          narrative: extractNarrative(m.content),
          choices: extractChoices(m.content),
          events: m.events ?? [],
          turn: m.turn,
          rawContent: m.content,
        })
        pendingUser = null
      }
    }
    // Only the latest turn's choices are still actionable; older choices
    // are stale once the player moved on.
    for (let i = 0; i < reconstructed.length - 1; i++) {
      reconstructed[i].choices = []
    }
    turns.value = reconstructed

    // Dice rolls don't have a dedicated table; rebuild from assistant content.
    dice.value = extractDiceFromHistory(msgs)
  } catch {
    /* ignore */
  }

  await refreshTokens()

  // Rehydrate right-side state from authoritative DB tables.
  try {
    const st = await sessionsApi.state(sessionId)
    Object.keys(stats).forEach((k) => delete stats[k])
    Object.assign(stats, st.stats)
    inventory.value = st.inventory
    npcs.value = st.npcs.map((n) => ({ ...n }))
    threads.value = st.threads
    pcMood.value = st.pc_mood ? { ...st.pc_mood } : {}

    // Augment with pinned flag from /npcs endpoint (state endpoint doesn't include it).
    try {
      const fullNpcs = await sessionsApi.npcs(sessionId)
      const pinSet = new Set(fullNpcs.filter((n) => n.pinned).map((n) => n.name))
      for (const n of npcs.value) n.pinned = pinSet.has(n.name)
    } catch { /* ignore */ }
  } catch {
    /* ignore */
  }

  await refreshGoals()

  await scrollToBottom()
})

onUnmounted(() => audio.stopBgm())
</script>

<template>
  <div class="flex h-full">
    <section class="flex-1 flex flex-col bg-slate-50">
      <header class="px-6 py-3 border-b bg-white flex items-center justify-between">
        <div class="flex items-center gap-3 flex-wrap">
          <CharacterAvatar
            :character-id="character?.id"
            :has-portrait="!!character?.portrait_path"
            :fallback-name="character?.name"
            :size="36"
          />
          <span class="font-bold">{{ character?.name ?? '跑团进行中' }}</span>
          <span class="text-xs text-slate-500">{{ turnCount }} 回合</span>
          <span class="text-xs text-slate-500 font-mono">
            tokens: {{ tokensIn.toLocaleString() }} in / {{ tokensOut.toLocaleString() }} out
          </span>
          <div v-if="character" class="flex items-center gap-2">
            <span class="text-xs text-slate-500">
              Lv {{ character.level ?? 1 }}
              ({{ character.xp ?? 0 }} / {{ xpThreshold }} XP)
            </span>
            <div class="w-32 h-1.5 bg-slate-200 rounded overflow-hidden">
              <div class="h-full bg-amber-400 transition-all"
                   :style="{ width: xpPct + '%' }"></div>
            </div>
            <el-button v-if="canLevelUp" size="small" type="warning"
                       @click="levelUpDialogOpen = true">
              ⭐ 升级
            </el-button>
          </div>
        </div>
        <div class="flex items-center gap-4">
          <button
            type="button"
            class="text-sm text-slate-500 hover:text-slate-800"
            @click="characterCardOpen = true"
          >📜 角色卡</button>
          <router-link :to="`/play/${sessionId}/screenplay`"
                       class="text-sm text-slate-500 hover:text-slate-800">
            📜 剧本
          </router-link>
          <router-link :to="`/play/${sessionId}/journal`"
                       class="text-sm text-slate-500 hover:text-slate-800">
            📖 任务日志
          </router-link>
          <router-link :to="`/play/${sessionId}/npcs`"
                       class="text-sm text-slate-500 hover:text-slate-800">
            📒 NPC
          </router-link>
          <router-link :to="`/play/${sessionId}/relations`"
                       class="text-sm text-slate-500 hover:text-slate-800">
            🔗 关系
          </router-link>
          <router-link :to="`/play/${sessionId}/chronicle`"
                       class="text-sm text-slate-500 hover:text-slate-800">
            📜 编年史
          </router-link>
          <button
            type="button"
            class="text-sm text-slate-500 hover:text-slate-800"
            @click="feedbackOpen = true"
          >💬 反馈</button>
          <router-link to="/sessions" class="text-sm text-slate-500 hover:text-slate-800">
            返回存档
          </router-link>
          <span class="text-xs text-slate-400 ml-2">v{{ version }}</span>
        </div>
      </header>

      <FeedbackDialog
        v-model="feedbackOpen"
        :session-id="sessionId"
      />

      <div v-if="screenplay && screenplay.status === 'concluded'"
           class="bg-blue-50 border-b border-blue-200 px-6 py-3 flex items-center justify-between">
        <div class="text-sm text-blue-900">🎬 故事已完结：{{ screenplay.ending_md }}</div>
        <el-button size="small" type="primary"
                   @click="$router.push(`/play/${sessionId}/screenplay`)">
          📖 续写下一章
        </el-button>
      </div>

      <div ref="logEl" class="flex-1 overflow-auto px-6 py-4 space-y-6">
        <div v-if="!turns.length" class="text-slate-400 italic">
          输入第一个行动开始跑团（例如：「(开始游戏)」让 GM 给你开局描写）
        </div>
        <article v-for="(t, i) in turns" :key="i" class="space-y-2">
          <div class="text-sm text-slate-500 font-medium">▶ {{ t.action }}</div>
          <div class="relative bg-white rounded shadow-sm p-4">
            <template v-if="displayParts(t).length">
              <SpeakerBubble
                v-for="(part, pi) in displayParts(t)"
                :key="pi"
                :part="part"
                :pc-name="character?.name"
              />
            </template>
            <MarkdownView v-else :source="t.narrative" />
            <el-button
              v-if="t.events && t.events.length > 0"
              size="small"
              link
              class="!absolute bottom-1 right-1 text-xs"
              @click="openEvents(t)"
            >
              🎲 {{ t.events.length }}
            </el-button>
          </div>
          <div v-if="t.choices.length" class="flex flex-col gap-2 ml-4">
            <button
              v-for="(c, ci) in t.choices"
              :key="ci"
              type="button"
              class="text-left bg-amber-50 hover:bg-amber-100 active:bg-amber-200 border border-amber-200 rounded px-3 py-2 text-sm text-slate-800 transition disabled:opacity-50 disabled:cursor-not-allowed"
              :disabled="sending"
              @click="quick(c)"
            >
              <span class="font-mono text-amber-600 mr-2">{{ ci + 1 }}.</span>{{ c }}
            </button>
          </div>
          <div v-if="i === turns.length - 1 && !sending"
               class="flex gap-3 text-xs text-slate-500 pt-1">
            <button type="button" class="hover:text-slate-800 underline"
                    @click="regenerate">🔄 重新生成</button>
            <button type="button" class="hover:text-slate-800 underline"
                    @click="editPrev">✏️ 编辑上一动作</button>
          </div>
        </article>
      </div>

      <footer class="border-t bg-white p-4 space-y-2">
        <div class="flex flex-wrap gap-2">
          <el-button
            v-for="a in quickActions"
            :key="a"
            size="small"
            @click="quick(a)"
            :disabled="sending"
          >{{ a }}</el-button>
        </div>
        <div class="flex gap-2">
          <el-input
            v-model="action"
            type="textarea"
            :autosize="{ minRows: 2, maxRows: 6 }"
            placeholder="输入你的行动…（Enter 发送，Shift+Enter 换行）"
            :disabled="sending"
            @keydown="onKey"
            @compositionstart="composing = true"
            @compositionend="composing = false"
          />
          <el-button type="primary" :loading="sending" @click="send">发送</el-button>
        </div>
      </footer>
    </section>

    <!-- Desktop: side panel always visible -->
    <div class="hidden md:flex">
      <StatePanel :stats="stats" :inventory="inventory" :npcs="npcs"
                  :dice="dice" :threads="threads" :goals="goals"
                  :pc-mood="pcMood"
                  @select-npc="openNpcDetail"
                  @goal-status="updateGoal" />
    </div>

    <!-- Mobile: floating toggle button, drawer slides in from right -->
    <button
      v-if="!panelOpen"
      type="button"
      class="md:hidden fixed top-2 right-2 z-20 bg-white border border-slate-300 rounded-full w-10 h-10 shadow flex items-center justify-center text-lg"
      title="打开状态面板"
      @click="panelOpen = true"
    >📋</button>

    <div
      v-if="panelOpen"
      class="md:hidden fixed inset-0 z-30 bg-black/40"
      @click="panelOpen = false"
    ></div>

    <div
      class="md:hidden fixed top-0 right-0 h-full z-40 transition-transform duration-200 bg-white shadow-xl"
      :class="panelOpen ? 'translate-x-0' : 'translate-x-full'"
    >
      <button
        type="button"
        class="absolute top-2 left-2 text-slate-400 hover:text-slate-700 text-2xl leading-none z-50"
        @click="panelOpen = false"
      >×</button>
      <StatePanel :stats="stats" :inventory="inventory" :npcs="npcs"
                  :dice="dice" :threads="threads" :goals="goals"
                  :pc-mood="pcMood"
                  @select-npc="openNpcDetail"
                  @goal-status="updateGoal" />
    </div>

    <LevelUpDialog
      v-model="levelUpDialogOpen"
      :character="character"
      @leveled="onLeveled"
    />

    <NpcDetailDialog
      v-model="npcDialogOpen"
      :session-id="sessionId"
      :npc="selectedNpc"
      @updated="onNpcUpdated"
    />

    <CharacterCardDrawer
      v-model="characterCardOpen"
      :character="character"
      :stats="stats"
      :inventory="inventory"
    />

    <MessageEventsDialog
      v-model="eventsDialogOpen"
      :events="eventsDialogEvents"
      :turn="eventsDialogTurn"
    />
  </div>
</template>
