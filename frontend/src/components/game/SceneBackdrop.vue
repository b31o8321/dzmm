<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ imageUrl: string | null }>()

const style = computed(() =>
  props.imageUrl
    ? { backgroundImage: `linear-gradient(rgba(255,255,255,0.7), rgba(255,255,255,0.85)), url('${props.imageUrl}')` }
    : {},
)
</script>

<template>
  <Transition name="fade">
    <div
      v-if="imageUrl"
      class="absolute inset-0 -z-10 bg-cover bg-center"
      :style="style"
    />
  </Transition>
</template>

<style scoped>
.fade-enter-active, .fade-leave-active {
  transition: opacity 0.7s;
}
.fade-enter-from, .fade-leave-to {
  opacity: 0;
}
</style>
