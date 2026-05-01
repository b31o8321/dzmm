<script setup lang="ts">
// Generic wizard step container.
//
// Slots:
//   default = read-only preview (rendered when not editing)
//   editor  = optional custom editor (e.g. multi-field NPC list).
//             If absent, we render a single textarea bound to v-model:content.
//
// Props:
//   title         step heading
//   content       the markdown / text being edited (only used if no `editor` slot)
//   loading       true => disable buttons + show generating bar
//   elapsed       seconds elapsed (for display when loading)
//   tip           a rotating tip string to show under the spinner
//   error         error message (rendered above the action bar)
//   canBack       show "⬅ 返回" (default true)
//   canRegenerate show "🔄 重新生成" (default true; requires backend call)
//   canHandwrite  show "✏️ 我自己写" (default true)
//   canAccept     show "⏩ 接受继续" (default true)
//
// Events:
//   update:content   v-model for textarea content
//   edit             user clicks "✏️ 编辑"  -> parent flips into edit mode
//   regenerate       user clicks "🔄 重新生成"
//   handwrite        user clicks "✏️ 我自己写"
//   accept           user clicks "⏩ 接受继续"
//   back             user clicks "⬅ 返回"
//   retry            user clicks "重试" inside the error banner
import { computed } from 'vue'
import { ElButton, ElInput, ElProgress, ElAlert } from 'element-plus'

const props = withDefaults(
  defineProps<{
    title: string
    content?: string
    editing?: boolean
    loading?: boolean
    elapsed?: number
    tip?: string
    error?: string
    canBack?: boolean
    canEdit?: boolean
    canRegenerate?: boolean
    canHandwrite?: boolean
    canAccept?: boolean
    acceptLabel?: string
  }>(),
  {
    content: '',
    editing: false,
    loading: false,
    elapsed: 0,
    tip: '',
    error: '',
    canBack: true,
    canEdit: true,
    canRegenerate: true,
    canHandwrite: true,
    canAccept: true,
    acceptLabel: '⏩ 接受继续',
  },
)

const emit = defineEmits<{
  'update:content': [string]
  edit: []
  regenerate: []
  handwrite: []
  accept: []
  back: []
  retry: []
}>()

const localContent = computed({
  get: () => props.content,
  set: (v: string) => emit('update:content', v),
})
</script>

<template>
  <div class="space-y-4">
    <div class="text-xl font-bold text-slate-800">{{ title }}</div>

    <!-- generating state -->
    <div v-if="loading" class="space-y-3 bg-white border border-slate-200 rounded p-6">
      <div class="text-sm text-slate-600">⏳ 生成中... 已用 {{ elapsed }}s / 通常 30-60s</div>
      <div v-if="tip" class="text-xs text-slate-500 min-h-[2.5rem]">💡 {{ tip }}</div>
      <el-progress
        :percentage="Math.min(elapsed * 1.5, 95)"
        :show-text="false"
        :indeterminate="elapsed > 60"
      />
      <div v-if="elapsed > 90" class="text-xs text-amber-600">
        模型生成中，最长 10 分钟。如果总卡，建议改用云模型或更小的本地模型。
      </div>
    </div>

    <!-- error -->
    <el-alert
      v-else-if="error"
      :title="error"
      type="error"
      :closable="false"
      show-icon
      class="!my-0"
    >
      <template #default>
        <div class="space-y-2">
          <div class="break-words">{{ error }}</div>
          <el-button size="small" type="primary" @click="emit('retry')">
            重试
          </el-button>
        </div>
      </template>
    </el-alert>

    <!-- editor (custom) -->
    <div v-else-if="editing && $slots.editor">
      <slot name="editor" />
    </div>

    <!-- editor (textarea fallback) -->
    <el-input
      v-else-if="editing"
      v-model="localContent"
      type="textarea"
      :autosize="{ minRows: 12, maxRows: 30 }"
      placeholder="在这里直接修改内容..."
      class="font-mono"
    />

    <!-- preview -->
    <div v-else class="bg-white border border-slate-200 rounded p-6">
      <slot />
    </div>

    <!-- actions -->
    <div v-if="!loading && !error" class="flex flex-wrap gap-2">
      <el-button v-if="canBack" @click="emit('back')">⬅ 返回</el-button>
      <el-button v-if="canEdit && !editing" @click="emit('edit')">
        ✏️ 编辑
      </el-button>
      <el-button v-if="canRegenerate && !editing" @click="emit('regenerate')">
        🔄 重新生成
      </el-button>
      <el-button v-if="canHandwrite && !editing" @click="emit('handwrite')">
        ✏️ 我自己写
      </el-button>
      <div class="flex-1" />
      <el-button v-if="canAccept" type="primary" @click="emit('accept')">
        {{ acceptLabel }}
      </el-button>
    </div>
  </div>
</template>
