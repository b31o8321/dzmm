<script setup lang="ts">
import { ref, computed, reactive, onMounted, onUnmounted, watch, nextTick } from 'vue'
import { ElMessage } from 'element-plus'
import { useSessionsStore } from '@/stores/sessions'
import { useWorldsStore } from '@/stores/worlds'
import { useModelConfigsStore } from '@/stores/modelConfigs'
import { sessionsApi, type MessageRow, type Npc, type LocationItem } from '@/api/sessions'
import { charactersApi } from '@/api/characters'
import type { Character } from '@/api/types'
import { useAudio } from '@/composables/useAudio'
import { useGameState, MAX_DICE } from '@/composables/useGameState'
import {
  useGameTurn,
  cleanNarrative,
  extractChoices,
  type Turn,
} from '@/composables/useGameTurn'
import StatePanel from '@/components/StatePanel.vue'
import CharacterAvatar from '@/components/CharacterAvatar.vue'
import LevelUpDialog from '@/components/LevelUpDialog.vue'
import NpcDetailDialog from '@/components/NpcDetailDialog.vue'
import CharacterCardDrawer from '@/components/CharacterCardDrawer.vue'
import MessageEventsDialog from '@/components/MessageEventsDialog.vue'
import FeedbackDialog from '@/components/FeedbackDialog.vue'
import MessageList from '@/components/game/MessageList.vue'
import { screenplayApi, type Screenplay } from '@/api/screenplay'

const props = defineProps<{ id: string }>()
const sessionId = Number(props.id)
const sessionsStore = useSessionsStore()
const worldsStore = useWorldsStore()
const modelsStore = useModelConfigsStore()
const audio = useAudio()
const version = __APP_VERSION__

const FONT_SIZE_KEY = 'dzmm_game_font_size'
const FONT_FAMILY_KEY = 'dzmm_game_font_family'
const FONT_FAMILIES = [
  { label: '默认', value: 'system-ui, sans-serif' },
  { label: '衬线', value: 'Georgia, serif' },
  { label: '等宽', value: "'Courier New', monospace" },
]
const fontSize = ref(parseInt(localStorage.getItem(FONT_SIZE_KEY) ?? '15'))
const fontFamilyIdx = ref(parseInt(localStorage.getItem(FONT_FAMILY_KEY) ?? '0'))
const fontFamily = computed(() => FONT_FAMILIES[fontFamilyIdx.value]?.value ?? FONT_FAMILIES[0].value)
function changeFontSize(delta: number) {
  fontSize.value = Math.min(24, Math.max(12, fontSize.value + delta))
  localStorage.setItem(FONT_SIZE_KEY, String(fontSize.value))
}
function cycleFontFamily() {
  fontFamilyIdx.value = (fontFamilyIdx.value + 1) % FONT_FAMILIES.length
  localStorage.setItem(FONT_FAMILY_KEY, String(fontFamilyIdx.value))
}

const action = ref('')
const composing = ref(false)
const eventsDialogOpen = ref(false)
const eventsDialogEvents = ref<Turn['events']>([])
const eventsDialogTurn = ref(0)
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

const gs = useGameState()
const {
  stats,
  inventory,
  npcs,
  dice,
  threads,
  pcMood,
  goals,
} = gs
const refreshGoals = () => gs.refreshGoals(sessionId)
const updateGoal = (goalId: number, status: 'active' | 'completed' | 'abandoned') =>
  gs.updateGoal(sessionId, goalId, status)

// Streaming + per-turn state lives in the composable now. Hooks let it call
// back into the view for log scrolling and post-turn refreshes (XP / goals).
const {
  turns,
  currentTurn,
  turnCount,
  tokensIn,
  tokensOut,
  sending,
  sendAction,
  refreshTokens,
} = useGameTurn(sessionId, gs, {
  onTurnDone: () => {
    refreshCharacter()  // pick up XP gains from <character_xp>
    refreshGoals()  // pick up <pc_goal> add/complete
    refreshLocations()  // pick up <location_enter> updates
    refreshNpcLocations()  // pick up <npc_update location="..."> changes
    refreshSuggestions()
  },
  onNpcInitiative: (npcName) => onInitiativeTrigger(npcName),
})

