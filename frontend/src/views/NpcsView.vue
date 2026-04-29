<script setup lang="ts">
import { onMounted, ref, computed } from 'vue'
import { ElMessage } from 'element-plus'
import { sessionsApi, type Npc } from '@/api/sessions'
import NpcDetailDialog from '@/components/NpcDetailDialog.vue'

const props = defineProps<{ id: string }>()
const sessionId = Number(props.id)

const all = ref<Npc[]>([])
const loading = ref(false)
const dialogOpen = ref(false)
const selected = ref<Npc | null>(null)
const search = ref('')

async function refresh() {
  loading.value = true
  try {
    all.value = await sessionsApi.npcs(sessionId)
  } catch (e: any) {
    ElMessage.error(e.message ?? '加载失败')
  } finally {
    loading.value = false
  }
}

function open(n: Npc) {
  selected.value = n
  dialogOpen.value = true
}

function onUpdated(updated: Npc) {
  const idx = all.value.findIndex((n) => n.id === updated.id)
  if (idx >= 0) all.value[idx] = { ...updated }
  selected.value = updated
  // Re-sort: pinned first, then by last_seen_turn desc.
  all.value = [...all.value].sort((a, b) => {
    if (a.pinned !== b.pinned) return a.pinned ? -1 : 1
    return b.last_seen_turn - a.last_seen_turn
  })
}

const filtered = computed(() => {
  const q = search.value.trim().toLowerCase()
  if (!q) return all.value
  return all.value.filter((n) =>
    n.name.toLowerCase().includes(q) ||
    n.archetype.toLowerCase().includes(q) ||
    n.purpose.toLowerCase().includes(q),
  )
})

// Best single axis to display on the card preview: largest absolute affinity,
// fallback to favor.
function primaryAffinity(n: Npc): { axis: string; value: number } {
  const entries = Object.entries(n.affinity ?? {})
    .filter(([, v]) => typeof v === 'number')
  if (!entries.length) return { axis: '好感', value: n.favor }
  entries.sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]))
  return { axis: entries[0][0], value: entries[0][1] }
}

function barWidth(v: number): string {
  const clamped = Math.max(-20, Math.min(20, v))
  const pct = ((clamped + 20) / 40) * 100
  return `${pct}%`
}

function barColor(v: number): string {
  if (v >= 5) return 'bg-emerald-500'
  if (v > 0) return 'bg-emerald-300'
  if (v === 0) return 'bg-slate-300'
  if (v > -5) return 'bg-rose-300'
  return 'bg-rose-500'
}

onMounted(refresh)
</script>

<template>
  <div class="p-6 max-w-5xl mx-auto">
    <div class="flex items-center justify-between mb-4 flex-wrap gap-2">
      <h2 class="text-2xl font-bold">📒 NPC 名册</h2>
      <div class="flex items-center gap-3">
        <el-input
          v-model="search"
          size="small"
          placeholder="搜索 名字 / 原型 / 动机"
          style="width: 220px"
          clearable
        />
        <router-link :to="`/play/${props.id}`"
                     class="text-sm text-slate-500 hover:text-slate-800">
          ← 返回跑团
        </router-link>
      </div>
    </div>

    <div v-if="loading" class="text-slate-400 text-center py-8">加载中…</div>
    <div v-else-if="!filtered.length"
         class="text-slate-400 italic text-center py-8">
      尚无登场 NPC
    </div>

    <div v-else class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
      <article
        v-for="n in filtered"
        :key="n.id"
        class="bg-white border border-slate-200 rounded p-4 shadow-sm hover:shadow-md transition cursor-pointer"
        :class="n.pinned ? 'ring-1 ring-amber-300' : ''"
        @click="open(n)"
      >
        <div class="flex items-center gap-2 mb-1">
          <span v-if="n.pinned" class="text-amber-500" title="已置顶">📌</span>
          <h3 class="font-bold text-slate-800 truncate">{{ n.name }}</h3>
          <span class="text-xs text-slate-400 ml-auto shrink-0">
            T{{ n.last_seen_turn }}
          </span>
        </div>

        <div v-if="n.archetype"
             class="text-xs text-amber-700 bg-amber-50 inline-block px-2 py-0.5 rounded mb-2">
          {{ n.archetype }}
        </div>

        <p class="text-sm text-slate-600 mb-2 line-clamp-2">
          状态：{{ n.state || '未知' }}
        </p>

        <p v-if="n.purpose" class="text-xs text-slate-500 mb-2 line-clamp-2">
          🎯 {{ n.purpose }}
        </p>

        <div class="flex items-center gap-2 text-xs">
          <span class="w-12 text-slate-500 shrink-0">
            {{ primaryAffinity(n).axis }}
          </span>
          <div class="flex-1 bg-slate-100 rounded h-2 relative overflow-hidden">
            <div class="absolute top-0 bottom-0 left-1/2 w-px bg-slate-400/40"></div>
            <div
              class="absolute top-0 bottom-0"
              :class="barColor(primaryAffinity(n).value)"
              :style="{
                width: barWidth(primaryAffinity(n).value),
                left: primaryAffinity(n).value >= 0 ? '50%' : 'auto',
                right: primaryAffinity(n).value < 0 ? '50%' : 'auto',
              }"
            ></div>
          </div>
          <span class="font-mono text-slate-600 shrink-0 w-10 text-right">
            {{ primaryAffinity(n).value >= 0 ? '+' : '' }}{{ primaryAffinity(n).value }}
          </span>
        </div>
      </article>
    </div>

    <NpcDetailDialog
      v-model="dialogOpen"
      :session-id="sessionId"
      :npc="selected"
      @updated="onUpdated"
    />
  </div>
</template>
