<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElButton, ElInput, ElTag, ElProgress, ElMessage, ElDialog, ElTabs, ElTabPane } from 'element-plus'
import {
  screenplayApi,
  eventDescription,
  eventCriteria,
  eventKeywords,
  type Screenplay,
  type ScreenplayChapter,
  type ScreenplayMainCharacter,
  type CompletedEvent,
  type ScreenplayRevision,
} from '@/api/screenplay'

const props = defineProps<{ id: string }>()
const sessionId = Number(props.id)
const router = useRouter()

const screenplay = ref<Screenplay | null>(null)
const revisions = ref<ScreenplayRevision[]>([])
const loading = ref(true)
const decisionOpen = ref(false)
const decisionText = ref('')
const processingRevId = ref<number | null>(null)

// ── 手动编辑大纲 ─────────────────────────────────────────────
const editOpen = ref(false)
const editTab = ref('opening')
const editOpeningHook = ref('')
const editChaptersJson = ref('')
const editNpcsJson = ref('')
const editEndingMd = ref('')
const editSaving = ref(false)

function openEditDialog() {
  if (!screenplay.value) return
  editOpeningHook.value = screenplay.value.opening_hook ?? ''
  editChaptersJson.value = JSON.stringify(screenplay.value.chapters, null, 2)
  editNpcsJson.value = JSON.stringify(screenplay.value.main_characters, null, 2)
  editEndingMd.value = screenplay.value.ending_md ?? ''
  editTab.value = 'opening'
  editOpen.value = true
}

async function saveEdit() {
  // Validate JSON textareas before submitting
  let parsedChapters: ScreenplayChapter[] | undefined
  let parsedNpcs: ScreenplayMainCharacter[] | undefined

  try {
    parsedChapters = JSON.parse(editChaptersJson.value)
    if (!Array.isArray(parsedChapters)) throw new Error('not an array')
  } catch {
    ElMessage.warning('章节 JSON 格式不正确')
    return
  }

  try {
    parsedNpcs = JSON.parse(editNpcsJson.value)
    if (!Array.isArray(parsedNpcs)) throw new Error('not an array')
  } catch {
    ElMessage.warning('主要 NPC JSON 格式不正确')
    return
  }

  editSaving.value = true
  try {
    screenplay.value = await screenplayApi.update(sessionId, {
      chapters: parsedChapters,
      main_characters: parsedNpcs,
      ending_md: editEndingMd.value,
      opening_hook: editOpeningHook.value,
    })
    await loadRevisions()
    editOpen.value = false
    ElMessage.success('大纲已更新')
  } catch (e: any) {
    ElMessage.error(e?.message ?? '保存失败')
  } finally {
    editSaving.value = false
  }
}

async function loadRevisions() {
  try {
    revisions.value = await screenplayApi.revisions(sessionId)
  } catch {
    revisions.value = []
  }
}

onMounted(async () => {
  try {
    screenplay.value = await screenplayApi.getActive(sessionId)
    await loadRevisions()
  } catch (e) {
    ElMessage.warning('当前 session 还没有剧本')
  } finally {
    loading.value = false
  }
})

