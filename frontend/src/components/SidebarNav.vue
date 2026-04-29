<script setup lang="ts">
import { RouterLink } from 'vue-router'

const items = [
  { to: '/sessions', label: '跑团', icon: '🎲' },
  { to: '/worlds', label: '世界观', icon: '🌍' },
  { to: '/characters', label: '角色', icon: '🧝' },
  { to: '/models', label: '模型', icon: '🤖' },
]
</script>

<template>
  <nav class="w-48 bg-slate-800 text-slate-100 h-full p-4 flex flex-col gap-1">
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
  </nav>
</template>
