<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import {
  ElSelect, ElOption, ElTabs, ElTabPane, ElTag, ElEmpty, ElButton,
  ElMessage, ElMessageBox,
} from 'element-plus'
import {
  sessionsApi,
  type Npc,
  type PlotThreadItem,
  type HiddenEventItem,
  type FeedbackItem,
  type MessageRow,
} from '@/api/sessions'
import type { GameSession } from '@/api/types'
import { screenplayApi, eventDescription, type Screenplay } from '@/api/screenplay'

const sessions = ref<GameSession[]>([])
const selectedSid = ref<number | null>(null)

const screenplay = ref<Screenplay | null>(null)
const npcs = ref<Npc[]>([])
const threads = ref<PlotThreadItem[]>([])
const hiddenEvents = ref<HiddenEventItem[]>([])
const feedback = ref<FeedbackItem[]>([])
const messages = ref<MessageRow[]>([])
const loading = ref(false)
const errMsg = ref('')

const tokensIn = computed(() =>
  messages.value.filter((m) => m.role === 'assistant').reduce((s, m) => s + m.tokens_in, 0),
)
const tokensOut = computed(() =>
  messages.value.filter((m) => m.role === 'assistant').reduce((s, m) => s + m.tokens_out, 0),
)
const lastSystemPromptMsgs = computed(() => {
  // We can't directly read what was last sent to the GM from the FE — but we
  // can show the last GM response raw content (with all hidden tags) which is
  // what the GM emitted, not what the GM received.
  return messages.value.filter((m) => m.role === 'assistant').slice(-3)
})

onMounted(async () => {
  try {
    sessions.value = await sessionsApi.list()
    if (sessions.value.length) selectedSid.value = sessions.value[sessions.value.length - 1].id
  } catch (e: any) {
    errMsg.value = `加载存档列表失败：${e?.message ?? e}`
  }
})

