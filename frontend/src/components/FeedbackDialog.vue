<script setup lang="ts">
import { ref, watch } from 'vue'
import { ElDialog, ElInput, ElButton, ElRadioGroup, ElRadio, ElMessage } from 'element-plus'
import { sessionsApi } from '@/api/sessions'

const props = defineProps<{
  modelValue: boolean
  sessionId: number | null
  // Optional: bind feedback to a specific GM message (highlights "this turn" complaint)
  messageId?: number | null
}>()
const emit = defineEmits<{ 'update:modelValue': [boolean] }>()

const content = ref('')
const kind = ref<'bug' | 'suggestion' | 'praise' | 'other'>('bug')
const submitting = ref(false)

watch(
  () => props.modelValue,
  (open) => {
    if (open) {
      content.value = ''
      kind.value = 'bug'
    }
  },
)

async function submit() {
  if (!props.sessionId) {
    ElMessage.warning('当前没有选中跑团存档')
    return
  }
  const trimmed = content.value.trim()
  if (!trimmed) {
    ElMessage.warning('请填写反馈内容')
    return
  }
  if (trimmed.length > 4000) {
    ElMessage.warning('反馈过长（上限 4000 字）')
    return
  }
  submitting.value = true
  try {
    await sessionsApi.postFeedback(props.sessionId, {
      content: trimmed,
      kind: kind.value,
      message_id: props.messageId ?? undefined,
    })
    ElMessage.success('已提交，谢谢反馈！')
    emit('update:modelValue', false)
  } catch (err: any) {
    ElMessage.error(`提交失败：${err?.message ?? err}`)
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    @update:model-value="(v: boolean) => emit('update:modelValue', v)"
    title="反馈 / 吐槽"
    width="520px"
  >
    <div class="space-y-3">
      <div class="text-xs text-slate-500">
        反馈会绑定到当前跑团存档（含回合 / 时间），方便开发者结合上下文优化。
      </div>

      <el-radio-group v-model="kind">
        <el-radio value="bug">🐛 Bug / 异常</el-radio>
        <el-radio value="suggestion">💡 建议</el-radio>
        <el-radio value="praise">🌟 好评</el-radio>
        <el-radio value="other">📝 其他</el-radio>
      </el-radio-group>

      <el-input
        v-model="content"
        type="textarea"
        :autosize="{ minRows: 5, maxRows: 12 }"
        placeholder="例如：GM 反复反问，没给出关键信息（接触者名字）"
        maxlength="4000"
        show-word-limit
      />
    </div>

    <template #footer>
      <el-button @click="emit('update:modelValue', false)">取消</el-button>
      <el-button type="primary" :loading="submitting" @click="submit">
        提交反馈
      </el-button>
    </template>
  </el-dialog>
</template>
