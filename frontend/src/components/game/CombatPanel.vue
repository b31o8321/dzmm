<script setup lang="ts">
interface Enemy { name: string; hp: number; max_hp?: number }

defineProps<{
  enemies: Enemy[]
  pcHp: number
  pcMaxHp: number
  ended: boolean
  winner?: string
  turnSpan: { start: number; end: number | null }
}>()
</script>

<template>
  <div
    class="my-3 border-2 rounded-lg overflow-hidden"
    :class="ended ? 'border-slate-300 bg-slate-50/50' : 'border-red-300 bg-red-50/30'"
  >
    <!-- Header -->
    <div
      class="px-3 py-2 flex items-center justify-between text-white"
      :class="ended ? 'bg-slate-500' : 'bg-red-500'"
    >
      <span class="font-bold">
        {{ ended ? '🏁 战斗结束' : '⚔️ 战斗中' }}
        <span v-if="ended && winner" class="text-xs ml-1 opacity-90">
          ({{
            winner === 'pc'
              ? '玩家胜'
              : winner === 'enemy'
              ? '敌方胜'
              : winner === 'flee'
              ? '撤退'
              : '平局'
          }})
        </span>
      </span>
      <span class="text-xs opacity-80">
        回合 {{ turnSpan.start }}{{ turnSpan.end != null ? ' - ' + turnSpan.end : '+' }}
      </span>
    </div>

    <!-- HP bars -->
    <div
      v-if="pcMaxHp > 0 || enemies.length"
      class="px-3 py-2 space-y-1.5 bg-white/60 border-b border-slate-200"
    >
      <!-- PC HP -->
      <div v-if="pcMaxHp > 0" class="flex items-center gap-2 text-sm">
        <span class="w-20 font-bold text-blue-700 truncate">PC</span>
        <div class="flex-1 h-2 bg-slate-200 rounded overflow-hidden">
          <div
            class="h-full bg-blue-500 transition-all duration-500"
            :style="{ width: `${Math.max(0, Math.min(100, (pcHp / Math.max(1, pcMaxHp)) * 100))}%` }"
          />
        </div>
        <span class="text-xs font-mono text-slate-600 w-14 text-right">{{ pcHp }} / {{ pcMaxHp }}</span>
      </div>
      <!-- Enemy HP bars -->
      <div v-for="(e, i) in enemies" :key="i" class="flex items-center gap-2 text-sm">
        <span class="w-20 font-bold text-red-700 truncate">{{ e.name }}</span>
        <div class="flex-1 h-2 bg-slate-200 rounded overflow-hidden">
          <div
            class="h-full bg-red-500 transition-all duration-500"
            :style="{
              width: `${Math.max(0, Math.min(100, (e.hp / Math.max(1, e.max_hp ?? e.hp ?? 1)) * 100))}%`,
            }"
          />
        </div>
        <span class="text-xs font-mono text-slate-600 w-14 text-right">
          {{ e.hp }} / {{ e.max_hp ?? '?' }}
        </span>
      </div>
    </div>

    <!-- Slot for the wrapped turn cards -->
    <div class="p-2 space-y-2">
      <slot />
    </div>
  </div>
</template>