// v0.1.9: bulk-delete every NER-fallback stub NPC (description = "（GM 未补全）")
// for the current session. Used to clean up historical false positives picked
// up by older / looser NER thresholds.
async function cleanupAutoCreated() {
  if (!selectedSid.value) return
  try {
    await ElMessageBox.confirm(
      '将删除所有 description 为「（GM 未补全）」的 NPC（NER fallback 自动建的 stub）。已被 GM 通过 npc_update 补全的 NPC 不会被删。',
      '清理 NER 自动创建的 NPC',
      { type: 'warning', confirmButtonText: '确认清理', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  try {
    await sessionsApi.deleteAutoCreatedNpcs(selectedSid.value)
    ElMessage.success('清理完成')
    npcs.value = await sessionsApi.npcs(selectedSid.value)
  } catch (e: any) {
    ElMessage.error(e?.message ?? '清理失败')
  }
}

watch(selectedSid, async (sid) => {
  if (sid == null) return
  loading.value = true
  errMsg.value = ''
  try {
    const [sp, npcList, thList, hidList, fbList, msgList] = await Promise.all([
      screenplayApi.getActive(sid).catch(() => null),
      sessionsApi.npcs(sid),
      sessionsApi.threads(sid),
      sessionsApi.hiddenEvents(sid, true),
      sessionsApi.listFeedback(sid),
      sessionsApi.messages(sid),
    ])
    screenplay.value = sp
    npcs.value = npcList
    threads.value = thList
    hiddenEvents.value = hidList
    feedback.value = fbList
    messages.value = msgList
  } catch (e: any) {
    errMsg.value = `加载失败：${e?.message ?? e}`
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div class="h-full overflow-auto p-6 max-w-6xl mx-auto space-y-4">
    <header class="flex items-center justify-between">
      <h1 class="text-2xl font-bold text-slate-800">🐛 调试模式</h1>
      <div class="text-xs text-slate-500">
        ↑↑↓↓←→←→ 再次输入可关闭调试模式（任何页面均可）
      </div>
    </header>

    <div class="bg-amber-50 border border-amber-200 rounded p-3 text-sm text-amber-900">
      此页面展示一切：完整剧本（含未来章节、未出场 NPC）、所有 hidden_events（含 GM only 后果）、
      未揭示的 NPC 字段、token 统计、原始消息。**正常游玩时关闭调试模式以避免剧透**。
    </div>

    <div class="flex items-center gap-3">
      <span class="font-bold text-slate-700">选择存档：</span>
      <el-select v-model="selectedSid" placeholder="选择存档" class="!w-64">
        <el-option
          v-for="s in sessions"
          :key="s.id"
          :label="`${s.name} (#${s.id}, 第 ${s.turn_count} 回合)`"
          :value="s.id"
        />
      </el-select>
    </div>

    <div v-if="errMsg" class="bg-red-50 border border-red-200 text-red-700 text-sm p-3 rounded">
      {{ errMsg }}
    </div>

    <div v-if="loading" class="text-slate-500">加载中…</div>

    <el-tabs v-else-if="selectedSid != null" type="border-card">
      <!-- 完整剧本 -->
      <el-tab-pane label="📜 完整剧本（含未来章节）">
        <el-empty v-if="!screenplay" description="此存档没有剧本" />
        <div v-else class="space-y-3">
          <div class="text-sm text-slate-600">
            类型：{{ screenplay.genre }} · 当前 {{ screenplay.current_chapter }} / {{ screenplay.chapters.length }} 章 ·
            状态：<el-tag :type="screenplay.status === 'concluded' ? 'success' : 'primary'" size="small">
              {{ screenplay.status }}
            </el-tag>
            <span v-if="screenplay.parent_screenplay_id" class="ml-2 text-purple-600">
              续作 v{{ screenplay.version }} (parent #{{ screenplay.parent_screenplay_id }})
            </span>
          </div>

          <div class="bg-blue-50 border border-blue-200 rounded p-3 text-sm">
            <div class="font-bold text-blue-900 mb-1">🎯 完结条件（剧透）</div>
            <div class="text-slate-700">{{ screenplay.ending_md }}</div>
          </div>

          <div v-for="(ch, idx) in screenplay.chapters" :key="idx"
               class="bg-white border rounded p-3"
               :class="idx + 1 === screenplay.current_chapter ? 'border-blue-400 ring-2 ring-blue-200' : 'border-slate-200'">
            <div class="font-bold text-slate-800">
              第 {{ idx + 1 }} 章：{{ ch.title }}
              <el-tag v-if="idx + 1 < screenplay.current_chapter" type="success" size="small">已演完</el-tag>
              <el-tag v-else-if="idx + 1 === screenplay.current_chapter" type="primary" size="small">当前</el-tag>
              <el-tag v-else type="info" size="small">未来（剧透）</el-tag>
            </div>
            <div class="text-sm text-slate-600 italic mt-1">{{ ch.summary }}</div>

            <div v-if="ch.main_events.length" class="mt-2 text-sm">
              <span class="font-bold">主线：</span>
              <ul class="ml-4 list-disc">
                <li v-for="(ev, i) in ch.main_events" :key="i">{{ eventDescription(ev) }}</li>
              </ul>
            </div>
            <div v-if="ch.optional_events.length" class="mt-1 text-sm">
              <span class="font-bold">支线：</span>
              <ul class="ml-4 list-disc text-slate-500">
                <li v-for="(ev, i) in ch.optional_events" :key="i">{{ eventDescription(ev) }}</li>
              </ul>
            </div>
            <div v-if="ch.main_npcs.length" class="mt-1 text-sm">
              <span class="font-bold">NPC：</span>{{ ch.main_npcs.join('、') }}
            </div>
          </div>

          <div class="bg-slate-50 border border-slate-200 rounded p-3 text-sm">
            <div class="font-bold mb-1">主要 NPC 名单（含未出场）</div>
            <div v-for="(c, i) in screenplay.main_characters" :key="i" class="mt-1">
              <el-tag size="small">第 {{ c.intro_chapter }} 章登场</el-tag>
              <strong class="ml-2">{{ c.name }}</strong>
              <span class="text-slate-600">（{{ c.role }}）— {{ c.description }}</span>
            </div>
          </div>

          <div v-if="screenplay.completed_events.length" class="text-xs text-slate-500">
            已完成事件 {{ screenplay.completed_events.length }} 条：
            <code>{{ JSON.stringify(screenplay.completed_events) }}</code>
          </div>
        </div>
      </el-tab-pane>

      <!-- Hidden events -->
      <el-tab-pane :label="`🌑 隐性事件 (${hiddenEvents.length})`">
        <el-empty v-if="!hiddenEvents.length" description="无隐性事件" />
        <div v-else class="space-y-2">
          <div v-for="ev in hiddenEvents" :key="ev.id"
               class="bg-white border rounded p-3"
               :class="ev.status === 'active' ? 'border-red-300' : 'border-slate-200 opacity-70'">
            <div class="flex items-center gap-2">
              <el-tag size="small">{{ ev.kind }}</el-tag>
              <el-tag size="small" :type="ev.status === 'active' ? 'danger' : 'info'">
                {{ ev.status }}
              </el-tag>
              <strong>{{ ev.subject }}</strong>
              <span class="text-xs text-slate-500">severity={{ ev.severity }} · t={{ ev.introduced_turn }}</span>
            </div>
            <div class="text-sm mt-1">{{ ev.description }}</div>
            <div class="text-xs text-red-600 mt-1">
              <strong>GM-only 后果：</strong>{{ ev.consequence }}
            </div>
          </div>
        </div>
      </el-tab-pane>

      <!-- NPCs full -->
      <el-tab-pane :label="`👥 NPC 全字段 (${npcs.length})`">
        <el-empty v-if="!npcs.length" description="无 NPC" />
        <div v-else class="space-y-2">
          <div class="flex justify-end">
            <el-button size="small" type="warning" plain @click="cleanupAutoCreated">
              🧹 清理 NER 自动创建的 NPC
            </el-button>
          </div>
          <div v-for="n in npcs" :key="n.name" class="bg-white border border-slate-200 rounded p-3">
            <div class="flex items-center gap-2">
              <strong>{{ n.name }}</strong>
              <el-tag v-if="n.pinned" size="small">📌 pinned</el-tag>
              <span class="text-xs text-slate-500">favor={{ n.favor }} · {{ n.state }}</span>
            </div>
            <div class="text-xs text-slate-500 mt-1">原型：{{ n.archetype || '（无）' }}</div>
            <div class="text-sm mt-1">{{ n.description || '（无描述）' }}</div>
            <div class="text-sm mt-1">
              <strong class="text-purple-700">动机：</strong>{{ n.purpose || '（无）' }}
            </div>
            <div v-if="n.affinity" class="text-xs text-slate-600 mt-1">
              affinity: <code>{{ JSON.stringify(n.affinity) }}</code>
            </div>
            <div v-if="n.emotion" class="text-xs text-slate-600 mt-1">
              emotion: <code>{{ JSON.stringify(n.emotion) }}</code>
            </div>
            <div v-if="n.revealed" class="text-xs text-amber-600 mt-1">
              玩家可见字段: <code>{{ Object.keys(n.revealed).filter((k) => n.revealed![k]).join(', ') }}</code>
            </div>
          </div>
        </div>
      </el-tab-pane>

      <!-- Plot threads -->
      <el-tab-pane :label="`🎯 剧情线 (${threads.length})`">
        <el-empty v-if="!threads.length" description="无剧情线" />
        <div v-else class="space-y-2">
          <div v-for="(t, i) in threads" :key="i" class="bg-white border border-slate-200 rounded p-2 text-sm">
            <el-tag size="small">{{ t.type }}</el-tag>
            <span class="ml-2">{{ '★'.repeat(t.importance) }}</span>
            <span class="ml-2">{{ t.description }}</span>
          </div>
        </div>
      </el-tab-pane>

      <!-- Tokens / messages -->
      <el-tab-pane :label="`📊 Token / 消息 (${messages.length})`">
        <div class="bg-slate-50 border border-slate-200 rounded p-3 text-sm mb-3">
          tokens 累计：in <strong>{{ tokensIn }}</strong> / out <strong>{{ tokensOut }}</strong>（{{ messages.length }} 条消息）
        </div>
        <div class="space-y-1">
          <div v-for="m in messages" :key="m.id"
               class="text-xs border-l-2 pl-2"
               :class="m.role === 'assistant' ? 'border-blue-300' : 'border-slate-300'">
            <span class="text-slate-500">#{{ m.id }} · {{ m.role }} · 回合 {{ m.turn }}</span>
            <span v-if="m.role === 'assistant'" class="text-slate-500 ml-2">
              ({{ m.tokens_in }} → {{ m.tokens_out }})
            </span>
            <pre class="whitespace-pre-wrap mt-1 text-slate-700">{{ m.content.slice(0, 400) }}{{ m.content.length > 400 ? '…' : '' }}</pre>
          </div>
        </div>
      </el-tab-pane>

      <!-- Feedback -->
      <el-tab-pane :label="`💬 反馈 (${feedback.length})`">
        <el-empty v-if="!feedback.length" description="无反馈" />
        <div v-else class="space-y-2">
          <div v-for="f in feedback" :key="f.id" class="bg-white border border-slate-200 rounded p-3">
            <div class="flex items-center gap-2">
              <el-tag size="small">{{ f.kind }}</el-tag>
              <span class="text-xs text-slate-500">回合 {{ f.turn }} · {{ f.created_at }}</span>
            </div>
            <div class="text-sm mt-1 whitespace-pre-wrap">{{ f.content }}</div>
          </div>
        </div>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>
