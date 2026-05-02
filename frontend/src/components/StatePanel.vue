<script setup lang="ts">
import { computed } from 'vue'
import type { PCGoalItem } from '@/api/sessions'

const props = defineProps<{
  stats: Record<string, number>
  inventory: string[]
  npcs: { name: string; favor: number; state: string; pinned?: boolean; current_location?: string | null }[]
  dice: { skill: string; target: string; result: string }[]
  threads: { type: string; description: string; importance: number }[]
  goals?: PCGoalItem[]
  pcMood?: Record<string, number>
  currentLocation?: {
    name: string
    description: string
    items?: { name: string; description: string }[]
  } | null
}>()

const presentNpcs = computed(() =>
  props.currentLocation
    ? props.npcs.filter(
        (n) =>
          n.current_location &&
          n.current_location.toLowerCase() === props.currentLocation!.name.toLowerCase(),
      )
    : [],
)

const emit = defineEmits<{
  (e: 'select-npc', name: string): void
  (e: 'goal-status', goalId: number, status: 'active' | 'completed' | 'abandoned'): void
}>()

const STAT_TOOLTIPS: Record<string, string> = {
  hp: '生命值。归 0 → 倒地或死亡。低于 30% 时 GM 会描写虚弱状态。',
  HP: '生命值。归 0 → 倒地或死亡。低于 30% 时 GM 会描写虚弱状态。',
  sanity: '理智值。受恐怖、超自然、心理压力影响。低于 5 → 可能出现幻觉；归 0 → 短暂崩溃。Cthulhu 系跑团常见机制。',
  san: '理智值。受恐怖、超自然、心理压力影响。低于 5 → 可能出现幻觉；归 0 → 短暂崩溃。',
  mp: '法力值 / 内力。释放法术或特殊技能时消耗。',
  MP: '法力值 / 内力。释放法术或特殊技能时消耗。',
  力量: '决定攻击伤害、举重、推门、扛人等物理强度判定。',
  敏捷: '决定闪避、潜行、精细操作、轻功 / 跃越判定。',
  体质: '决定耐力、抗毒、抗疾病、长途奔波耐受度。',
  智力: '决定知识、推理、解谜、识别符文 / 装置判定。',
  感知: '决定洞察、察觉、识破谎言、追踪痕迹判定。',
  魅力: '决定说服、谈判、表演、影响 NPC 态度判定。',
  幸运: '决定意外事件、捡到东西、关键关头的好运判定。',
  耐力: '决定长跑、连续战斗、抵抗疲劳的能力。',
  意志: '决定抗心控、抗恐惧、抵御精神攻击的能力。',
}

function tooltipFor(key: string): string {
  return STAT_TOOLTIPS[key] || ''
}

function npcAvatarColor(name: string): string {
  let h = 0
  for (let i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) & 0xffff
  return `hsl(${h % 360}, 52%, 50%)`
}
</script>

<template>
  <aside class="w-80 bg-white border-l p-4 flex flex-col gap-4 overflow-auto">
    <div v-if="currentLocation" class="bg-blue-50 border border-blue-200 rounded px-3 py-2 text-sm mb-2">
      <span class="text-slate-500 text-xs">当前场所</span>
      <div class="font-bold text-blue-800">📍 {{ currentLocation.name }}</div>
      <div v-if="currentLocation.description" class="text-xs text-slate-500 mt-0.5">
        {{ currentLocation.description }}
      </div>
      <div v-if="presentNpcs.length" class="text-xs text-slate-600 mt-1">
        在场：{{ presentNpcs.map((n) => n.name).join('、') }}
      </div>
      <div v-if="currentLocation.items?.length" class="text-xs text-slate-500 mt-1">
        <span class="font-medium">物品：</span>{{ currentLocation.items.map((i) => i.name).join('、') }}
      </div>
    </div>
    <section>
      <h3 class="font-bold text-slate-700 mb-2">角色状态</h3>
      <div class="space-y-1 text-sm">
        <el-tooltip
          v-for="(v, k) in stats"
          :key="k"
          :content="tooltipFor(String(k))"
          :disabled="!tooltipFor(String(k))"
          placement="left"
        >
          <div
            class="flex justify-between"
            :class="tooltipFor(String(k)) ? 'cursor-help' : ''"
          >
            <span class="text-slate-500">{{ k }}</span>
            <span class="font-mono">{{ v }}</span>
          </div>
        </el-tooltip>
        <div v-if="!Object.keys(stats).length" class="text-slate-400 italic">尚未初始化</div>
      </div>
    </section>

    <section v-if="pcMood && Object.keys(pcMood).length">
      <h3 class="font-bold text-slate-700 mb-2">心情</h3>
      <div class="flex flex-wrap gap-1.5">
        <span
          v-for="(v, k) in pcMood"
          :key="k"
          class="inline-flex items-center gap-1 px-2 py-0.5 bg-violet-50 text-violet-700 rounded text-xs"
        >
          {{ k }}<span class="font-mono opacity-60">{{ v }}</span>
        </span>
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
            class="text-left hover:underline hover:text-amber-700 truncate flex items-center gap-1.5"
            @click="emit('select-npc', n.name)"
            :title="`查看 ${n.name} 的详情`"
          >
            <span
              class="inline-flex items-center justify-center w-5 h-5 rounded-full text-white text-xs font-bold shrink-0 select-none"
              :style="{ backgroundColor: npcAvatarColor(n.name) }"
            >{{ n.name[0] }}</span>
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
