<script setup lang="ts">
import { onMounted, ref, computed } from 'vue'
import { ElMessage } from 'element-plus'
import { sessionsApi, type PlotThreadItem } from '@/api/sessions'

const props = defineProps<{ id: string }>()
const sessionId = Number(props.id)

const all = ref<PlotThreadItem[]>([])
const loading = ref(false)
const tab = ref<'active' | 'resolved'>('active')

const active = computed(() => all.value.filter((t) => t.status === 'active'))
const resolved = computed(() => all.value.filter((t) => t.status === 'resolved'))

async function refresh() {
  loading.value = true
  try {
    all.value = await sessionsApi.threads(sessionId)
  } catch (e: any) {
    ElMessage.error(e.message ?? '加载失败')
  } finally {
    loading.value = false
  }
}

onMounted(refresh)
</script>

<template>
  <div class="p-6 max-w-3xl mx-auto">
    <div class="flex items-center justify-between mb-4">
      <h2 class="text-2xl font-bold">📖 任务日志</h2>
      <router-link :to="`/play/${props.id}`"
                   class="text-sm text-slate-500 hover:text-slate-800">
        ← 返回跑团
      </router-link>
    </div>

    <el-tabs v-model="tab">
      <el-tab-pane :label="`进行中 (${active.length})`" name="active">
        <div v-if="loading" class="text-slate-400 text-center py-8">加载中…</div>
        <div v-else-if="!active.length" class="text-slate-400 italic text-center py-8">
          暂无进行中的剧情线
        </div>
        <article v-for="t in active" :key="t.id"
                 class="bg-white border border-slate-200 rounded p-4 mb-3 shadow-sm">
          <div class="flex items-center gap-2 mb-2">
            <span class="text-amber-500">{{ '★'.repeat(t.importance) }}</span>
            <span class="text-xs text-slate-500 px-2 py-0.5 bg-slate-100 rounded">
              {{ t.type }}
            </span>
            <span class="text-xs text-slate-400 ml-auto">
              第 {{ t.introduced_turn }} 回合引入
            </span>
          </div>
          <p class="text-sm text-slate-800">{{ t.description }}</p>
        </article>
      </el-tab-pane>

      <el-tab-pane :label="`已解决 (${resolved.length})`" name="resolved">
        <div v-if="!resolved.length"
             class="text-slate-400 italic text-center py-8">
          暂无已解决的剧情线
        </div>
        <article v-for="t in resolved" :key="t.id"
                 class="bg-white border border-slate-200 rounded p-4 mb-3 shadow-sm opacity-75">
          <div class="flex items-center gap-2 mb-2">
            <span class="text-amber-500">{{ '★'.repeat(t.importance) }}</span>
            <span class="text-xs text-slate-500 px-2 py-0.5 bg-slate-100 rounded">
              {{ t.type }}
            </span>
            <span class="text-xs text-emerald-600 ml-auto">✓ 已解决</span>
          </div>
          <p class="text-sm text-slate-800 mb-2">{{ t.description }}</p>
          <p v-if="t.resolution"
             class="text-sm text-emerald-700 border-l-2 border-emerald-400 pl-3 italic">
            {{ t.resolution }}
          </p>
        </article>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>