const npcDialogOpen = ref(false)
const selectedNpc = ref<Npc | null>(null)
const characterCardOpen = ref(false)
const feedbackOpen = ref(false)
const screenplay = ref<Screenplay | null>(null)
const currentLocation = ref<{ name: string; description: string; items: { name: string; description: string }[] } | null>(null)

async function refreshNpcLocations() {
  try {
    const fullNpcs = await sessionsApi.npcs(sessionId)
    const npcMap = new Map(fullNpcs.map((n) => [n.name, n]))
    for (const n of npcs.value) {
      const full = npcMap.get(n.name)
      if (full) (n as any).current_location = full.current_location ?? null
    }
  } catch { /* ignore */ }
}

async function refreshLocations() {
  try {
    const locs = await sessionsApi.locations(sessionId)
    const cur = locs.find((l) => l.is_current) ?? null
    currentLocation.value = cur
      ? { name: cur.name, description: cur.description, items: cur.items ?? [] }
      : null
  } catch {
    /* ignore */
  }
}

const modelSwitchOpen = ref(false)
const switchModelId = ref<number | null>(null)

async function applyModelSwitch() {
  if (!switchModelId.value) return
  try {
    await sessionsApi.updateGmModel(sessionId, switchModelId.value)
    ElMessage.success('模型已切换，下一回合生效')
    modelSwitchOpen.value = false
  } catch (e: any) {
    ElMessage.error(e?.message ?? '切换失败')
  }
}

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

async function send() {
  const userAction = action.value.trim()
  if (!userAction || sending.value) return
  action.value = ''
  await sendAction(userAction)
}

async function sendActionDirect(choice: string) {
  if (!choice || sending.value) return
  await sendAction(choice)
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
  // v0.2.1 P0.3: deep-copy events so the dialog never holds a reactive ref
  // back into the turn (which could mutate while the dialog is open and show
  // last turn's NPC/state). Combined with the close-watcher below, each open
  // gets a frozen snapshot of the requested turn.
  eventsDialogEvents.value = JSON.parse(JSON.stringify(t.events ?? []))
  eventsDialogTurn.value = t.turn
  eventsDialogOpen.value = true
}

// v0.2.1 P0.3: clear events on close so the next open never flashes a stale
// frame from the previous turn before the new payload lands.
watch(eventsDialogOpen, (open) => {
  if (!open) {
    nextTick(() => {
      eventsDialogEvents.value = []
      eventsDialogTurn.value = 0
    })
  }
})

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

const suggestions = ref<string[]>([])

function quick(act: string) {
  action.value = act
}

// NPC initiative
const initiativeNpc = ref<string | null>(null)
let initiativeTimer: ReturnType<typeof setTimeout> | null = null

function onInitiativeTrigger(npcName: string) {
  if (!npcName) return
  initiativeNpc.value = npcName
  if (initiativeTimer) clearTimeout(initiativeTimer)
  initiativeTimer = setTimeout(() => triggerInitiative(), 4000)
}

async function triggerInitiative() {
  const npcName = initiativeNpc.value
  initiativeNpc.value = null
  if (initiativeTimer) { clearTimeout(initiativeTimer); initiativeTimer = null }
  if (!npcName) return

  const newTurn = reactive<Turn>({ action: `【${npcName}主动】`, narrative: '', choices: [], events: [], turn: 0 })
  turns.value.push(newTurn)
  sending.value = true

  try {
    await sessionsApi.npcTick(
      sessionId,
      npcName,
      {
        onNarrative: (text) => { newTurn.narrative += text },
        onTag: (name, attrs, content) => {
          if (name === 'choices') {
            newTurn.choices = content.split('\n').map((s: string) => s.replace(/^[-•*]\s*/, '').trim()).filter(Boolean)
          }
          newTurn.events = [...(newTurn.events ?? []), { type: name, payload: attrs, content }]
        },
        onDone: () => {
          sending.value = false
          refreshCharacter()
          refreshGoals()
          refreshLocations()
          refreshNpcLocations()
          refreshSuggestions()
        },
      },
    )
  } finally {
    sending.value = false
  }
}

function dismissInitiative() {
  initiativeNpc.value = null
  if (initiativeTimer) { clearTimeout(initiativeTimer); initiativeTimer = null }
}

