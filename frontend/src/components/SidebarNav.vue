<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { RouterLink } from 'vue-router'
import { fetchHealth } from '@/api/client'
import { useDebugStore } from '@/stores/debug'
import { useAppStore } from '@/stores/app'
import { useAudio } from '@/composables/useAudio'
import { useRouter } from 'vue-router'

const debug = useDebugStore()
const appStore = useAppStore()
const audio = useAudio()
const router = useRouter()

function toggleMute() {
  audio.setMuted(!appStore.muted)
}

function restartTour() {
  appStore.restartTour()
  router.push('/welcome')
}

const items = [
  { to: '/sessions', label: '跑团', icon: '🎲' },
  { to: '/worlds', label: '世界观', icon: '🌍' },
  { to: '/models', label: '模型', icon: '🤖' },
]

const frontendVersion = __APP_VERSION__
const backendVersion = ref<string | null>(null)

onMounted(async () => {
  const h = await fetchHealth()
  backendVersion.value = h?.version ?? null
})

const versionMismatch = computed(() => {
  if (!backendVersion.value) return false
  return backendVersion.value !== frontendVersion
})
</script>

<template>
  <!-- Desktop: vertical sidebar, persistent -->
  <nav class="hidden md:flex w-48 bg-slate-800 text-slate-100 h-full p-4 flex-col gap-1 shrink-0">
    <div class="text-xl font-bold mb-6 px-2">dzmm</div>
    <div
      v-if="debug.enabled"
      class="bg-red-700 text-white text-xs px-2 py-1 rounded mb-2 text-center font-bold"
    >
      🐛 DEBUG MODE
    </div>
    <RouterLink
      v-for="i in items"
      :key="i.to"
      :to="i.to"
      class="px-3 py-2 rounded hover:bg-slate-700 transition"
      active-class="bg-slate-700"
    >
      <span class="mr-2">{{ i.icon }}</span>{{ i.label }}
    </RouterLink>
    <div class="mt-auto pt-4 border-t border-slate-700">
      <RouterLink
        v-if="debug.enabled"
        to="/debug"
        class="block px-3 py-2 rounded text-sm text-red-300 hover:bg-slate-700 transition"
        active-class="bg-slate-700"
      >
        <span class="mr-2">🐛</span>调试
      </RouterLink>
      <RouterLink
        to="/settings"
        class="block px-3 py-2 rounded text-sm text-slate-300 hover:bg-slate-700 transition"
        active-class="bg-slate-700"
      >
        <span class="mr-2">⚙️</span>设置
      </RouterLink>
      <RouterLink
        to="/help"
        class="block px-3 py-2 rounded text-sm text-slate-300 hover:bg-slate-700 transition"
        active-class="bg-slate-700"
      >
        <span class="mr-2">📖</span>说明 / 帮助
      </RouterLink>
      <div class="flex gap-1 px-3 mt-1">
        <button type="button"
          class="text-slate-400 hover:text-slate-200 text-sm w-7 h-7 flex items-center justify-center rounded hover:bg-slate-700 transition"
          :title="appStore.muted ? '取消静音' : '静音'"
          @click="toggleMute">{{ appStore.muted ? '🔇' : '🔊' }}</button>
        <button type="button"
          class="text-slate-400 hover:text-slate-200 text-sm w-7 h-7 flex items-center justify-center rounded hover:bg-slate-700 transition"
          title="重新查看引导"
          @click="restartTour">❓</button>
      </div>
      <div class="text-xs text-slate-400 mt-2 px-3">
        v{{ frontendVersion }}
        <span
          v-if="backendVersion"
          :class="versionMismatch ? 'text-red-500 font-bold' : ''"
        >
          / 后端 v{{ backendVersion }}
        </span>
      </div>
      <div v-if="versionMismatch" class="text-xs text-red-500 mt-1 px-3">
        ⚠️ 前后端版本不一致，请重打包：<code>python packaging/build.py</code>
      </div>
    </div>
  </nav>

  <!-- Mobile: horizontal tab bar at top of layout -->
  <nav class="flex md:hidden w-full bg-slate-800 text-slate-100 px-2 py-1 gap-1 overflow-x-auto shrink-0">
    <RouterLink
      v-for="i in items"
      :key="i.to"
      :to="i.to"
      class="px-3 py-2 rounded hover:bg-slate-700 transition shrink-0 text-sm whitespace-nowrap"
      active-class="bg-slate-700"
    >
      <span class="mr-1">{{ i.icon }}</span>{{ i.label }}
    </RouterLink>
    <RouterLink
      v-if="debug.enabled"
      to="/debug"
      class="px-3 py-2 rounded hover:bg-slate-700 transition shrink-0 text-sm whitespace-nowrap text-red-300"
      active-class="bg-slate-700"
    >
      <span class="mr-1">🐛</span>调试
    </RouterLink>
    <RouterLink
      to="/settings"
      class="px-3 py-2 rounded hover:bg-slate-700 transition shrink-0 text-sm whitespace-nowrap"
      active-class="bg-slate-700"
    >
      <span class="mr-1">⚙️</span>设置
    </RouterLink>
    <RouterLink
      to="/help"
      class="px-3 py-2 rounded hover:bg-slate-700 transition shrink-0 text-sm whitespace-nowrap"
      active-class="bg-slate-700"
    >
      <span class="mr-1">📖</span>说明
    </RouterLink>
    <div class="ml-auto flex items-center gap-1 shrink-0 px-1">
      <button type="button"
        class="text-slate-300 hover:text-white text-sm w-7 h-7 flex items-center justify-center rounded hover:bg-slate-700 transition shrink-0"
        :title="appStore.muted ? '取消静音' : '静音'"
        @click="toggleMute">{{ appStore.muted ? '🔇' : '🔊' }}</button>
      <button type="button"
        class="text-slate-300 hover:text-white text-sm w-7 h-7 flex items-center justify-center rounded hover:bg-slate-700 transition shrink-0"
        title="重新查看引导"
        @click="restartTour">❓</button>
      <span class="text-xs text-slate-400 px-1">
        v{{ frontendVersion }}<span
          v-if="backendVersion"
          :class="versionMismatch ? 'text-red-500 font-bold' : ''"
        > / 后端 v{{ backendVersion }}</span>
      </span>
    </div>
  </nav>
</template>
