<script setup lang="ts">
import { onMounted, reactive, ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useSessionsStore } from '@/stores/sessions'
import { useWorldsStore } from '@/stores/worlds'
import { useCharactersStore } from '@/stores/characters'
import { useModelConfigsStore } from '@/stores/modelConfigs'
import { sessionsApi } from '@/api/sessions'
import type { SessionIn } from '@/api/types'
import GenreSelector from '@/components/GenreSelector.vue'

const router = useRouter()
const sessionsStore = useSessionsStore()
const worldsStore = useWorldsStore()
const charsStore = useCharactersStore()
const modelsStore = useModelConfigsStore()

const dialogOpen = ref(false)
const submitting = ref(false)
const createMode = ref<'wizard' | 'quick'>('wizard')

function goWizard() {
  dialogOpen.value = false
  router.push({ name: 'session-wizard' })
}

const form = reactive<SessionIn>({
  name: '',
  world_id: 0,
  character_id: 0,
  gm_model_config_id: 0,
  summarizer_model_config_id: 0,
})

const genreForm = reactive<{ genre: string; custom_prompt: string }>({
  genre: '悬疑探案',
  custom_prompt: '',
})

const charsForWorld = computed(() =>
  charsStore.items.filter((c) => c.world_id === form.world_id),
)

function reset() {
  Object.assign(form, {
    name: '',
    world_id: worldsStore.items[0]?.id ?? 0,
    character_id: 0,
    gm_model_config_id: modelsStore.items[0]?.id ?? 0,
    summarizer_model_config_id: modelsStore.items[0]?.id ?? 0,
  })
  genreForm.genre = '悬疑探案'
  genreForm.custom_prompt = ''
}

async function exportSession(id: number, format: 'json' | 'md') {
  try {
    const blob = await sessionsApi.exportSession(id, format)
    const typed =
      blob.type
        ? blob
        : new Blob([blob], {
            type: format === 'json' ? 'application/json' : 'text/markdown',
          })
    const url = URL.createObjectURL(typed)
    const a = document.createElement('a')
    a.href = url
    a.download = `dzmm_export_${id}.${format}`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  } catch (e: any) {
    ElMessage.error(e.message ?? '导出失败')
  }
}

async function onDelete(row: { id: number; name: string; turn_count: number; world_id: number; character_id: number }) {
  try {
    await ElMessageBox.confirm(
      `确定要删除存档「${row.name}」吗？\n\n该操作会一并清除：消息历史、NPC、关系、` +
      `剧情线、编年史、目标、暗中状态、剧本、玩家反馈等。\n\n此操作无法撤销。`,
      `删除存档（已进行 ${row.turn_count} 回合）`,
      {
        confirmButtonText: '确认删除',
        cancelButtonText: '取消',
        type: 'warning',
        confirmButtonClass: 'el-button--danger',
      },
    )
  } catch {
    return  // user cancelled
  }
  try {
    await sessionsStore.remove(row.id)
    ElMessage.success(`已删除「${row.name}」`)
  } catch (e: any) {
    ElMessage.error(e.message ?? '删除失败')
    return
  }

  // Ask about deleting world
  const worldName = worldNameById.value.get(row.world_id) ?? `世界观 #${row.world_id}`
  const otherSessionsWithWorld = sessionsStore.items.filter(
    (s) => s.world_id === row.world_id,
  )
  const worldWarning = otherSessionsWithWorld.length > 0
    ? `\n⚠️ 还有 ${otherSessionsWithWorld.length} 个其他存档使用此世界观，删除后它们也将失去关联。`
    : ''
  try {
    await ElMessageBox.confirm(
      `是否同时删除世界观「${worldName}」？${worldWarning}`,
      '删除世界观',
      {
        confirmButtonText: '删除',
        cancelButtonText: '保留',
        type: 'warning',
        confirmButtonClass: 'el-button--danger',
        distinguishCancelAndClose: true,
      },
    )
    await worldsStore.remove(row.world_id)
    ElMessage.success(`已删除世界观「${worldName}」`)
  } catch { /* user chose to keep or closed dialog */ }

  // Ask about deleting character
  const charName = charNameById.value.get(row.character_id) ?? `角色 #${row.character_id}`
  const otherSessionsWithChar = sessionsStore.items.filter(
    (s) => s.character_id === row.character_id,
  )
  const charWarning = otherSessionsWithChar.length > 0
    ? `\n⚠️ 还有 ${otherSessionsWithChar.length} 个其他存档使用此角色卡，删除后它们也将失去关联。`
    : ''
  try {
    await ElMessageBox.confirm(
      `是否同时删除角色卡「${charName}」？${charWarning}`,
      '删除角色卡',
      {
        confirmButtonText: '删除',
        cancelButtonText: '保留',
        type: 'warning',
        confirmButtonClass: 'el-button--danger',
        distinguishCancelAndClose: true,
      },
    )
    await charsStore.remove(row.character_id)
    ElMessage.success(`已删除角色卡「${charName}」`)
  } catch { /* user chose to keep or closed dialog */ }
}

async function onCreate() {
  submitting.value = true
  try {
    if (!form.world_id || !form.character_id || !form.gm_model_config_id) {
      ElMessage.warning('请补全所有字段')
      return
    }
    if (genreForm.genre === '自定义' && !genreForm.custom_prompt.trim()) {
      ElMessage.warning('选择「自定义」时请填写故事描述')
      return
    }
    const s = await sessionsStore.create(form)
    ElMessage.success('已创建，正在生成剧本…')
    dialogOpen.value = false
    router.push({
      name: 'session-generate',
      params: { id: String(s.id) },
      query: {
        genre: genreForm.genre,
        custom_prompt: genreForm.custom_prompt,
      },
    })
  } catch (e: any) {
    ElMessage.error(e.message)
  } finally {
    submitting.value = false
  }
}

