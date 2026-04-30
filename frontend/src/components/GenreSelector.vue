<script setup lang="ts">
import { ref, watch } from 'vue'
import { ElInput } from 'element-plus'
import { KNOWN_GENRES } from '@/api/screenplay'

const props = defineProps<{
  modelValue: { genre: string; custom_prompt: string }
}>()
const emit = defineEmits<{
  'update:modelValue': [{ genre: string; custom_prompt: string }]
}>()

const selected = ref(props.modelValue.genre || '悬疑探案')
const customText = ref(props.modelValue.custom_prompt || '')

function update() {
  emit('update:modelValue', {
    genre: selected.value,
    custom_prompt: customText.value,
  })
}

watch([selected, customText], update)

watch(
  () => props.modelValue,
  (v) => {
    if (v.genre !== selected.value) selected.value = v.genre || '悬疑探案'
    if (v.custom_prompt !== customText.value)
      customText.value = v.custom_prompt || ''
  },
)
</script>

<template>
  <div class="space-y-3">
    <div class="grid grid-cols-2 gap-2">
      <button
        v-for="g in KNOWN_GENRES"
        :key="g.key"
        type="button"
        :class="[
          'text-left p-3 rounded border transition',
          selected === g.key
            ? 'bg-blue-50 border-blue-400 ring-2 ring-blue-200'
            : 'bg-white border-slate-200 hover:border-slate-400',
        ]"
        @click="selected = g.key"
      >
        <div class="font-bold text-slate-800">{{ g.label }}</div>
        <div class="text-xs text-slate-500 mt-1">{{ g.desc }}</div>
      </button>
    </div>
    <el-input
      v-if="selected === '自定义'"
      v-model="customText"
      type="textarea"
      :autosize="{ minRows: 3, maxRows: 6 }"
      placeholder="例如：一场冰雪覆盖大陆的末日逃亡 / 你想要的故事类型 / 主题 / 走向"
      maxlength="1000"
      show-word-limit
    />
  </div>
</template>