async function processRevision(revId: number) {
  processingRevId.value = revId
  try {
    const r = await screenplayApi.processRevision(sessionId, revId)
    ElMessage.success(`大纲已重写：${r.diff_summary}`)
    screenplay.value = await screenplayApi.getActive(sessionId)
    await loadRevisions()
  } catch (e: any) {
    ElMessage.error(`重写失败：${e?.message ?? e}`)
  } finally {
    processingRevId.value = null
  }
}

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
    const r = await screenplayApi.markDecision(sessionId, t)
    ElMessage.success(r.diff_summary ? `大纲已重写：${r.diff_summary}` : '已标记')
    decisionOpen.value = false
    decisionText.value = ''
    screenplay.value = await screenplayApi.getActive(sessionId)
    await loadRevisions()
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
        <div class="flex gap-2">
          <el-button type="primary" @click="continueNext">📖 续写下一章</el-button>
          <el-button @click="openEditDialog">✏️ 编辑大纲</el-button>
        </div>
      </div>

      <!-- 当前章节 -->
      <div v-if="currentChapter" class="bg-white border border-slate-200 rounded p-4 space-y-3">
        <h2 class="text-lg font-bold text-slate-800">
          第 {{ screenplay.current_chapter }} 章：{{ currentChapter.title }}
        </h2>
        <p class="text-sm text-slate-600 italic">{{ currentChapter.summary }}</p>

        <div v-if="currentChapter.main_events.length">
          <div class="text-sm font-bold text-slate-700 mt-2 mb-1">本章主线</div>
          <ul class="space-y-2">
            <li v-for="(ev, i) in currentChapter.main_events" :key="i" class="text-sm">
              <div class="flex items-start gap-2">
                <el-tag v-if="isEventDone(screenplay.current_chapter, i, 'main')" type="success" size="small">
                  ✓ done
                </el-tag>
                <el-tag v-else type="warning" size="small">pending</el-tag>
                <div class="flex-1 min-w-0">
                  <div class="text-slate-800">{{ eventDescription(ev) }}</div>
                  <div v-if="eventKeywords(ev).length" class="mt-0.5 flex flex-wrap gap-1">
                    <span
                      v-for="kw in eventKeywords(ev)" :key="kw"
                      class="text-xs text-slate-500 bg-slate-100 px-1.5 py-0.5 rounded"
                    >#{{ kw }}</span>
                  </div>
                  <div v-if="eventCriteria(ev)" class="text-xs text-slate-500 italic mt-0.5">
                    完成条件：{{ eventCriteria(ev) }}
                  </div>
                </div>
              </div>
            </li>
          </ul>
        </div>

        <div v-if="currentChapter.optional_events.length">
          <div class="text-sm font-bold text-slate-700 mt-2 mb-1">本章可选支线</div>
          <ul class="space-y-2">
            <li v-for="(ev, i) in currentChapter.optional_events" :key="i" class="text-sm">
              <div class="flex items-start gap-2">
                <el-tag v-if="isEventDone(screenplay.current_chapter, i, 'optional')" type="success" size="small">
                  ✓ done
                </el-tag>
                <el-tag v-else size="small">optional</el-tag>
                <div class="flex-1 min-w-0">
                  <div class="text-slate-700">{{ eventDescription(ev) }}</div>
                  <div v-if="eventCriteria(ev)" class="text-xs text-slate-500 italic mt-0.5">
                    完成条件：{{ eventCriteria(ev) }}
                  </div>
                </div>
              </div>
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

      <!-- 待处理的 plot_turn（GM 自动标记） -->
      <div v-if="revisions.some((r) => r.pending)"
           class="bg-orange-50 border border-orange-200 rounded p-4 space-y-2">
        <div class="text-sm font-bold text-orange-900">⚡ 待处理的剧情转折</div>
        <div class="text-xs text-orange-700">GM 标记的重大转折，点击重写大纲让后续章节反映这些决定。</div>
        <div v-for="r in revisions.filter((rv) => rv.pending)" :key="r.id"
             class="bg-white border border-orange-200 rounded p-2 flex items-center justify-between gap-2">
          <div class="text-sm flex-1 min-w-0">
            <div class="text-xs text-slate-400">回合 {{ r.trigger_turn }}</div>
            <div class="text-slate-700 truncate">{{ r.trigger_description }}</div>
          </div>
          <el-button
            type="primary"
            size="small"
            :loading="processingRevId === r.id"
            @click="processRevision(r.id)"
          >🔄 重写</el-button>
        </div>
      </div>

      <!-- 改写历史（已处理的 revisions） -->
      <div v-if="revisions.some((r) => !r.pending)"
           class="bg-slate-50 border border-slate-200 rounded p-4 space-y-2">
        <div class="text-sm font-bold text-slate-700">📝 改写历史</div>
        <div v-for="r in revisions.filter((rv) => !rv.pending)" :key="r.id"
             class="bg-white border border-slate-200 rounded p-2 text-xs">
          <div class="text-slate-400">回合 {{ r.trigger_turn }} · {{ r.created_at?.slice(0, 16).replace('T', ' ') }}</div>
          <div class="text-slate-700 mt-0.5">{{ r.trigger_description }}</div>
          <div class="text-slate-500 mt-1 italic">→ {{ r.diff_summary }}</div>
        </div>
      </div>

      <!-- 标记重大决策 + 手动编辑大纲 -->
      <div class="border-t pt-4 flex flex-wrap gap-2">
        <el-button @click="decisionOpen = true">⚡ 这是重要决定（标记后立即重写大纲）</el-button>
        <el-button v-if="screenplay.status !== 'concluded'" @click="openEditDialog">✏️ 编辑大纲</el-button>
      </div>

      <el-dialog v-model="decisionOpen" title="标记重大决定" width="500px">
        <el-input v-model="decisionText" type="textarea" :autosize="{ minRows: 3, maxRows: 6 }"
          placeholder="描述这个决定 + 为什么觉得它会改变后续走向" />
        <template #footer>
          <el-button @click="decisionOpen = false">取消</el-button>
          <el-button type="primary" @click="submitDecision">提交</el-button>
        </template>
      </el-dialog>

      <!-- 手动编辑大纲对话框 -->
      <el-dialog v-model="editOpen" title="✏️ 编辑大纲" width="700px">
        <el-tabs v-model="editTab">
          <!-- Tab: 开场 -->
          <el-tab-pane label="开场" name="opening">
            <div class="text-xs text-slate-500 mb-1">开篇引子（游戏开始时展示给玩家）</div>
            <el-input
              v-model="editOpeningHook"
              type="textarea"
              :autosize="{ minRows: 3, maxRows: 8 }"
              placeholder="开篇引子文本"
            />
          </el-tab-pane>

          <!-- Tab: 章节 -->
          <el-tab-pane label="章节" name="chapters">
            <div class="text-xs text-slate-500 mb-2">
              章节 JSON 数组（每章包含 title / summary / main_events / optional_events / main_npcs）。
              点击 ➕ / 🗑️ 添加/删除章节，或直接编辑 JSON。
            </div>
            <!-- Quick add/remove buttons -->
            <div class="flex gap-2 mb-2">
              <el-button size="small" @click="() => {
                try {
                  const arr = JSON.parse(editChaptersJson)
                  arr.push({ title: '', summary: '', main_events: [], optional_events: [], main_npcs: [] })
                  editChaptersJson = JSON.stringify(arr, null, 2)
                } catch { ElMessage.warning('请先修正 JSON 格式') }
              }">➕ 添加章节</el-button>
              <el-button size="small" type="danger" @click="() => {
                try {
                  const arr = JSON.parse(editChaptersJson)
                  if (arr.length > 0) {
                    arr.pop()
                    editChaptersJson = JSON.stringify(arr, null, 2)
                  }
                } catch { ElMessage.warning('请先修正 JSON 格式') }
              }">🗑️ 删除末章</el-button>
            </div>
            <el-input
              v-model="editChaptersJson"
              type="textarea"
              :autosize="{ minRows: 8, maxRows: 20 }"
              placeholder="[]"
              class="font-mono text-xs"
            />
          </el-tab-pane>

          <!-- Tab: 主要 NPC -->
          <el-tab-pane label="主要 NPC" name="npcs">
            <div class="text-xs text-slate-500 mb-1">
              主要角色 JSON 数组（每项含 name / role / description / intro_chapter）
            </div>
            <el-input
              v-model="editNpcsJson"
              type="textarea"
              :autosize="{ minRows: 6, maxRows: 16 }"
              placeholder="[]"
              class="font-mono text-xs"
            />
          </el-tab-pane>

          <!-- Tab: 结局 -->
          <el-tab-pane label="结局" name="ending">
            <div class="text-xs text-slate-500 mb-1">预设结局描述（Markdown）</div>
            <el-input
              v-model="editEndingMd"
              type="textarea"
              :autosize="{ minRows: 4, maxRows: 12 }"
              placeholder="预设结局文本"
            />
          </el-tab-pane>
        </el-tabs>

        <template #footer>
          <el-button @click="editOpen = false">取消</el-button>
          <el-button type="primary" :loading="editSaving" @click="saveEdit">保存</el-button>
        </template>
      </el-dialog>
    </template>
  </div>
</template>
