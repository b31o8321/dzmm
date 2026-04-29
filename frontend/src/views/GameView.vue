<script setup lang="ts">
import { ref, reactive, nextTick, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { streamTurn } from '@/composables/useTurnStream'
import { useSessionsStore } from '@/stores/sessions'
import StatePanel from '@/components/StatePanel.vue'
import MarkdownView from '@/components/MarkdownView.vue'

const props = defineProps<{ id: string }>()
const sessionId = Number(props.id)
const sessionsStore = useSessionsStore()

interface Turn {
  action: string
  narrative: string
}
const turns = ref<Turn[]>([])
const currentTurn = ref<Turn | null>(null)
const action = ref('')
const sending = ref(false)
const turnCount = ref(0)

const stats = reactive<Record<string, number>>({})
const inventory = ref<string[]>([])
const npcs = ref<{ name: string; favor: number; state: string }[]>([])
const dice = ref<{ skill: string; target: string; result: string }[]>([])
const threads = ref<{ type: string; description: string; importance: number }[]>([])

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

async function send() {
  if (!action.value.trim() || sending.value) return
  const userAction = action.value.trim()
  action.value = ''
  sending.value = true

  const turn: Turn = { action: userAction, narrative: '' }
  currentTurn.value = turn
  turns.value.push(turn)
  await scrollToBottom()

  try {
    await streamTurn(sessionId, userAction, {
      onNarrative: (text) => {
        turn.narrative += text
        scrollToBottom()
      },
      onTag: (name, attrs, content) => {
        if (name === 'state_change') applyStateChange(content)
        else if (name === 'npc_update') applyNpcUpdate(content)
        else if (name === 'dice') {
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

const quickActions = ['环顾四周', '探索', '搭话', '潜行', '战斗', '使用物品']

function quick(act: string) {
  action.value = act
}

onMounted(async () => {
  try {
    const sess = await sessionsStore.get(sessionId)
    turnCount.value = sess.turn_count
  } catch {
    /* ignore */
  }
})
</script>

<template>
  <div class="flex h-full">
    <section class="flex-1 flex flex-col bg-slate-50">
      <header class="px-6 py-3 border-b bg-white flex items-center justify-between">
        <div class="font-bold">跑团进行中（已进行 {{ turnCount }} 回合）</div>
        <router-link to="/sessions" class="text-sm text-slate-500 hover:text-slate-800">
          返回存档
        </router-link>
      </header>

      <div ref="logEl" class="flex-1 overflow-auto px-6 py-4 space-y-6">
        <div v-if="!turns.length" class="text-slate-400 italic">
          输入第一个行动开始跑团（例如：「(开始游戏)」让 GM 给你开局描写）
        </div>
        <article v-for="(t, i) in turns" :key="i" class="space-y-2">
          <div class="text-sm text-slate-500 font-medium">▶ {{ t.action }}</div>
          <div class="bg-white rounded shadow-sm p-4">
            <MarkdownView :source="t.narrative" />
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
            :rows="2"
            placeholder="输入你的行动…（Cmd/Ctrl+Enter 发送）"
            @keydown.enter.meta.prevent="send"
            @keydown.enter.ctrl.prevent="send"
            :disabled="sending"
          />
          <el-button type="primary" :loading="sending" @click="send">发送</el-button>
        </div>
      </footer>
    </section>

    <StatePanel :stats="stats" :inventory="inventory" :npcs="npcs"
                :dice="dice" :threads="threads" />
  </div>
</template>
