<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElButton, ElInput, ElTag, ElProgress, ElMessage, ElDialog } from 'element-plus'
import { screenplayApi, type Screenplay, type CompletedEvent } from '@/api/screenplay'

const props = defineProps<{ id: string }>()
const sessionId = Number(props.id)
const router = useRouter()

const screenplay = ref<Screenplay | null>(null)
const loading = ref(true)
const decisionOpen = ref(false)
const decisionText = ref('')

onMounted(async () => {
  try {
    screenplay.value = await screenplayApi.getActive(sessionId)
  } catch (e) {
    ElMessage.warning('当前 session 还没有剧本')
  } finally {
    loading.value = false
  }
})

const currentChapter = computed(() => {
  if (!screenplay.value) return null
  const idx = Math.max(0, Math.min(screenplay.value.current_chapter - 1, screenplay.value.chapters.length - 1))
  return screenplay.value.chapters[idx] ?? null
})

function isEventDone(chapter: number, eventIdx: number, type: 'main' | 'optional'): boolean {
  if (!screenplay.value) return false
  return screenplay.value.completed_events.some(
    (c: CompletedEvent) =>
      c.chapter === chapter && c.event_idx === eventIdx && c.type === type,
  )
}

const progressPct = computed(() => {
  if (!screenplay.value) return 0
  const total = screenplay.value.chapters.reduce(
    (sum, ch) => sum + ch.main_events.length, 0,
  )
  if (total === 0) return 0
  const done = screenplay.value.completed_events.filter((c) => c.type === 'main').length
  return Math.round((done / total) * 100)
})

async function submitDecision() {
  const t = decisionText.value.trim()
  if (!t) {
    ElMessage.warning('请描述这个决定')
    return
  }
  try {
    await screenplayApi.markDecision(sessionId, t)
    ElMessage.success('已标记为重大决定，下次大纲更新时会反映')
    decisionOpen.value = false
    decisionText.value = ''
  } catch (e: any) {
    ElMessage.error(`标记失败：${e?.message ?? e}`)
  }
}

async function continueNext() {
  try {
    const sp = await screenplayApi.continueNext(sessionId)
    screenplay.value = sp
    ElMessage.success('已生成下一章！')
  } catch (e: any) {
    ElMessage.error(`生成失败：${e?.message ?? e}`)
  }
}

function backToGame() {
  router.push(`/play/${sessionId}`)
}
</script>

<template>
  <div class="h-full overflow-auto p-6 max-w-4xl mx-auto space-y-4">
    <header class="flex items-center justify-between">
      <h1 class="text-2xl font-bold text-slate-800">📜 剧本进度</h1>
      <el-button @click="backToGame">返回跑团</el-button>
    </header>

    <div v-if="loading" class="text-slate-500">加载中…</div>
    <div v-else-if="!screenplay" class="text-slate-500 italic">
      此存档还没有剧本。可在新建存档时选择或自定义剧本类型。
    </div>

    <template v-else>
      <!-- 总进度 -->
      <div class="bg-white border border-slate-200 rounded p-4 space-y-2">
        <div class="text-sm text-slate-500">
          类型：{{ screenplay.genre }} · 第 {{ screenplay.current_chapter }} / {{ screenplay.chapters.length }} 章
          <span v-if="screenplay.parent_screenplay_id" class="ml-2 text-purple-600">
            (续作 · 第 {{ screenplay.version }} 版)
          </span>
        </div>
        <el-progress :percentage="progressPct" :show-text="true" />
      </div>

      <!-- 已完结 -->
      <div v-if="screenplay.status === 'concluded'"
           class="bg-blue-50 border border-blue-200 rounded p-4 space-y-2">
        <div class="font-bold text-blue-900">🎬 故事已完结</div>
        <div class="text-sm text-slate-700">{{ screenplay.ending_md }}</div>
        <el-button type="primary" @click="continueNext">📖 续写下一章</el-button>
      </div>

      <!-- 当前章节 -->
      <div v-if="currentChapter" class="bg-white border border-slate-200 rounded p-4 space-y-3">
        <h2 class="text-lg font-bold text-slate-800">
          第 {{ screenplay.current_chapter }} 章：{{ currentChapter.title }}
        </h2>
        <p class="text-sm text-slate-600 italic">{{ currentChapter.summary }}</p>

        <div v-if="currentChapter.main_events.length">
          <div class="text-sm font-bold text-slate-700 mt-2 mb-1">本章主线</div>
          <ul class="space-y-1">
            <li v-for="(ev, i) in currentChapter.main_events" :key="i" class="text-sm">
              <el-tag v-if="isEventDone(screenplay.current_chapter, i, 'main')" type="success" size="small">
                ✓ done
              </el-tag>
              <el-tag v-else type="warning" size="small">pending</el-tag>
              <span class="ml-2">{{ ev }}</span>
            </li>
          </ul>
        </div>

        <div v-if="currentChapter.optional_events.length">
          <div class="text-sm font-bold text-slate-700 mt-2 mb-1">本章可选支线</div>
          <ul class="space-y-1">
            <li v-for="(ev, i) in currentChapter.optional_events" :key="i" class="text-sm">
              <el-tag v-if="isEventDone(screenplay.current_chapter, i, 'optional')" type="success" size="small">
                ✓ done
              </el-tag>
              <el-tag v-else size="small">optional</el-tag>
              <span class="ml-2">{{ ev }}</span>
            </li>
          </ul>
        </div>

        <div v-if="currentChapter.main_npcs.length" class="text-sm text-slate-600 mt-2">
          本章重要 NPC：{{ currentChapter.main_npcs.join('、') }}
        </div>
      </div>

      <!-- 完结条件 -->
      <div v-if="screenplay.ending_md" class="bg-amber-50 border border-amber-200 rounded p-4">
        <div class="text-sm font-bold text-amber-900 mb-1">🎯 完结条件</div>
        <div class="text-sm text-slate-700">{{ screenplay.ending_md }}</div>
      </div>

      <!-- 标记重大决策 -->
      <div class="border-t pt-4">
        <el-button @click="decisionOpen = true">⚡ 这是重要决定（标记后影响后续大纲）</el-button>
      </div>

      <el-dialog v-model="decisionOpen" title="标记重大决定" width="500px">
        <el-input v-model="decisionText" type="textarea" :autosize="{ minRows: 3, maxRows: 6 }"
          placeholder="描述这个决定 + 为什么觉得它会改变后续走向" />
        <template #footer>
          <el-button @click="decisionOpen = false">取消</el-button>
          <el-button type="primary" @click="submitDecision">提交</el-button>
        </template>
      </el-dialog>
    </template>
  </div>
</template>
