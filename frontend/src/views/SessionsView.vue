<script setup lang="ts">
import { onMounted, ref, computed, reactive } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useSessionsStore } from '@/stores/sessions'
import { useWorldsStore } from '@/stores/worlds'
import { useModelConfigsStore } from '@/stores/modelConfigs'
import { useScreenplaysStore } from '@/stores/screenplays'
import { sessionsApi } from '@/api/sessions'
import { worldsApi } from '@/api/worlds'
import { standaloneScreenplayApi } from '@/api/screenplays'
import { modelsApi } from '@/api/models'
import type { ModelCheckResult } from '@/api/models'
import type { GameSession } from '@/api/types'
import { api } from '@/api/client'

const router = useRouter()
const sessionsStore = useSessionsStore()
const worldsStore = useWorldsStore()
const modelsStore = useModelConfigsStore()
const spStore = useScreenplaysStore()

// Per-session model check results
const modelCheckResults = reactive<Record<number, ModelCheckResult | 'checking' | 'error'>>({})

async function checkSessionModel(session: GameSession) {
  modelCheckResults[session.id] = 'checking'
  try {
    const result = await modelsApi.check(session.gm_model_config_id)
    modelCheckResults[session.id] = result
  } catch {
    modelCheckResults[session.id] = 'error'
  }
}

const modelNameById = computed(() => {
  const map: Record<number, string> = {}
  for (const m of modelsStore.items) map[m.id] = m.name
  return map
})

// Fix model dialog
const fixModelDialog = reactive({
  visible: false,
  sessionId: 0,
  selectedCfgId: 0,
  saving: false,
})

function openFixModel(session: GameSession) {
  fixModelDialog.sessionId = session.id
  fixModelDialog.selectedCfgId = session.gm_model_config_id
  fixModelDialog.visible = true
  fixModelDialog.saving = false
}

async function saveFixModel() {
  fixModelDialog.saving = true
  try {
    await sessionsApi.updateGmModel(fixModelDialog.sessionId, fixModelDialog.selectedCfgId)
    await sessionsStore.refresh()
    fixModelDialog.visible = false
    ElMessage.success('模型已更新')
  } catch {
    ElMessage.error('更新失败，请重试')
  } finally {
    fixModelDialog.saving = false
  }
}

const dialogOpen = ref(false)
const submitting = ref(false)
const createMode = ref<'wizard' | 'quick'>('wizard')

function goWizard() {
  dialogOpen.value = false
  router.push({ name: 'session-wizard' })
}

const form = ref({
  name: '',
  screenplay_id: 0,
  gm_model_config_id: 0,
  summarizer_model_config_id: 0,
  contentLevel: 'safe' as 'safe' | 'mature' | 'unrestricted',
})
const selectedWorldId = ref(0)
const worldScreenplays = computed(() => spStore.byWorld.get(selectedWorldId.value) ?? [])

async function onWorldChange(worldId: number) {
  selectedWorldId.value = worldId
  form.value.screenplay_id = 0
  if (worldId) await spStore.fetchByWorld(worldId)
}