// v0.2.3 P2.3: 主推按钮——剧本当前章节下一个 [pending] main_event 作为 hint
const nextMainEvent = computed(() => {
  if (!screenplay.value) return null
  const chapters = screenplay.value.chapters
  const cur = chapters[screenplay.value.current_chapter - 1]
  if (!cur) return null
  const completed = screenplay.value.completed_events
  for (let i = 0; i < cur.main_events.length; i++) {
    const isDone = completed.some(
      (c) =>
        c.chapter === screenplay.value!.current_chapter &&
        c.event_idx === i &&
        c.type === 'main',
    )
    if (!isDone) return cur.main_events[i]
  }
  return null // all main events done
})

// 把通用推进提示塞 input，让玩家审阅／编辑后再发送（不直接 send）
function applyEventHint(_event: string) {
  action.value = '（感觉剧情进展太慢，请主动推进剧情节奏）'
}

async function refreshSuggestions() {
  const lastTurn = turns.value[turns.value.length - 1]
  if (!lastTurn) return
  const narrative = (lastTurn.narrative ?? '').slice(0, 400)
  const activeGoals = goals.value
    .filter((g: any) => g.status === 'active')
    .map((g: any) => g.description)
    .slice(0, 3)
  suggestions.value = await sessionsApi.suggestActions(sessionId, narrative, activeGoals)
}

// Extract narrative text from a stored assistant message (which contains
// raw <narrative>...</narrative> tags interleaved with state tags).
//
// Robustness note: weak models sometimes forget to close <narrative> before
// emitting the next tag (e.g. <choices>). We defensively strip any embedded
// child tags from the narrative content so options/state/dice blocks don't
// leak into the chat log.
const NARRATIVE_RE = /<narrative\b[^>]*>([\s\S]*?)(?:<\/narrative>|(?=<(?:choices|state_change|npc_update|plot_event|dice)\b))/g
const DICE_RE = /<dice\s+([^>]*)>([\s\S]*?)<\/dice>/g
const ATTR_RE = /(\w+)="([^"]*)"/g

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

  // Load model configs for the model-switch dialog.
  if (modelsStore.items.length === 0) await modelsStore.refresh()

  // v0.2.1 P0.4: hydrate side-panel state (esp. inventory) FIRST so the
  // character-card drawer and StatePanel show items immediately, even if
  // later init steps (messages rehydrate, BGM, etc.) hang or throw. The
  // second pass at the end of onMounted re-applies on top to pick up any
  // state writes that landed during init.
  try {
    const st = await sessionsApi.state(sessionId)
    Object.keys(stats).forEach((k) => delete stats[k])
    Object.assign(stats, st.stats)
    inventory.value = st.inventory
    npcs.value = st.npcs.map((n) => ({ ...n }))
    threads.value = st.threads
    pcMood.value = st.pc_mood ? { ...st.pc_mood } : {}
  } catch {
    /* ignore — fall through to the end-of-mount rehydrate below */
  }

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

    // Augment with pinned flag and current_location from /npcs endpoint.
    try {
      const fullNpcs = await sessionsApi.npcs(sessionId)
      const npcMap = new Map(fullNpcs.map((n) => [n.name, n]))
      for (const n of npcs.value) {
        const full = npcMap.get(n.name)
        if (full) {
          n.pinned = full.pinned
          ;(n as any).current_location = full.current_location ?? null
        }
      }
    } catch { /* ignore */ }
  } catch {
    /* ignore */
  }

  await refreshGoals()
  await refreshLocations()

  // v0.2.3 P2.1: 新 session 自动开局——turn_count=0 且无任何 turn 时，
  // 自动派发首个 action 让 GM 输出开局描写。screenplay.opening_hook 是
  // wizard 生成的引子，作为隐式起手 prompt。双重检查 turns.value.length === 0
  // 防止已 hydrate 出消息时重复开局。
  if (turnCount.value === 0 && turns.value.length === 0 && !sending.value) {
    let opener = '(开始游戏 — 描写场景，让我代入)'
    const hook = screenplay.value?.opening_hook
    if (hook) {
      opener = `(开始游戏。开篇引子: ${hook.slice(0, 200)})`
    }
    try {
      await sendAction(opener)
    } catch {
      /* ignore — 玩家可手动输入 */
    }
  }
})

