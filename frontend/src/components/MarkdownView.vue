<script setup lang="ts">
import { computed } from 'vue'
import { marked } from 'marked'

const props = defineProps<{ source: string }>()

const html = computed(() => {
  marked.setOptions({ breaks: true, gfm: true })
  return marked.parse(props.source || '') as string
})
</script>

<template>
  <div class="prose max-w-none" v-html="html" />
</template>
