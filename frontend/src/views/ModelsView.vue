<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useModelConfigsStore } from '@/stores/modelConfigs'
import type { ModelConfig, ModelConfigIn } from '@/api/types'

const store = useModelConfigsStore()
const dialogOpen = ref(false)
const editingId = ref<number | null>(null)
const submitting = ref(false)
const testing = ref<number | null>(null)
const removing = ref<number | null>(null)

const form = reactive<ModelConfigIn>({
  name: '',
  type: 'ollama',
  base_url: 'http://localhost:11434',
  model_name: '',
  api_key: '',
  timeout: 60,
})

function resetForm() {
  Object.assign(form, {
    name: '',
    type: 'ollama',
    base_url: 'http://localhost:11434',
    model_name: '',
    api_key: '',
    timeout: 60,
  })
}

const TYPE_DEFAULTS: Record<string, { base_url: string; model_placeholder: string }> = {
  ollama: { base_url: 'http://localhost:11434', model_placeholder: '例如：qwen2.5:7b' },
  lm_studio: { base_url: 'http://localhost:1234/v1', model_placeholder: '例如：Qwen2.5-7B-Instruct（LM Studio 中加载的模型 id）' },
  openai_compat: { base_url: 'https://api.openai.com/v1', model_placeholder: '例如：gpt-4o-mini' },
}

const modelPlaceholder = computed(
  () => TYPE_DEFAULTS[form.type]?.model_placeholder ?? '',
)

function onTypeChange(t: string) {
  // Auto-fill base_url with the type's default — but only if user hasn't
  // typed a custom URL or is leaving an empty form.
  const defaults = TYPE_DEFAULTS[t]
  if (!defaults) return
  const isDefaultUrl = Object.values(TYPE_DEFAULTS).some((d) => d.base_url === form.base_url)
  if (!form.base_url || isDefaultUrl) {
    form.base_url = defaults.base_url
  }
  // Clear api_key when switching to a local type (not used).
  if (t !== 'openai_compat') {
    form.api_key = ''
  }
}

function openCreate() {
  editingId.value = null
  resetForm()
  dialogOpen.value = true
}

function openEdit(row: ModelConfig) {
  editingId.value = row.id
  Object.assign(form, {
    name: row.name,
    type: row.type,
    base_url: row.base_url,
    model_name: row.model_name,
    api_key: '',
    timeout: row.timeout,
  })
  dialogOpen.value = true
}

async function onSubmit() {
  submitting.value = true
  try {
    const payload: ModelConfigIn = { ...form }
    if (!payload.api_key) delete (payload as any).api_key
    if (editingId.value === null) {
      await store.create(payload)
      ElMessage.success('已添加')
    } else {
      await store.update(editingId.value, payload)
      ElMessage.success('已更新')
    }
    dialogOpen.value = false
    resetForm()
    editingId.value = null
  } catch (e: any) {
    ElMessage.error(e.message)
  } finally {
    submitting.value = false
  }
}

async function onDelete(row: ModelConfig) {
  try {
    await ElMessageBox.confirm(
      `确认删除模型配置 "${row.name}"?`,
      '确认',
      { type: 'warning' },
    )
  } catch {
    return
  }
  removing.value = row.id
  try {
    await store.remove(row.id)
    ElMessage.success('已删除')
  } catch (e: any) {
    ElMessage.error(e.message)
  } finally {
    removing.value = null
  }
}

async function onTest(id: number) {
  testing.value = id
  try {
    const r = await store.test(id)
    if (r.ok) {
      ElMessageBox.alert(r.info, '连接成功', { type: 'success' })
    } else {
      ElMessageBox.alert(r.info, '连接失败', { type: 'error' })
    }
  } catch (e: any) {
    ElMessage.error(e.message)
  } finally {
    testing.value = null
  }
}

onMounted(() => store.refresh())
</script>

<template>
  <div class="p-6">
    <div class="flex items-center justify-between mb-4">
      <h2 class="text-2xl font-bold">模型配置</h2>
      <el-button type="primary" @click="openCreate">+ 新增</el-button>
    </div>

    <el-alert type="info" :closable="false" class="mb-4">
      <template #title>
        <span class="text-sm">
          推荐模型：本地 <code>qwen2.5:7b</code> / <code>llama3.1:8b</code>；云端 <code>gpt-4o-mini</code> / <code>claude-haiku</code>。
          <strong>避免</strong> <code>deepseek-r1</code> 等推理模型——它们会把输出全部放在 <code>&lt;think&gt;</code> 中，导致状态标签缺失。
        </span>
      </template>
    </el-alert>

    <el-table :data="store.items" v-loading="store.loading" border>
      <el-table-column prop="name" label="名称" width="160" />
      <el-table-column prop="type" label="类型" width="140" />
      <el-table-column prop="base_url" label="Base URL" />
      <el-table-column prop="model_name" label="模型" width="200" />
      <el-table-column label="API Key" width="100">
        <template #default="{ row }">
          {{ row.api_key_ref ? '已设置' : '—' }}
        </template>
      </el-table-column>
      <el-table-column label="操作" width="240">
        <template #default="{ row }">
          <el-button
            size="small"
            :loading="testing === row.id"
            @click="onTest(row.id)"
          >测试</el-button>
          <el-button size="small" @click="openEdit(row)">编辑</el-button>
          <el-button
            size="small"
            type="danger"
            :loading="removing === row.id"
            @click="onDelete(row)"
          >删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog
      v-model="dialogOpen"
      :title="editingId === null ? '新增模型配置' : '编辑模型配置'"
      width="520px"
    >
      <el-form :model="form" label-width="100px">
        <el-form-item label="名称" required>
          <el-input v-model="form.name" placeholder="例如：本地 qwen" />
        </el-form-item>
        <el-form-item label="类型" required>
          <el-select v-model="form.type" @change="onTypeChange">
            <el-option label="Ollama 本地" value="ollama" />
            <el-option label="LM Studio 本地" value="lm_studio" />
            <el-option label="OpenAI 兼容（云端）" value="openai_compat" />
          </el-select>
        </el-form-item>
        <el-form-item label="Base URL" required>
          <el-input v-model="form.base_url" />
        </el-form-item>
        <el-form-item label="模型" required>
          <el-input
            v-model="form.model_name"
            :placeholder="modelPlaceholder"
          />
        </el-form-item>
        <el-form-item label="API Key" v-if="form.type === 'openai_compat'">
          <el-input
            v-model="form.api_key"
            type="password"
            show-password
            :placeholder="editingId !== null ? '留空则保留原密钥' : ''"
          />
        </el-form-item>
        <el-form-item label="超时（秒）">
          <el-input-number v-model="form.timeout" :min="5" :max="300" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogOpen = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="onSubmit">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>