onUnmounted(() => {
  audio.stopBgm()
  if (initiativeTimer) clearTimeout(initiativeTimer)
})
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
          <router-link :to="`/play/${sessionId}/locations`"
                       class="text-sm text-slate-500 hover:text-slate-800">
            📍 场所
          </router-link>
          <button
            type="button"
            class="text-sm text-slate-500 hover:text-slate-800"
            @click="feedbackOpen = true"
          >💬 反馈</button>
          <button
            type="button"
            class="text-xs text-slate-400 hover:text-slate-600 shrink-0"
            @click="modelSwitchOpen = true"
            title="切换 GM 模型"
          >⚙️ 模型</button>
          <span class="flex items-center gap-0.5">
            <button type="button"
              class="text-xs w-5 h-5 flex items-center justify-center text-slate-400 hover:text-slate-700 border border-slate-200 rounded"
              title="缩小字号" @click="changeFontSize(-1)">A-</button>
            <span class="text-xs text-slate-400 w-6 text-center select-none">{{ fontSize }}</span>
            <button type="button"
              class="text-xs w-5 h-5 flex items-center justify-center text-slate-400 hover:text-slate-700 border border-slate-200 rounded"
              title="放大字号" @click="changeFontSize(1)">A+</button>
            <button type="button"
              class="text-xs px-1.5 h-5 flex items-center text-slate-400 hover:text-slate-700 border border-slate-200 rounded ml-0.5"
              title="切换字体" @click="cycleFontFamily()">{{ FONT_FAMILIES[fontFamilyIdx].label }}</button>
          </span>
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

      <div v-if="initiativeNpc" class="initiative-banner">
        <span class="initiative-label">{{ initiativeNpc }} 正在寻找你...</span>
        <el-button size="small" type="primary" @click="triggerInitiative">立即触发</el-button>
        <el-button size="small" @click="dismissInitiative">忽略</el-button>
      </div>

      <MessageList
        :turns="turns"
        :character-name="character?.name"
        :style="{ fontSize: fontSize + 'px', fontFamily }"
        @choose="(c: string) => sendActionDirect(c)"
        @open-events="(t: Turn) => openEvents(t)"
      />

      <div v-if="turns.length && !sending"
           class="px-6 pb-2 flex gap-3 text-xs text-slate-500">
        <button type="button" class="hover:text-slate-800 underline"
                @click="regenerate">🔄 重新生成</button>
        <button type="button" class="hover:text-slate-800 underline"
                @click="editPrev">✏️ 编辑上一动作</button>
      </div>

      <footer class="border-t bg-white p-4 space-y-2">
        <!-- v0.2.3 P2.3: 主推剧本下一个 main_event，点击仅塞 input 让玩家审阅 -->
        <div v-if="nextMainEvent" class="flex justify-end">
          <el-button
            size="small"
            type="info"
            plain
            :disabled="sending"
            @click="applyEventHint(nextMainEvent)"
            title="感觉剧情太慢或走偏时使用"
          >⚡ 推进剧情</el-button>
        </div>
        <!-- 通用 fallback：自由探索 -->
        <div class="flex flex-wrap gap-1">
          <el-button
            v-for="s in (suggestions.length ? suggestions : ['环顾四周', '探索', '搭话'])"
            :key="s"
            size="small"
            @click="quick(s)"
            :disabled="sending"
          >{{ s }}</el-button>
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
                  :current-location="currentLocation"
                  @select-npc="openNpcDetail"
                  @goal-status="updateGoal" />
    </div>

    <!-- Mobile: floating toggle button, drawer slides in from right -->
    <button
      v-if="!panelOpen"
      type="button"
      class="md:hidden fixed bottom-24 right-3 z-20 bg-white border border-slate-300 rounded-full w-10 h-10 shadow flex items-center justify-center text-lg"
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
                  :current-location="currentLocation"
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

    <el-dialog v-model="modelSwitchOpen" title="切换 GM 模型" width="360px">
      <el-select v-model="switchModelId" placeholder="选择新模型" class="w-full">
        <el-option
          v-for="m in modelsStore.items"
          :key="m.id"
          :label="`${m.name} (${m.model_name})`"
          :value="m.id"
        />
      </el-select>
      <template #footer>
        <el-button @click="modelSwitchOpen = false">取消</el-button>
        <el-button type="primary" @click="applyModelSwitch">确认切换</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.initiative-banner {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  background: rgba(64, 158, 255, 0.1);
  border: 1px solid rgba(64, 158, 255, 0.3);
  border-radius: 6px;
  margin-bottom: 8px;
  font-size: 13px;
}
.initiative-label {
  flex: 1;
  color: #409eff;
}
</style>