function resetForm() {
  form.value = {
    name: '',
    screenplay_id: 0,
    gm_model_config_id: modelsStore.items[0]?.id ?? 0,
    summarizer_model_config_id: modelsStore.items[0]?.id ?? 0,
    contentLevel: 'safe',
  }
  selectedWorldId.value = 0
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

async function onDelete(row: GameSession) {
  // Step 1: confirm session delete
  try {
    await ElMessageBox.confirm(
      `确定要删除存档「${row.name}」吗？\n\n该操作会一并清除：消息历史、NPC、关系、` +
      `剧情线、编年史、目标、暗中状态、玩家反馈等。\n\n此操作无法撤销。`,
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

  // Step 2: ask about deleting screenplay (only if no other session references it)
  if (row.screenplay_id) {
    try {
      const refs = await standaloneScreenplayApi.refs(row.screenplay_id)
      if (refs.sessions === 0) {
        try {
          await ElMessageBox.confirm(
            `该存档使用的剧本已不再被任何存档引用。是否一并删除？`,
            '删除剧本',
            {
              confirmButtonText: '删除',
              cancelButtonText: '保留',
              type: 'warning',
              confirmButtonClass: 'el-button--danger',
              distinguishCancelAndClose: true,
            },
          )
          await standaloneScreenplayApi.remove(row.screenplay_id)
          ElMessage.success('剧本已删除')
        } catch { /* user kept it */ }
      }
    } catch {
      // refs lookup failed (deleted screenplay etc.) — skip silently
    }
  }

  // Step 3: ask about deleting world (with cascade summary)
  const worldName = worldNameById.value.get(row.world_id) ?? `世界观 #${row.world_id}`
  let summary: { characters: number; sessions: number; screenplays: number }
  try {
    summary = await worldsApi.cascadeSummary(row.world_id)
  } catch { return }

  const total = summary.characters + summary.sessions + summary.screenplays
  if (total === 0) {
    try {
      await ElMessageBox.confirm(
        `该世界观「${worldName}」已无关联资源。是否一并删除？`,
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
    } catch { /* keep */ }
    return
  }

  const lines: string[] = []
  if (summary.sessions) lines.push(`${summary.sessions} 个其他存档（含全部消息/NPC/关系等）`)
  if (summary.characters) lines.push(`${summary.characters} 个角色`)
  if (summary.screenplays) lines.push(`${summary.screenplays} 个剧本`)
  try {
    await ElMessageBox.confirm(
      `世界观「${worldName}」还有以下关联资源：\n\n• ${lines.join('\n• ')}\n\n` +
      `是否级联删除这些内容并移除该世界观？`,
      '级联删除世界观',
      {
        confirmButtonText: '全部删除',
        cancelButtonText: '保留',
        type: 'warning',
        confirmButtonClass: 'el-button--danger',
        distinguishCancelAndClose: true,
      },
    )
    await worldsStore.remove(row.world_id, { cascade: true })
    ElMessage.success(`已删除世界观「${worldName}」及其关联资源`)
  } catch { /* keep */ }
}

async function onCreate() {
  submitting.value = true
  try {
    if (!form.value.screenplay_id || !form.value.gm_model_config_id) {
      ElMessage.warning('请选择剧本和模型')
      return
    }
    const s = await sessionsStore.create({
      name: form.value.name || '新游戏',
      screenplay_id: form.value.screenplay_id,
      gm_model_config_id: form.value.gm_model_config_id,
      summarizer_model_config_id: form.value.summarizer_model_config_id,
    })
    if (form.value.contentLevel && form.value.contentLevel !== 'safe') {
      await sessionsApi.updateSettings(s.id, { content_level: form.value.contentLevel })
    }
    ElMessage.success('已创建，正在进入游戏…')
    dialogOpen.value = false
    router.push(`/play/${s.id}`)
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
const screenplayTitleById = computed(() => {
  const m = new Map<number, string>()
  for (const [, sps] of spStore.byWorld) {
    for (const sp of sps) m.set(sp.id, sp.title)
  }
  return m
})

// --- Spinoff ---
const spinoffTarget = ref<{ id: number; name: string } | null>(null)
const spinoffName = ref('')
const spinoffNpcs = ref<{ id: number; name: string; selected: boolean }[]>([])
const spinoffLoading = ref(false)

async function openSpinoff(session: { id: number; name: string }) {
  spinoffTarget.value = session
  spinoffName.value = session.name + ' 续'
  spinoffNpcs.value = []
  try {
    const res = await api.get<{ id: number; name: string; pinned: boolean }[]>(
      `/sessions/${session.id}/npcs`,
    )
    spinoffNpcs.value = res.data.map((n) => ({
      id: n.id,
      name: n.name,
      selected: n.pinned,
    }))
  } catch (e: any) {
    ElMessage.error(e.message ?? 'NPC 加载失败')
  }
}

async function doSpinoff() {
  if (!spinoffTarget.value) return
  if (!spinoffName.value.trim()) {
    ElMessage.warning('请输入续作名称')
    return
  }
  spinoffLoading.value = true
  try {
    const npc_ids = spinoffNpcs.value.filter((n) => n.selected).map((n) => n.id)
    const res = await api.post<{ id: number; name: string }>(
      `/sessions/${spinoffTarget.value.id}/spinoff`,
      { name: spinoffName.value.trim(), npc_ids },
    )
    ElMessage.success(`已创建续作「${res.data.name}」`)
    spinoffTarget.value = null
    router.push(`/play/${res.data.id}`)
  } catch (e: any) {
    ElMessage.error(e.message ?? '创建续作失败')
  } finally {
    spinoffLoading.value = false
  }
}

onMounted(async () => {
  await Promise.all([
    sessionsStore.refresh(),
    worldsStore.refresh(),
    modelsStore.refresh(),
  ])
  for (const w of worldsStore.items) {
    spStore.fetchByWorld(w.id)
  }
  resetForm()
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
      <el-table-column label="世界观 / 剧本" min-width="200">
        <template #default="{ row }">
          <div>{{ worldNameById.get(row.world_id) ?? `世界观#${row.world_id}` }}</div>
          <div v-if="row.screenplay_id" class="sp-subtitle">
            📜 {{ screenplayTitleById.get(row.screenplay_id) ?? `剧本#${row.screenplay_id}` }}
          </div>
        </template>
      </el-table-column>
      <el-table-column prop="turn_count" label="回合数" width="100" />
      <el-table-column label="GM 模型" min-width="180">
        <template #default="{ row }">
          <div class="flex items-center gap-1 flex-wrap">
            <span class="text-slate-500 text-xs">{{ modelNameById[row.gm_model_config_id] || '—' }}</span>
            <template v-if="modelCheckResults[row.id]">
              <span v-if="modelCheckResults[row.id] === 'checking'" class="text-slate-400 text-xs">…</span>
              <span v-else-if="modelCheckResults[row.id] === 'error'" class="text-orange-500 text-xs" title="检测失败">⚠️</span>
              <span
                v-else-if="(modelCheckResults[row.id] as ModelCheckResult).narrative_ok && ((modelCheckResults[row.id] as ModelCheckResult).embed_ok ?? true)"
                class="text-green-600 text-xs" title="模型在线"
              >✓</span>
              <span
                v-else
                class="text-red-500 text-xs"
                :title="'缺少：' + (modelCheckResults[row.id] as ModelCheckResult).missing.join(', ')"
              >✗</span>
            </template>
            <el-button size="small" text @click.stop="checkSessionModel(row)" :loading="modelCheckResults[row.id] === 'checking'" class="!px-1">检测</el-button>
            <el-button size="small" text type="primary" @click.stop="openFixModel(row)" class="!px-1">修改</el-button>
          </div>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="370">
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
            type="success"
            plain
            @click="openSpinoff(row)"
          >+ 续作</el-button>
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

    <!-- Spinoff dialog -->
    <el-dialog
      :model-value="spinoffTarget !== null"
      @update:model-value="(v: boolean) => { if (!v) spinoffTarget = null }"
      title="创建续作"
      width="480px"
    >
      <el-form label-width="90px">
        <el-form-item label="续作名称">
          <el-input v-model="spinoffName" placeholder="例如：第二章 续" />
        </el-form-item>
        <el-form-item label="携带 NPC">
          <div v-if="!spinoffNpcs.length" class="text-slate-400 text-sm">
            本存档暂无 NPC
          </div>
          <div v-else class="flex flex-col gap-1 max-h-48 overflow-y-auto w-full">
            <el-checkbox
              v-for="npc in spinoffNpcs"
              :key="npc.id"
              v-model="npc.selected"
            >{{ npc.name }}</el-checkbox>
          </div>
        </el-form-item>
      </el-form>
      <div class="text-xs text-slate-500 mt-1">
        续作将继承原存档的世界观与角色卡；所选 NPC 的好感与情绪将重置为中立。
      </div>
      <template #footer>
        <el-button @click="spinoffTarget = null">取消</el-button>
        <el-button type="primary" :loading="spinoffLoading" @click="doSpinoff">
          创建续作
        </el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="dialogOpen" title="新开一局" width="640px" @closed="resetForm">
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

        <el-tab-pane label="⚡ 快速创建（已有剧本）" name="quick">
          <div class="bg-blue-50 border border-blue-200 rounded p-3 text-xs text-blue-800 mb-3 leading-relaxed">
            💡 选择已有的世界观与剧本，直接进入游戏。
          </div>
          <el-form :model="form" label-width="100px">
            <el-form-item label="存档名称">
              <el-input v-model="form.name" placeholder="留空则使用剧本名" />
            </el-form-item>
            <el-form-item label="世界观">
              <el-select
                :model-value="selectedWorldId"
                @change="onWorldChange"
                placeholder="先选世界观"
              >
                <el-option
                  v-for="w in worldsStore.items"
                  :key="w.id"
                  :label="w.name"
                  :value="w.id"
                />
              </el-select>
            </el-form-item>
            <el-form-item label="剧本" required>
              <el-select
                v-model="form.screenplay_id"
                :disabled="!selectedWorldId"
                placeholder="选择剧本"
              >
                <el-option
                  v-for="sp in worldScreenplays"
                  :key="sp.id"
                  :label="`${sp.title}（${sp.pc_name}）`"
                  :value="sp.id"
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
            <el-form-item label="内容尺度">
              <el-select v-model="form.contentLevel" size="default">
                <el-option label="🟢 安全（默认）" value="safe" />
                <el-option label="🟡 成人向（暴力 / 亲密 / 黑暗主题）" value="mature" />
                <el-option label="🔴 无限制（请确认你成年且自愿）" value="unrestricted" />
              </el-select>
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
    <!-- Fix GM model dialog -->
    <el-dialog v-model="fixModelDialog.visible" title="修改 GM 模型" width="420px">
      <div class="space-y-3">
        <div class="text-sm text-slate-600">为该存档选择新的 GM 模型：</div>
        <el-select v-model="fixModelDialog.selectedCfgId" class="w-full">
          <el-option
            v-for="cfg in modelsStore.items"
            :key="cfg.id"
            :label="`${cfg.name} (${cfg.model_name})`"
            :value="cfg.id"
          />
        </el-select>
        <div class="text-xs text-slate-400">切换后立即生效，下次回合使用新模型。</div>
      </div>
      <template #footer>
        <el-button @click="fixModelDialog.visible = false">取消</el-button>
        <el-button type="primary" :loading="fixModelDialog.saving" @click="saveFixModel">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.sp-subtitle { font-size: 12px; color: #888; }
</style>
