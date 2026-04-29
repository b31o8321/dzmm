<script setup lang="ts">
import type { PCGoalItem } from '@/api/sessions'

defineProps<{
  stats: Record<string, number>
  inventory: string[]
  npcs: { name: string; favor: number; state: string; pinned?: boolean }[]
  dice: { skill: string; target: string; result: string }[]
  threads: { type: string; description: string; importance: number }[]
  goals?: PCGoalItem[]
}>()

const emit = defineEmits<{
  (e: 'select-npc', name: string): void
  (e: 'goal-status', goalId: number, status: 'active' | 'completed' | 'abandoned'): void
}>()
</script>

<template>
  <aside class="w-80 bg-white border-l p-4 flex flex-col gap-4 overflow-auto">
    <section>
      <h3 class="font-bold text-slate-700 mb-2">角色状态</h3>
      <div class="space-y-1 text-sm">
        <div v-for="(v, k) in stats" :key="k" class="flex justify-between">
          <span class="text-slate-500">{{ k }}</span>
          <span class="font-mono">{{ v }}</span>
        </div>
        <div v-if="!Object.keys(stats).length" class="text-slate-400 italic">尚未初始化</div>
      </div>
    </section>

    <section>
      <h3 class="font-bold text-slate-700 mb-2">背包</h3>
      <ul class="space-y-1 text-sm">
        <li v-for="item in inventory" :key="item">· {{ item }}</li>
        <li v-if="!inventory.length" class="text-slate-400 italic">空</li>
      </ul>
    </section>

    <section v-if="dice.length">
      <h3 class="font-bold text-slate-700 mb-2">最近骰点</h3>
      <ul class="space-y-1 text-xs font-mono">
        <li v-for="(d, i) in dice" :key="i" class="text-slate-600">
          🎲 {{ d.skill }} (DC {{ d.target }}) → {{ d.result }}
        </li>
      </ul>
    </section>

    <section v-if="threads.length">
      <h3 class="font-bold text-slate-700 mb-2">剧情线</h3>
      <ul class="space-y-1 text-sm">
        <li v-for="(t, i) in threads" :key="i">
          <span class="text-amber-600 mr-1">{{ '★'.repeat(t.importance) }}</span>
          <span class="text-xs text-slate-500 mr-1">[{{ t.type }}]</span>
          {{ t.description }}
        </li>
      </ul>
    </section>

    <section v-if="goals && goals.length">
      <h3 class="font-bold text-slate-700 mb-2">🎯 我的目标</h3>
      <ul class="space-y-2 text-sm">
        <li v-for="g in goals.filter(x => x.status === 'active')" :key="g.id"
            class="flex items-start gap-2">
          <span class="text-amber-500 text-xs pt-0.5 shrink-0">
            {{ g.priority === 'high' ? '★★★'
              : g.priority === 'low' ? '★' : '★★' }}
          </span>
          <span class="flex-1">{{ g.description }}</span>
          <button type="button" class="text-xs text-slate-400 hover:text-emerald-500"
                  title="标记完成"
                  @click="emit('goal-status', g.id, 'completed')">✓</button>
        </li>
      </ul>
      <details v-if="goals.some(g => g.status !== 'active')" class="mt-2">
        <summary class="text-xs text-slate-400 cursor-pointer">
          已完成 / 已放弃 ({{ goals.filter(g => g.status !== 'active').length }})
        </summary>
        <ul class="mt-1 space-y-1 text-xs text-slate-500 pl-4">
          <li v-for="g in goals.filter(x => x.status !== 'active')" :key="g.id"
              class="flex items-start gap-2">
            <span class="line-through opacity-60 flex-1">{{ g.description }}</span>
            <span class="text-slate-400">
              {{ g.status === 'completed' ? '✓' : '✕' }}
            </span>
          </li>
        </ul>
      </details>
    </section>

    <section>
      <h3 class="font-bold text-slate-700 mb-2">NPC 关系</h3>
      <ul class="space-y-1 text-sm">
        <li v-for="n in npcs" :key="n.name" class="flex justify-between items-center gap-2">
          <button
            type="button"
            class="text-left hover:underline hover:text-amber-700 truncate flex items-center gap-1"
            @click="emit('select-npc', n.name)"
            :title="`查看 ${n.name} 的详情`"
          >
            <span v-if="n.pinned" class="text-amber-500" title="已置顶">📌</span>
            <span>{{ n.name }}</span>
          </button>
          <span class="text-slate-500 shrink-0">
            <span class="font-mono mr-1">{{ n.favor >= 0 ? '+' : '' }}{{ n.favor }}</span>
            <span class="text-xs">{{ n.state }}</span>
          </span>
        </li>
        <li v-if="!npcs.length" class="text-slate-400 italic">尚无登场 NPC</li>
      </ul>
    </section>
  </aside>
</template>
