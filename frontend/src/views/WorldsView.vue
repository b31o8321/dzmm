<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useRouter } from 'vue-router'
import { useWorldsStore } from '@/stores/worlds'
import { useScreenplaysStore } from '@/stores/screenplays'
import { worldsApi } from '@/api/worlds'
import MarkdownView from '@/components/MarkdownView.vue'
import type { World, WorldIn } from '@/api/types'

const store = useWorldsStore()
const router = useRouter()
const spStore = useScreenplaysStore()

const screenplayCountById = computed(() =>
  new Map(store.items.map(w => [w.id, (spStore.byWorld.get(w.id) ?? []).length]))
)
const dialogOpen = ref(false)
const editingId = ref<number | null>(null)
const submitting = ref(false)
const removing = ref<number | null>(null)

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

function openCreate() {
  editingId.value = null
  reset()
  dialogOpen.value = true
}

function openEdit(row: World) {
  editingId.value = row.id
  Object.assign(form, {
    name: row.name,
    content_md: row.content_md,
    style: row.style,
    rules_mode: row.rules_mode,
  })
  dialogOpen.value = true
}

async function onSubmit() {
  submitting.value = true
  try {
    if (editingId.value === null) {
      await store.create(form)
      ElMessage.success('已创建')
    } else {
      await store.update(editingId.value, form)
      ElMessage.success('已更新')
    }
    dialogOpen.value = false
    reset()
    editingId.value = null
  } catch (e: any) {
    ElMessage.error(e.message)
  } finally {
    submitting.value = false
  }
}

async function onDelete(row: World) {
  let summary: { characters: number; sessions: number; screenplays: number }
  try {
    summary = await worldsApi.cascadeSummary(row.id)
  } catch (e: any) {
    ElMessage.error(e.message ?? '获取关联资源数失败')
    return
  }

  const total = summary.characters + summary.sessions + summary.screenplays
  if (total === 0) {
    try {
      await ElMessageBox.confirm(
        `确认删除世界观「${row.name}」？该操作不可逆。`,
        '删除世界观',
        { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
      )
    } catch { return }
    removing.value = row.id
    try {
      await store.remove(row.id)
      ElMessage.success('已删除')
    } catch (e: any) {
      ElMessage.error(e.message)
    } finally {
      removing.value = null
    }
    return
  }

  // Cascade required.
  const lines: string[] = []
  if (summary.sessions) lines.push(`${summary.sessions} 个跑团存档（含全部消息/NPC/关系/编年史/目标等）`)
  if (summary.characters) lines.push(`${summary.characters} 个角色`)
  if (summary.screenplays) lines.push(`${summary.screenplays} 个剧本`)

  try {
    await ElMessageBox.confirm(
      `删除「${row.name}」将一并清除：\n\n• ${lines.join('\n• ')}\n\n该操作不可恢复。`,
      '级联删除世界观',
      {
        type: 'warning',
        confirmButtonText: '全部删除',
        cancelButtonText: '取消',
        confirmButtonClass: 'el-button--danger',
      },
    )
  } catch { return }

  removing.value = row.id
  try {
    await store.remove(row.id, { cascade: true })
    ElMessage.success(`已删除「${row.name}」及其关联资源`)
  } catch (e: any) {
    ElMessage.error(e.message ?? '删除失败')
  } finally {
    removing.value = null
  }
}

onMounted(async () => {
  await store.refresh()
  for (const w of store.items) {
    spStore.fetchByWorld(w.id)
  }
})
</script>

<template>
  <div class="p-6">
    <div class="flex items-center justify-between mb-4">
      <h2 class="text-2xl font-bold">世界观</h2>
      <el-button type="primary" @click="openCreate">+ 新建世界观</el-button>
    </div>

    <el-table :data="store.items" v-loading="store.loading" border>
      <el-table-column prop="name" label="名称" width="200" />
      <el-table-column prop="style" label="风格" width="100" />
      <el-table-column prop="rules_mode" label="规则" width="100" />
      <el-table-column label="设定预览">
        <template #default="{ row }">
          <div class="line-clamp-2 text-sm text-slate-600">{{ row.content_md }}</div>
        </template>
      </el-table-column>
      <el-table-column label="剧本" width="130">
        <template #default="{ row }">
          <span class="text-slate-500 text-xs">{{ screenplayCountById.get(row.id) ?? 0 }} 个剧本</span>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="160">
        <template #default="{ row }">
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
      :title="editingId === null ? '新建世界观' : '编辑世界观'"
      width="900px"
      top="5vh"
    >
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
        <el-button type="primary" :loading="submitting" @click="onSubmit">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>
