<script setup lang="ts">
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { charactersApi } from '@/api/characters'
import type { Character } from '@/api/types'

const props = defineProps<{
  modelValue: boolean
  character: Character | null
}>()
const emit = defineEmits<{
  'update:modelValue': [boolean]
  leveled: [Character]
}>()

const submitting = ref(false)

function bonusFor(stat: string): number {
  return stat === 'hp' || stat === 'stamina' ? 5 : 1
}

async function chooseStat(stat: string) {
  if (!props.character) return
  submitting.value = true
  try {
    const updated = await charactersApi.levelup(props.character.id, stat)
    ElMessage.success(`升级成功！${stat} +${bonusFor(stat)}`)
    emit('leveled', updated)
    emit('update:modelValue', false)
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail ?? e?.message ?? '升级失败')
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    @update:model-value="$emit('update:modelValue', $event)"
    title="🎉 升级了！"
    width="480px"
  >
    <p class="text-sm text-slate-600 mb-4">
      你达成了 Lv {{ character?.level ?? 1 }} → Lv {{ (character?.level ?? 1) + 1 }} 的经验门槛。
      选择一个属性提升：
    </p>
    <div class="grid grid-cols-2 gap-3">
      <button
        :disabled="submitting"
        class="border border-slate-300 hover:border-rose-400 hover:bg-rose-50 rounded p-4 text-left disabled:opacity-50"
        @click="chooseStat('hp')"
      >
        <div class="font-bold">❤️ HP +5</div>
        <div class="text-xs text-slate-500">承伤更多</div>
      </button>
      <button
        :disabled="submitting"
        class="border border-slate-300 hover:border-purple-400 hover:bg-purple-50 rounded p-4 text-left disabled:opacity-50"
        @click="chooseStat('sanity')"
      >
        <div class="font-bold">🧠 理智 +1</div>
        <div class="text-xs text-slate-500">抵抗心理冲击</div>
      </button>
      <button
        :disabled="submitting"
        class="border border-slate-300 hover:border-emerald-400 hover:bg-emerald-50 rounded p-4 text-left disabled:opacity-50"
        @click="chooseStat('stamina')"
      >
        <div class="font-bold">⚡ 耐力 +5</div>
        <div class="text-xs text-slate-500">体力活动更持久</div>
      </button>
      <button
        :disabled="submitting"
        class="border border-slate-300 hover:border-blue-400 hover:bg-blue-50 rounded p-4 text-left disabled:opacity-50"
        @click="chooseStat('灵力')"
      >
        <div class="font-bold">✨ 灵力 +1</div>
        <div class="text-xs text-slate-500">超自然能力（仙侠/灵能）</div>
      </button>
    </div>
  </el-dialog>
</template>
