<script setup lang="ts">
import { onMounted, ref, computed } from 'vue'
import { ElMessage } from 'element-plus'
import { sessionsApi, type TimelineItem, type EraItem } from '@/api/sessions'

const props = defineProps<{ id: string }>()
const sessionId = Number(props.id)

const timeline = ref<TimelineItem[]>([])
const eras = ref<EraItem[]>([])
const search = ref('')
const loading = ref(false)

interface Group {
  era: EraItem | null  // null = 序幕（在第一个 era 之前）
  events: TimelineItem[]
}

const groups = computed<Group[]>(() => {
  const filtered = search.value.trim()
    ? timeline.value.filter((t) =>
        t.event_text.toLowerCase().includes(search.value.toLowerCase()),
      )
    : timeline.value

  if (!eras.value.length) {
    return [{ era: null, events: filtered }]
  }

  const sortedEras = [...eras.value].sort((a, b) => a.started_turn - b.started_turn)
  const result: Group[] = []
  for (let i = -1; i < sortedEras.length; i++) {
    const startTurn = i === -1 ? -Infinity : sortedEras[i].started_turn
    const endTurn = i + 1 < sortedEras.length
      ? sortedEras[i + 1].started_turn
      : Infinity
    const events = filtered.filter((t) => t.turn >= startTurn && t.turn < endTurn)
    if (events.length || i >= 0) {
      result.push({
        era: i === -1 ? null : sortedEras[i],
        events,
      })
    }
  }
  return result
})

async function refresh() {
  loading.value = true
  try {
    const [t, e] = await Promise.all([
      sessionsApi.timeline(sessionId),
      sessionsApi.eras(sessionId),
    ])
    timeline.value = t
    eras.value = e
  } catch (err: any) {
    ElMessage.error(err.message ?? '加载失败')
  } finally {
    loading.value = false
  }
}

onMounted(refresh)
</script>

<template>
  <div class="p-4 md:p-6 max-w-4xl mx-auto">
    <div class="flex items-center justify-between mb-4 flex-wrap gap-2">
      <h2 class="text-2xl font-bold">📜 编年史</h2>
      <router-link :to="`/play/${id}`"
                   class="text-sm text-slate-500 hover:text-slate-800">
        ← 返回跑团
      </router-link>
    </div>

    <el-input v-model="search" placeholder="搜索事件…" clearable
              class="mb-4 max-w-md" />

    <div v-if="loading" class="text-slate-400 text-center py-12">加载中…</div>
    <div v-else-if="!timeline.length"
         class="text-slate-400 italic text-center py-12">
      还没有关键事件被记录。<br />
      <span class="text-xs">事件会在跑团达到 10+ 回合并触发摘要压缩后自动汇总。</span>
    </div>

    <div v-else class="space-y-8">
      <section v-for="(g, gi) in groups" :key="gi">
        <header class="border-b-2 border-amber-400 pb-2 mb-4">
          <h3 class="text-xl font-bold text-amber-800">
            <span v-if="g.era">第 {{ gi + 1 }} 卷 · {{ g.era.name }}</span>
            <span v-else class="text-slate-700">序幕</span>
          </h3>
          <p v-if="g.era?.description" class="text-sm text-slate-500 mt-1">
            {{ g.era.description }}
          </p>
          <p v-if="g.era" class="text-xs text-slate-400 mt-0.5">
            起始：第 {{ g.era.started_turn }} 回合
          </p>
        </header>

        <div v-if="!g.events.length" class="text-xs text-slate-400 italic pl-4">
          这一卷暂无关键事件
        </div>
        <ol v-else class="space-y-3">
          <li v-for="t in g.events" :key="t.id"
              class="flex gap-3 items-start border-l-4 pl-3 py-1"
              :class="t.importance === 3 ? 'border-rose-400'
                    : t.importance === 2 ? 'border-amber-400'
                    : 'border-slate-200'">
            <div class="text-xs text-slate-400 font-mono w-16 shrink-0 pt-0.5">
              第 {{ t.turn }} 回合
            </div>
            <div class="flex-1">
              <div class="text-amber-500 mb-0.5 text-xs">
                {{ '★'.repeat(t.importance) }}
              </div>
              <div class="text-sm text-slate-800">{{ t.event_text }}</div>
            </div>
          </li>
        </ol>
      </section>
    </div>
  </div>
</template>
