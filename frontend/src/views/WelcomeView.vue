<script setup lang="ts">
import { useRouter } from 'vue-router'
import { useAppStore } from '@/stores/app'

const router = useRouter()
const appStore = useAppStore()

function startTour() {
  appStore.tourStep = 1
  router.push('/sessions')
}

function skipAll() {
  appStore.completeTour()
  router.push('/sessions')
}
</script>

<template>
  <div class="h-full flex items-center justify-center bg-gradient-to-br from-slate-100 to-slate-200 p-6">
    <div class="max-w-xl bg-white rounded-2xl shadow-2xl p-8 md:p-12 space-y-6">
      <div class="text-center space-y-2">
        <div class="text-5xl mb-2">🎲</div>
        <h1 class="text-3xl font-bold text-slate-800">欢迎来到 dzmm</h1>
        <p class="text-slate-500">由本地 AI 担任 GM 的文字跑团游戏</p>
      </div>

      <div class="space-y-3 text-sm text-slate-700">
        <p>
          <strong class="text-slate-800">dzmm</strong> 让你随时随地开启一场私人 TRPG 跑团：
          自由设定世界观，创建角色，和 AI 主持人推进剧情。所有数据都在你自己电脑上。
        </p>
        <ul class="space-y-1 list-disc pl-5">
          <li>📜 完整的<strong>编年史</strong>记录，回看每一段冒险</li>
          <li>🧝 NPC <strong>多维好感+人设原型</strong>，攻略目标真的会"在乎"</li>
          <li>⭐ 角色 <strong>XP 升级</strong>系统，长线跑团有获得感</li>
          <li>🎵 风格化 BGM 和音效，沉浸式体验</li>
          <li>📱 支持手机访问（同 WiFi 下用浏览器进）</li>
        </ul>
      </div>

      <div class="flex flex-col sm:flex-row gap-3 pt-4">
        <el-button type="primary" size="large" class="flex-1" @click="startTour">
          🚀 开始 4 分钟引导
        </el-button>
        <el-button size="large" class="flex-1" @click="skipAll">
          直接进主界面
        </el-button>
      </div>

      <div class="text-xs text-slate-400 text-center pt-2">
        随时可以从主界面右上角的 ❓ 重新查看引导
      </div>
    </div>
  </div>
</template>
