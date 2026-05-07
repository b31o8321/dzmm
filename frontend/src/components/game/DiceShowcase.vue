<script setup lang="ts">
import { computed } from 'vue'
import D20Roll from './D20Roll.vue'
import { useDiceAnimation } from '@/composables/useDiceAnimation'
import type { DiceEvent } from '@/api/types'

const props = defineProps<{ dice: DiceEvent }>()

const { stage } = useDiceAnimation(props.dice.reactions.length)

const CATEGORY_META: Record<string, { icon: string; label: string }> = {
  combat:     { icon: '⚔️', label: '战斗' },
  stealth:    { icon: '🥷', label: '潜行' },
  persuasion: { icon: '💬', label: '社交' },
  arcane:     { icon: '✨', label: '法术' },
  athletics:  { icon: '💪', label: '体能' },
  perception: { icon: '👁️', label: '感知' },
  knowledge:  { icon: '📚', label: '学识' },
  generic:    { icon: '🎲', label: '检定' },
}

const OUTCOME_META: Record<string, { label: string; accent: string; glow: string }> = {
  crit_success: {
    label: '大成功',
    accent: 'bg-yellow-50 border-yellow-400 text-yellow-800',
    glow: 'shadow-[0_0_20px_rgba(234,179,8,0.4)]',
  },
  success: {
    label: '成功',
    accent: 'bg-green-50 border-green-400 text-green-700',
    glow: '',
  },
  fail: {
    label: '失败',
    accent: 'bg-slate-100 border-slate-400 text-slate-600',
    glow: '',
  },
  crit_fail: {
    label: '大失败',
    accent: 'bg-red-50 border-red-400 text-red-700',
    glow: 'shadow-[0_0_15px_rgba(239,68,68,0.4)]',
  },
}

const MOOD_ICON: Record<string, string> = {
  '无察觉': '😶', '平静': '🙂', '警觉': '👀', '愤怒': '😠',
  '惊讶': '😲', '嘲讽': '😏', '恐惧': '😨', '敬佩': '🥺',
  '怀疑': '🤨', '好奇': '🤔',
}

const cat = computed(() => CATEGORY_META[props.dice.category] ?? CATEGORY_META.generic)
const out = computed(() => OUTCOME_META[props.dice.outcome] ?? OUTCOME_META.success)
const sumExpr = computed(() => {
  const m = props.dice.modifier
  if (m === 0) return `${props.dice.pc_roll}`
  return `${props.dice.pc_roll}${m >= 0 ? '+' : ''}${m}`
})
const sumValue = computed(() => props.dice.pc_roll + props.dice.modifier)

function moodIcon(m: string) { return MOOD_ICON[m] || '' }
</script>

<template>
  <div
    class="my-3 border rounded-lg overflow-hidden transition-all duration-300"
    :class="[out.accent, out.glow]"
  >
    <!-- Mechanics row -->
    <div class="flex items-center justify-between px-3 py-2 border-b border-current/20">
      <div class="flex items-center gap-2">
        <D20Roll :rolling="stage.rolling" :value="stage.resultShown ? sumValue : null" />
        <span class="text-base">{{ cat.icon }}</span>
        <span class="font-bold text-sm">{{ cat.label }}检定</span>
      </div>
      <div class="flex items-center gap-3 text-xs">
        <span class="font-mono text-slate-600">
          d20: <span :class="{ 'opacity-30': stage.rolling }">{{ stage.resultShown ? sumExpr : '?' }}</span>
          <template v-if="stage.resultShown && dice.modifier !== 0">
            = <strong>{{ sumValue }}</strong>
          </template>
        </span>
        <span class="text-slate-400">vs DC {{ dice.dc }}</span>
        <span v-if="stage.resultShown" class="font-bold">{{ out.label }}</span>
      </div>
    </div>

    <!-- Scene -->
    <div
      v-if="dice.scene_text && stage.sceneShown"
      class="px-3 py-2.5 bg-white/50 border-b border-current/10 text-sm leading-relaxed text-slate-700 whitespace-pre-line"
    >
      {{ dice.scene_text }}
    </div>
    <div
      v-else-if="!dice.scene_text && dice.description && stage.sceneShown"
      class="px-3 py-2 bg-white/40 text-sm text-slate-600 italic"
    >
      {{ dice.description }}
    </div>

    <!-- Reactions -->
    <div v-if="dice.reactions.length" class="bg-white/30">
      <div
        v-for="(r, i) in dice.reactions" :key="i"
        v-show="i < stage.reactionsShown"
        class="px-3 py-1.5 border-t border-current/10 text-sm transition-opacity"
      >
        <span class="font-bold text-slate-700">
          {{ moodIcon(r.mood) }} {{ r.speaker
          }}<span v-if="r.mood" class="text-slate-400 font-normal">（{{ r.mood }}）</span>：
        </span>
        <span class="text-slate-600 ml-1">{{ r.text }}</span>
      </div>
    </div>
  </div>
</template>
