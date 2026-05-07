<script setup lang="ts">
defineProps<{ rolling: boolean; value: number | null }>()
</script>

<template>
  <span class="inline-block w-7 h-7 align-middle relative">
    <svg viewBox="0 0 100 100" :class="{ 'animate-spin': rolling }" class="w-full h-full">
      <polygon
        points="50,5 90,30 90,70 50,95 10,70 10,30"
        fill="#475569"
        stroke="#1e293b"
        stroke-width="2"
      />
      <text
        v-if="!rolling && value != null"
        x="50" y="62"
        text-anchor="middle"
        font-size="40"
        font-weight="bold"
        fill="white"
      >{{ value }}</text>
    </svg>
  </span>
</template>
