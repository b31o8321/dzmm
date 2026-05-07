<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { ElProgress, ElTag } from 'element-plus'
import { eventDescription, type Screenplay } from '@/api/screenplay'

const props = defineProps<{
  screenplay: Screenplay | null
  sessionId: number
}>()

const router = useRouter()

const currentChapter = computed(() => {
  if (!props.screenplay) return null
  const idx = Math.max(
    0,
    Math.min(props.screenplay.current_chapter - 1, props.screenplay.chapters.length - 1),
  )
  return props.screenplay.chapters[idx] ?? null
})

const progressPct = computed(() => {
  if (!props.screenplay) return 0
  const total = props.screenplay.chapters.reduce(
    (sum, ch) => sum + ch.main_events.length,
    0,
  )
  if (total === 0) return 0
  const done = props.screenplay.completed_events.filter((c) => c.type === 'main').length
  return Math.round((done / total) * 100)
})

function isEventDone(eventIdx: number, type: 'main' | 'optional'): boolean {
  if (!props.screenplay) return false
  return props.screenplay.completed_events.some(
    (c) =>
      c.chapter === props.screenplay!.current_chapter &&
      c.event_idx === eventIdx &&
      c.type === type,
  )
}

function openFullView() {
  router.push(`/play/${props.sessionId}/screenplay`)
}
</script>

<template>
  <div v-if="screenplay" class="bg-white border border-slate-200 rounded p-3 text-xs space-y-2">
    <button
      type="button"
      class="w-full text-left"
      title="查看完整剧本"
      @click="openFullView"
    >
      <div class="flex items-center justify-between">
        <span class="font-bold text-slate-700">📜 剧本进度</span>
        <span class="text-slate-400 hover:text-slate-600">›</span>
      </div>
      <div class="text-slate-500 mt-0.5">
        {{ screenplay.genre }} · 第 {{ screenplay.current_chapter }} / {{ screenplay.chapters.length }} 章
        <span v-if="screenplay.status === 'concluded'" class="ml-1 text-blue-600">✓ 已完结</span>
      </div>
    </button>

    <el-progress :percentage="progressPct" :show-text="false" :stroke-width="6" />

    <div v-if="currentChapter" class="space-y-1.5">
      <div class="font-medium text-slate-700 truncate" :title="currentChapter.title">
        {{ currentChapter.title }}
      </div>
      <ul v-if="currentChapter.main_events.length" class="space-y-0.5">
        <li
          v-for="(ev, i) in currentChapter.main_events"
          :key="i"
          class="flex items-start gap-1 leading-tight"
        >
          <el-tag
            v-if="isEventDone(i, 'main')"
            type="success"
            size="small"
            effect="plain"
          >✓</el-tag>
          <el-tag v-else type="warning" size="small" effect="plain">…</el-tag>
          <span class="text-slate-600 flex-1 min-w-0">{{ eventDescription(ev) }}</span>
        </li>
      </ul>
    </div>
  </div>
</template>
