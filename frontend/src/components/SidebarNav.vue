<script setup lang="ts">
import { RouterLink } from 'vue-router'

const items = [
  { to: '/sessions', label: '跑团', icon: '🎲' },
  { to: '/worlds', label: '世界观', icon: '🌍' },
  { to: '/characters', label: '角色', icon: '🧝' },
  { to: '/models', label: '模型', icon: '🤖' },
]

const version = __APP_VERSION__
</script>

<template>
  <!-- Desktop: vertical sidebar, persistent -->
  <nav class="hidden md:flex w-48 bg-slate-800 text-slate-100 h-full p-4 flex-col gap-1 shrink-0">
    <div class="text-xl font-bold mb-6 px-2">dzmm</div>
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
        to="/help"
        class="block px-3 py-2 rounded text-sm text-slate-300 hover:bg-slate-700 transition"
        active-class="bg-slate-700"
      >
        <span class="mr-2">📖</span>说明 / 帮助
      </RouterLink>
      <div class="text-xs text-slate-500 mt-2 px-3">v{{ version }}</div>
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
      to="/help"
      class="px-3 py-2 rounded hover:bg-slate-700 transition shrink-0 text-sm whitespace-nowrap"
      active-class="bg-slate-700"
    >
      <span class="mr-1">📖</span>说明
    </RouterLink>
    <span class="ml-auto self-center text-xs text-slate-500 px-2 shrink-0">v{{ version }}</span>
  </nav>
</template>
