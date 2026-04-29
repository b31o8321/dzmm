<script setup lang="ts">
import { computed } from 'vue'
import { backendOrigin } from '@/api/client'

const props = defineProps<{
  characterId: number | null | undefined
  hasPortrait: boolean
  fallbackName?: string
  size?: number  // px, default 48
}>()

const sz = computed(() => props.size ?? 48)
const url = computed(() =>
  props.hasPortrait && props.characterId
    ? `${backendOrigin}/characters/${props.characterId}/portrait`
    : null,
)
const initial = computed(() => (props.fallbackName ?? '?').slice(0, 1))
</script>

<template>
  <div
    class="rounded-full bg-slate-300 overflow-hidden flex items-center justify-center shrink-0"
    :style="{ width: sz + 'px', height: sz + 'px' }"
  >
    <img
      v-if="url"
      :src="url"
      :alt="fallbackName"
      class="w-full h-full object-cover"
    />
    <span
      v-else
      class="text-slate-600 font-bold"
      :style="{ fontSize: sz * 0.5 + 'px' }"
    >{{ initial }}</span>
  </div>
</template>
