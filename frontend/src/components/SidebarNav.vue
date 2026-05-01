<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { RouterLink } from 'vue-router'
import { fetchHealth } from '@/api/client'
import { useDebugStore } from '@/stores/debug'

const debug = useDebugStore()

const items = [
  { to: '/sessions', label: '跑团', icon: '🎲' },
  { to: '/worlds', label: '世界观', icon: '🌍' },
  { to: '/characters', label: '角色', icon: '🧝' },
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
    <span class="ml-auto self-center text-xs text-slate-400 px-2 shrink-0">
      v{{ frontendVersion }}<span
        v-if="backendVersion"
        :class="versionMismatch ? 'text-red-500 font-bold' : ''"
      > / 后端 v{{ backendVersion }}</span>
    </span>
  </nav>
</template>
