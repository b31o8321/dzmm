<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useWorldsStore } from '@/stores/worlds'
import MarkdownView from '@/components/MarkdownView.vue'
import type { WorldIn } from '@/api/types'

const store = useWorldsStore()
const dialogOpen = ref(false)
const submitting = ref(false)

const form = reactive<WorldIn>({
  name: '',
  content_md: '',
  style: 'dark',
  rules_mode: 'light',
})

const styles = [
  { label: '写实', value: 'realistic' },
  { label: '暗黑', value: 'dark' },
  { label: '治愈', value: 'healing' },
  { label: '幽默', value: 'comedy' },
  { label: '恐怖', value: 'horror' },
]

const rules = [
  { label: '轻量化（无骰子）', value: 'light' },
  { label: '标准（d20）', value: 'standard' },
  { label: '硬核（完整规则）', value: 'hardcore' },
]

function reset() {
  Object.assign(form, { name: '', content_md: '', style: 'dark', rules_mode: 'light' })
}

async function onCreate() {
  submitting.value = true
  try {
    await store.create(form)
    ElMessage.success('已创建')
    dialogOpen.value = false
    reset()
  } catch (e: any) {
    ElMessage.error(e.message)
  } finally {
    submitting.value = false
  }
}

onMounted(() => store.refresh())
</script>

<template>
  <div class="p-6">
    <div class="flex items-center justify-between mb-4">
      <h2 class="text-2xl font-bold">世界观</h2>
      <el-button type="primary" @click="dialogOpen = true">+ 新建世界观</el-button>
    </div>

    <el-table :data="store.items" v-loading="store.loading" border>
      <el-table-column prop="name" label="名称" width="200" />
      <el-table-column prop="style" label="风格" width="120" />
      <el-table-column prop="rules_mode" label="规则" width="120" />
      <el-table-column label="设定预览">
        <template #default="{ row }">
          <div class="line-clamp-2 text-sm text-slate-600">{{ row.content_md }}</div>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="dialogOpen" title="新建世界观" width="900px" top="5vh">
      <el-form :model="form" label-width="80px">
        <el-form-item label="名称" required>
          <el-input v-model="form.name" />
        </el-form-item>
        <el-form-item label="风格">
          <el-select v-model="form.style">
            <el-option v-for="s in styles" :key="s.value" :label="s.label" :value="s.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="规则">
          <el-select v-model="form.rules_mode">
            <el-option v-for="r in rules" :key="r.value" :label="r.label" :value="r.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="设定">
          <div class="grid grid-cols-2 gap-4 w-full">
            <el-input
              v-model="form.content_md"
              type="textarea"
              :rows="20"
              placeholder="使用 Markdown 描述世界观、势力、地理、禁忌、科技/魔法体系..."
            />
            <div class="border rounded p-3 bg-white max-h-[480px] overflow-auto">
              <MarkdownView :source="form.content_md" />
            </div>
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogOpen = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="onCreate">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>
