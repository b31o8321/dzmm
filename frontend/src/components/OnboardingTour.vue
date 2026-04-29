<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { useAppStore } from '@/stores/app'

const appStore = useAppStore()
const router = useRouter()

const STEPS = [
  {
    title: '第 1 步：选模型',
    body: '点左上「模型」标签，添加一个 Ollama 本地模型（默认已经预置 qwen2.5:7b，点测试确认连通），或加你的云端 API。',
    targetRoute: '/models',
  },
  {
    title: '第 2 步：世界观和角色',
    body: '已经预置了 4 个世界观和角色（赛博朋克、克苏鲁怪谈、当代灵能、仙侠），可以直接用，也可以创建自己的。',
    targetRoute: '/worlds',
  },
  {
    title: '第 3 步：开新一局',
    body: '回到「跑团」页面，点「+ 新开一局」，选世界 + 角色 + GM 模型，然后开始跑团。',
    targetRoute: '/sessions',
  },
  {
    title: '第 4 步：跑起来',
    body:
      '在游戏页输入框写下你的第一个动作（比如「(开始游戏)」让 GM 给你写开场）。' +
      '顶部有「📒 NPC」「📜 编年史」「📖 任务日志」三个常用入口。' +
      '右上角的 🔊 是声音开关。',
    targetRoute: null as string | null,
  },
]

const current = computed(() => STEPS[appStore.tourStep - 1])
const total = STEPS.length

function next() {
  if (appStore.tourStep < total) {
    appStore.tourStep++
    const step = STEPS[appStore.tourStep - 1]
    if (step.targetRoute) router.push(step.targetRoute)
  } else {
    appStore.completeTour()
  }
}

function skip() {
  appStore.completeTour()
}
</script>

<template>
  <Teleport to="body">
    <div
      v-if="appStore.tourStep > 0 && current"
      class="fixed inset-0 bg-black/30 z-50 flex items-end md:items-center justify-center p-4 pointer-events-none"
    >
      <div class="bg-white rounded-xl shadow-2xl max-w-md w-full p-6 pointer-events-auto">
        <div class="text-xs text-slate-400 mb-1">
          引导 {{ appStore.tourStep }} / {{ total }}
        </div>
        <h3 class="text-lg font-bold text-slate-800 mb-2">{{ current.title }}</h3>
        <p class="text-sm text-slate-600 mb-4">{{ current.body }}</p>
        <div class="flex gap-2 justify-end">
          <el-button size="small" @click="skip">跳过</el-button>
          <el-button size="small" type="primary" @click="next">
            {{ appStore.tourStep < total ? '下一步' : '完成' }}
          </el-button>
        </div>
      </div>
    </div>
  </Teleport>
</template>
