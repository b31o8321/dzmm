<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { sessionsApi, type RelationItem } from '@/api/sessions'
import { ElMessage } from 'element-plus'

const props = defineProps<{ id: string }>()
const sessionId = Number(props.id)
const items = ref<RelationItem[]>([])
const loading = ref(false)

async function refresh() {
  loading.value = true
  try {
    items.value = await sessionsApi.relations(sessionId)
  } catch (e: any) {
    ElMessage.error(e.message ?? '加载失败')
  } finally {
    loading.value = false
  }
}
onMounted(refresh)
</script>

<template>
  <div class="p-4 md:p-6 max-w-3xl mx-auto">
    <div class="flex items-center justify-between mb-4 flex-wrap gap-2">
      <h2 class="text-2xl font-bold">🔗 NPC 关系网</h2>
      <router-link :to="`/play/${props.id}`"
                   class="text-sm text-slate-500 hover:text-slate-800">
        ← 返回跑团
      </router-link>
    </div>

    <div v-if="loading" class="text-slate-400 text-center py-12">加载中…</div>
    <div v-else-if="!items.length"
         class="text-slate-400 italic text-center py-12">
      还没有 NPC 关系被记录。<br />
      <span class="text-xs">GM 用 &lt;npc_relation&gt; 标签揭示关系时会自动出现在这里。</span>
    </div>
    <ul v-else class="space-y-2">
      <li v-for="r in items" :key="r.id"
          class="bg-white border border-slate-200 rounded p-4 shadow-sm">
        <div class="flex items-center gap-2 mb-1 flex-wrap">
          <span class="font-bold">{{ r.npc_a }}</span>
          <span class="text-slate-400">↔</span>
          <span class="font-bold">{{ r.npc_b }}</span>
          <span class="ml-2 text-xs px-2 py-0.5 bg-amber-100 text-amber-800 rounded">
            {{ r.kind }}
          </span>
          <span class="ml-auto text-xs text-slate-400">
            第 {{ r.introduced_turn }} 回合
          </span>
        </div>
        <p v-if="r.description" class="text-sm text-slate-600">
          {{ r.description }}
        </p>
      </li>
    </ul>
  </div>
</template>
