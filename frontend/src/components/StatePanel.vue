<script setup lang="ts">
defineProps<{
  stats: Record<string, number>
  inventory: string[]
  npcs: { name: string; favor: number; state: string }[]
  dice: { skill: string; target: string; result: string }[]
  threads: { type: string; description: string; importance: number }[]
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

    <section>
      <h3 class="font-bold text-slate-700 mb-2">NPC 关系</h3>
      <ul class="space-y-1 text-sm">
        <li v-for="n in npcs" :key="n.name" class="flex justify-between">
          <span>{{ n.name }}</span>
          <span class="text-slate-500">
            <span class="font-mono mr-1">{{ n.favor >= 0 ? '+' : '' }}{{ n.favor }}</span>
            <span class="text-xs">{{ n.state }}</span>
          </span>
        </li>
        <li v-if="!npcs.length" class="text-slate-400 italic">尚无登场 NPC</li>
      </ul>
    </section>
  </aside>
</template>
