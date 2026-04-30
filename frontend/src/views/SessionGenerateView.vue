<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElProgress, ElButton } from 'element-plus'
import { screenplayApi, type Screenplay } from '@/api/screenplay'
import MarkdownView from '@/components/MarkdownView.vue'

const route = useRoute()
const router = useRouter()
const sessionId = Number(route.params.id)

const elapsed = ref(0)
const phase = ref<'generating' | 'preview' | 'failed'>('generating')
const errorMsg = ref('')
const screenplay = ref<Screenplay | null>(null)

const tips = [
  '剧本里包含主线和支线，主线是 GM 必须演的，支线由你探索触发',
  '关键决策可能改变后续章节走向',
  '剧本完结后可以续写下一章，保留人物状态',
  '主要 NPC 会在不同章节登场，跟他们的关系会影响剧情',
]
const tipIdx = ref(0)
let timer: number | null = null

function clearTimer() {
  if (timer !== null) {
    window.clearInterval(timer)
    timer = null
  }
}

async function runGenerate() {
  phase.value = 'generating'
  errorMsg.value = ''
  elapsed.value = 0
  tipIdx.value = 0

  const genre = (route.query.genre as string) || '悬疑探案'
  const customPrompt = (route.query.custom_prompt as string) || ''

  clearTimer()
  timer = window.setInterval(() => {
    elapsed.value += 1
    if (elapsed.value % 3 === 0) {
      tipIdx.value = (tipIdx.value + 1) % tips.length
    }
  }, 1000)

  try {
    const sp = await screenplayApi.generate(sessionId, {
      genre,
      custom_prompt: customPrompt,
    })
    screenplay.value = sp
    phase.value = 'preview'
  } catch (e: any) {
    phase.value = 'failed'
    errorMsg.value = e?.message ?? String(e)
  } finally {
    clearTimer()
  }
}

onMounted(() => {
  if (!Number.isFinite(sessionId) || sessionId <= 0) {
    phase.value = 'failed'
    errorMsg.value = '无效的 session id'
    return
  }
  void runGenerate()
})

onBeforeUnmount(() => {
  clearTimer()
})

function startPlay() {
  router.push(`/play/${sessionId}`)
}

function retry() {
  void runGenerate()
}

function backToSessions() {
  router.push('/sessions')
}
</script>

<template>
  <div class="h-full flex items-center justify-center bg-slate-50 p-6">
    <div
      v-if="phase === 'generating'"
      class="max-w-md w-full text-center space-y-4"
    >
      <div class="text-2xl font-bold text-slate-700">📜 正在为你生成剧本...</div>
      <div class="text-sm text-slate-500 min-h-[2.5rem]">
        {{ tips[tipIdx] }}
      </div>
      <div class="text-xs text-slate-400">已用 {{ elapsed }}s</div>
      <el-progress
        :percentage="Math.min(elapsed * 3, 95)"
        :show-text="false"
        :indeterminate="elapsed > 30"
      />
      <div v-if="elapsed > 60" class="text-xs text-amber-600">
        这个模型可能比较慢，下次可以换一个云模型试试
      </div>
    </div>

    <div
      v-else-if="phase === 'preview' && screenplay"
      class="max-w-2xl w-full space-y-4"
    >
      <div class="text-2xl font-bold text-slate-800">📖 故事开始了</div>
      <div class="text-sm text-slate-500">
        类型：{{ screenplay.genre }} · 共 {{ screenplay.chapters.length }} 章
      </div>
      <div class="bg-white border border-slate-200 rounded p-6">
        <MarkdownView :source="screenplay.opening_hook" />
      </div>
      <div class="flex gap-2">
        <el-button type="primary" size="large" @click="startPlay">
          ▶ 开始跑团
        </el-button>
      </div>
    </div>

    <div v-else class="max-w-md w-full text-center space-y-3">
      <div class="text-2xl font-bold text-red-600">生成失败</div>
      <div class="text-sm text-slate-600 break-words">{{ errorMsg }}</div>
      <div class="flex gap-2 justify-center">
        <el-button type="primary" @click="retry">重试</el-button>
        <el-button @click="backToSessions">返回存档列表</el-button>
      </div>
    </div>
  </div>
</template>