const worldNameById = computed(() => {
  const m = new Map<number, string>()
  for (const w of worldsStore.items) m.set(w.id, w.name)
  return m
})
const charNameById = computed(() => {
  const m = new Map<number, string>()
  for (const c of charsStore.items) m.set(c.id, c.name)
  return m
})

onMounted(async () => {
  await Promise.all([
    sessionsStore.refresh(),
    worldsStore.refresh(),
    charsStore.refresh(),
    modelsStore.refresh(),
  ])
  reset()
})
</script>

<template>
  <div class="p-6">
    <div class="flex items-center justify-between mb-4">
      <h2 class="text-2xl font-bold">跑团存档</h2>
      <el-button type="primary" @click="dialogOpen = true">+ 新开一局</el-button>
    </div>

    <el-table :data="sessionsStore.items" v-loading="sessionsStore.loading" border>
      <el-table-column prop="name" label="名称" width="220" />
      <el-table-column label="世界" width="200">
        <template #default="{ row }">{{ worldNameById.get(row.world_id) }}</template>
      </el-table-column>
      <el-table-column label="角色" width="160">
        <template #default="{ row }">{{ charNameById.get(row.character_id) }}</template>
      </el-table-column>
      <el-table-column prop="turn_count" label="回合数" width="100" />
      <el-table-column label="操作" width="290">
        <template #default="{ row }">
          <el-button size="small" type="primary" @click="router.push(`/play/${row.id}`)">
            继续
          </el-button>
          <el-dropdown
            class="ml-2"
            trigger="click"
            @command="(cmd: 'json' | 'md') => exportSession(row.id, cmd)"
          >
            <el-button size="small">📥 导出 ▾</el-button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="json">
                  JSON（含完整结构化数据）
                </el-dropdown-item>
                <el-dropdown-item command="md">
                  Markdown（人类可读）
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
          <el-button
            class="ml-2"
            size="small"
            type="danger"
            plain
            @click="onDelete(row)"
          >🗑️ 删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="dialogOpen" title="新开一局" width="640px">
      <el-tabs v-model="createMode" type="card">
        <el-tab-pane label="🪄 向导式（推荐）" name="wizard">
          <div class="space-y-3 p-2">
            <div class="text-sm text-slate-700 leading-relaxed">
              分 6 步引导你创建独有的世界、主角、剧本。每一步都可以审阅、
              编辑、重新生成。本地 12B+ 模型也能生成有质感的世界观。
            </div>
            <div class="bg-amber-50 border border-amber-200 rounded p-3 text-xs text-amber-800 leading-relaxed">
              💡 向导耗时较长（每步 30-90s × 6 步 ≈ 5-10 分钟）。
              如果用本地小模型容易卡，建议切到云端模型（满血推荐）。
            </div>
            <el-button type="primary" size="large" @click="goWizard">
              📜 进入向导
            </el-button>
          </div>
        </el-tab-pane>

        <el-tab-pane label="⚡ 快速创建（预设）" name="quick">
          <div class="bg-blue-50 border border-blue-200 rounded p-3 text-xs text-blue-800 mb-3 leading-relaxed">
            💡 一键生成大纲后即可开始。本地 7-8B 模型够用；
            想要更精致的世界观推荐用「向导式」。
          </div>
          <el-form :model="form" label-width="100px">
            <el-form-item label="存档名称" required>
              <el-input v-model="form.name" placeholder="例如：赛博朋克 第一夜" />
            </el-form-item>
            <el-form-item label="世界观" required>
              <el-select v-model="form.world_id" @change="form.character_id = 0">
                <el-option
                  v-for="w in worldsStore.items"
                  :key="w.id"
                  :label="w.name"
                  :value="w.id"
                />
              </el-select>
            </el-form-item>
            <el-form-item label="角色" required>
              <el-select v-model="form.character_id" :disabled="!form.world_id">
                <el-option
                  v-for="c in charsForWorld"
                  :key="c.id"
                  :label="c.name"
                  :value="c.id"
                />
              </el-select>
            </el-form-item>
            <el-form-item label="GM 模型" required>
              <el-select v-model="form.gm_model_config_id">
                <el-option
                  v-for="m in modelsStore.items"
                  :key="m.id"
                  :label="`${m.name} (${m.model_name})`"
                  :value="m.id"
                />
              </el-select>
            </el-form-item>
            <el-form-item label="摘要模型" required>
              <el-select v-model="form.summarizer_model_config_id">
                <el-option
                  v-for="m in modelsStore.items"
                  :key="m.id"
                  :label="`${m.name} (${m.model_name})`"
                  :value="m.id"
                />
              </el-select>
            </el-form-item>
            <el-form-item label="故事类型" required>
              <GenreSelector v-model="genreForm" />
            </el-form-item>
          </el-form>
        </el-tab-pane>
      </el-tabs>
      <template #footer>
        <el-button @click="dialogOpen = false">取消</el-button>
        <el-button
          v-if="createMode === 'quick'"
          type="primary"
          :loading="submitting"
          @click="onCreate"
        >
          开始跑团
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>
