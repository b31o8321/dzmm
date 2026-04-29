<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useModelConfigsStore } from '@/stores/modelConfigs'
import type { ModelConfigIn } from '@/api/types'

const store = useModelConfigsStore()
const dialogOpen = ref(false)
const submitting = ref(false)
const testing = ref<number | null>(null)

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

async function onCreate() {
  submitting.value = true
  try {
    const payload: ModelConfigIn = { ...form }
    if (!payload.api_key) delete (payload as any).api_key
    await store.create(payload)
    ElMessage.success('已添加')
    dialogOpen.value = false
    resetForm()
  } catch (e: any) {
    ElMessage.error(e.message)
  } finally {
    submitting.value = false
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
      <el-button type="primary" @click="dialogOpen = true">+ 新增</el-button>
    </div>

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
      <el-table-column label="操作" width="120">
        <template #default="{ row }">
          <el-button
            size="small"
            :loading="testing === row.id"
            @click="onTest(row.id)"
          >测试</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="dialogOpen" title="新增模型配置" width="520px">
      <el-form :model="form" label-width="100px">
        <el-form-item label="名称" required>
          <el-input v-model="form.name" placeholder="例如：本地 qwen" />
        </el-form-item>
        <el-form-item label="类型" required>
          <el-select v-model="form.type">
            <el-option label="Ollama 本地" value="ollama" />
            <el-option label="OpenAI 兼容（云端）" value="openai_compat" />
          </el-select>
        </el-form-item>
        <el-form-item label="Base URL" required>
          <el-input v-model="form.base_url" />
        </el-form-item>
        <el-form-item label="模型" required>
          <el-input v-model="form.model_name" placeholder="例如：qwen2.5:7b" />
        </el-form-item>
        <el-form-item label="API Key" v-if="form.type === 'openai_compat'">
          <el-input v-model="form.api_key" type="password" show-password />
        </el-form-item>
        <el-form-item label="超时（秒）">
          <el-input-number v-model="form.timeout" :min="5" :max="300" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogOpen = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="onCreate">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>
