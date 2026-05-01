<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { sessionsApi, type LocationItem } from '@/api/sessions'

const route = useRoute()
const router = useRouter()
const sessionId = Number(route.params.id)

const locations = ref<LocationItem[]>([])
const loading = ref(true)

onMounted(async () => {
  try {
    locations.value = await sessionsApi.locations(sessionId)
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div class="p-4 max-w-2xl mx-auto">
    <div class="flex items-center gap-3 mb-4">
      <button @click="router.back()" class="text-slate-500 hover:text-slate-800">← 返回</button>
      <h2 class="text-xl font-bold">📍 场所记录</h2>
    </div>

    <div v-if="loading" class="text-slate-500">加载中…</div>

    <div v-else-if="locations.length === 0" class="text-slate-400 text-center py-12">
      尚未登记任何场所。GM 使用 &lt;location_enter&gt; 标签后将在此显示。
    </div>

    <div v-else class="space-y-3">
      <div
        v-for="loc in locations"
        :key="loc.id"
        class="border rounded-lg p-3"
        :class="loc.is_current ? 'border-blue-400 bg-blue-50' : 'border-slate-200'"
      >
        <div class="flex items-center gap-2">
          <span class="font-bold">{{ loc.name }}</span>
          <span v-if="loc.is_current" class="text-xs bg-blue-500 text-white px-2 py-0.5 rounded">当前</span>
        </div>
        <p v-if="loc.description" class="text-sm text-slate-600 mt-1">{{ loc.description }}</p>
        <p class="text-xs text-slate-400 mt-1">
          首次到访：第 {{ loc.first_visited_turn }} 回合
          <span v-if="loc.last_visited_turn !== loc.first_visited_turn">
            · 最近到访：第 {{ loc.last_visited_turn }} 回合
          </span>
        </p>
      </div>
    </div>
  </div>
</template>
