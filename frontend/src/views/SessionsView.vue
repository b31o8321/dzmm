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
import { charactersApi } from '@/api/characters'
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
const createMode = ref<'screenplay' | 'new-screenplay' | 'fresh'>('screenplay')

// Tier-2 (existing world, new screenplay) — separate world picker so
// it doesn't fight with tier-1's screenplay-pinned world.
const tier2WorldId = ref(0)

function goWizard() {
  // Tier 3: full wizard. Don't clear an in-progress draft — wizard will
  // surface a "草稿已恢复" hint and the user can refresh to wipe it.
  dialogOpen.value = false
  router.push({ name: 'session-wizard' })
}

function goWizardWithWorld() {
  // Tier 2: prime the wizard's localStorage draft with an existing world,
  // then jump to step 3 (PC). The wizard's loadDraft() will restore from
  // this entry on mount.
  if (!tier2WorldId.value) {
    ElMessage.warning('请先选择世界观')
    return
  }
  const w = worldsStore.items.find((x) => x.id === tier2WorldId.value)
  if (!w) {
    ElMessage.error('找不到所选世界观')
    return
  }
  const draft = {
    step: 3,
    state: {
      wizard_model_config_id: modelsStore.items[0]?.id ?? null,
      gm_model_config_id: form.value.gm_model_config_id || (modelsStore.items[0]?.id ?? null),
      summarizer_model_config_id:
        form.value.summarizer_model_config_id || (modelsStore.items[0]?.id ?? null),
      genre: '悬疑探案',
      custom_genre: '',
      theme: '',
      session_name: form.value.name || '',
      world_brief: {
        name: w.name,
        setting: '',
        conflict: '',
        raw_md: w.content_md,
      },
      world_md: w.content_md,
      worldCoverAssetId: null,
      archetype: '',
      character_name: '',
      character_gender: '',
      character_md: '',
      npcs: [],
      pinned_npc_names: [],
      screenplay: null,
      chapterBgmAssetIds: [],
      sceneAssets: [],
      raw_outputs: {},
    },
  }
  try {
    localStorage.setItem('dzmm_wizard_draft', JSON.stringify(draft))
  } catch (e: any) {
    ElMessage.error(`无法写入草稿：${e?.message ?? e}`)
    return
  }
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
  tier2WorldId.value = 0
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

// ── Delete-session dialog state (3-tier UX) ──────────────────────────
//   tier 1: session only — keeps screenplay + world (replay same screenplay)
//   tier 2: session + screenplay (+PC + NPCs) — keeps world (new screenplay
//           in same world)
//   tier 3: session + screenplay + world — full nuke
const deleteDialog = reactive<{
  open: boolean
  target: GameSession | null
  tier: 1 | 2 | 3
  loading: boolean
  worldSummary: { characters: number; sessions: number; screenplays: number } | null
  screenplayShared: boolean  // true if other sessions also use this screenplay
}>({
  open: false,
  target: null,
  tier: 1,
  loading: false,
  worldSummary: null,
  screenplayShared: false,
})

async function onDelete(row: GameSession) {
  deleteDialog.target = row
  deleteDialog.tier = 1
  deleteDialog.loading = false
  deleteDialog.worldSummary = null
  deleteDialog.screenplayShared = false
  deleteDialog.open = true

  // Concurrently fetch the data the dialog needs to label the tiers.
  const tasks: Promise<void>[] = [
    worldsApi.cascadeSummary(row.world_id)
      .then((s) => { deleteDialog.worldSummary = s })
      .catch(() => { /* leave null */ }),
  ]
  if (row.screenplay_id) {
    tasks.push(
      standaloneScreenplayApi.refs(row.screenplay_id)
        .then((r) => { deleteDialog.screenplayShared = r.sessions > 1 })
        .catch(() => { /* assume shared = unknown */ }),
    )
  }
  await Promise.all(tasks)
}

const deleteDialogScreenplayName = computed(() => {
  const sid = deleteDialog.target?.screenplay_id ?? null
  if (sid == null) return ''
  for (const list of spStore.byWorld.values()) {
    const hit = list.find((sp) => sp.id === sid)
    if (hit) return hit.title
  }
  return `剧本 #${sid}`
})

const deleteDialogWorldName = computed(() => {
  const wid = deleteDialog.target?.world_id
  if (wid == null) return ''
  return worldNameById.value.get(wid) ?? `世界观 #${wid}`
})

// Tier 2 is only meaningful if the screenplay isn't shared by another session.
const deleteDialogTier2Disabled = computed(() => {
  const t = deleteDialog.target
  if (!t) return true
  if (!t.screenplay_id) return true  // legacy session without screenplay
  return deleteDialog.screenplayShared
})

// Tier 3 disabled when the world's other sessions / world-level screenplays
// would still want to live (we still allow it but warn). Always enabled.
async function confirmDeleteSession() {
  const row = deleteDialog.target
  if (!row) return
  deleteDialog.loading = true
  const tier = deleteDialog.tier
  try {
    if (tier === 3) {
      // Single cascade call wipes the world + every session + screenplay +
      // character under it (including this one).
      await worldsStore.remove(row.world_id, { cascade: true })
      // Refresh the local sessions list since the cascade removed others.
      await sessionsStore.refresh()
      ElMessage.success(`已删除世界观「${deleteDialogWorldName.value}」及其全部内容`)
    } else {
      // Tier 1 + 2 both start with a session delete.
      const charId = row.character_id
      const screenplayId = row.screenplay_id
      await sessionsStore.remove(row.id)

      if (tier === 2) {
        // Best-effort: delete screenplay + character. Both refuse via 409
        // if something else still references them, in which case we just
        // log and move on.
        if (screenplayId) {
          try {
            await standaloneScreenplayApi.remove(screenplayId)
          } catch (e: any) {
            ElMessage.warning(`剧本未删除：${e?.message ?? '可能仍有引用'}`)
          }
        }
        if (charId) {
          try {
            await charactersApi.remove(charId)
          } catch {
            // Silent — most often a 404 because the wizard's PC was the
            // only character and it cascaded with the session somehow,
            // or a 409 if another session references it.
          }
        }
        ElMessage.success(`已删除存档「${row.name}」+ 剧本 + PC`)
      } else {
        ElMessage.success(`已删除存档「${row.name}」`)
      }
    }
    deleteDialog.open = false
  } catch (e: any) {
    ElMessage.error(e?.message ?? '删除失败')
  } finally {
    deleteDialog.loading = false
  }
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

    <!-- 3-tier delete dialog -->
    <el-dialog
      v-model="deleteDialog.open"
      title="删除存档"
      width="560px"
      :close-on-click-modal="false"
    >
      <div v-if="deleteDialog.target" class="space-y-3 text-sm">
        <div class="text-slate-600">
          存档「<span class="font-medium">{{ deleteDialog.target.name }}</span>」（已进行
          {{ deleteDialog.target.turn_count }} 回合）
        </div>

        <el-radio-group v-model="deleteDialog.tier" class="flex flex-col gap-2 w-full">
          <div class="border border-slate-200 rounded p-3">
            <el-radio :value="1">
              <span class="font-medium">仅删除当前进度</span>
              <span class="text-xs text-slate-500 ml-2">（保留剧本 + 世界观）</span>
            </el-radio>
            <div class="text-xs text-slate-500 ml-6 mt-1">
              清除：消息历史 / NPC / 关系 / 剧情线 / 目标 / 暗中状态 / 反馈。
              下次可在同剧本重玩。
            </div>
          </div>

          <div
            class="border rounded p-3"
            :class="deleteDialogTier2Disabled ? 'border-slate-200 opacity-60' : 'border-slate-200'"
          >
            <el-radio :value="2" :disabled="deleteDialogTier2Disabled">
              <span class="font-medium">同时删除剧本</span>
              <span class="text-xs text-slate-500 ml-2">（保留世界观）</span>
            </el-radio>
            <div class="text-xs text-slate-500 ml-6 mt-1">
              额外清除：剧本「{{ deleteDialogScreenplayName || '—' }}」+ 主角 + 该剧本 NPC。
              下次可在同世界观下创建新剧本。
            </div>
            <div v-if="deleteDialog.screenplayShared" class="text-xs text-amber-600 ml-6 mt-1">
              ⚠️ 此剧本仍被其他存档使用，无法删除（仅可选项 1）
            </div>
            <div v-else-if="!deleteDialog.target.screenplay_id" class="text-xs text-amber-600 ml-6 mt-1">
              此存档没有绑定独立剧本（旧版数据）
            </div>
          </div>

          <div class="border border-slate-200 rounded p-3">
            <el-radio :value="3">
              <span class="font-medium">同时删除世界观</span>
              <span class="text-xs text-slate-500 ml-2">（全部删除）</span>
            </el-radio>
            <div class="text-xs text-slate-500 ml-6 mt-1">
              额外清除：世界观「{{ deleteDialogWorldName }}」+
              <template v-if="deleteDialog.worldSummary">
                {{ deleteDialog.worldSummary.sessions }} 个存档（含本存档）/
                {{ deleteDialog.worldSummary.screenplays }} 个剧本 /
                {{ deleteDialog.worldSummary.characters }} 个角色
              </template>
              <template v-else>
                <span class="text-slate-400 italic">加载中…</span>
              </template>
            </div>
            <div
              v-if="deleteDialog.worldSummary && deleteDialog.worldSummary.sessions > 1"
              class="text-xs text-rose-500 ml-6 mt-1"
            >
              ⚠️ 还有 {{ deleteDialog.worldSummary.sessions - 1 }} 个其他存档将一并删除
            </div>
          </div>
        </el-radio-group>

        <div class="text-xs text-slate-500 pt-1 border-t border-slate-100">
          所选操作不可恢复。
        </div>
      </div>
      <template #footer>
        <el-button @click="deleteDialog.open = false">取消</el-button>
        <el-button
          type="danger"
          :loading="deleteDialog.loading"
          @click="confirmDeleteSession"
        >确认删除</el-button>
      </template>
    </el-dialog>

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
      <el-radio-group v-model="createMode" class="flex flex-col gap-2 w-full mb-3">
        <div class="border border-slate-200 rounded p-3">
          <el-radio value="screenplay">
            <span class="font-medium">⚡ 用现有剧本直接玩</span>
            <span class="text-xs text-slate-500 ml-2">（最快，1 分钟内进游戏）</span>
          </el-radio>
        </div>
        <div class="border border-slate-200 rounded p-3">
          <el-radio value="new-screenplay">
            <span class="font-medium">🌍 用现有世界观，重新创作剧本</span>
            <span class="text-xs text-slate-500 ml-2">（向导跳过世界观环节，直接生成 PC + NPC + 剧本）</span>
          </el-radio>
        </div>
        <div class="border border-slate-200 rounded p-3">
          <el-radio value="fresh">
            <span class="font-medium">🪄 全部重新创建</span>
            <span class="text-xs text-slate-500 ml-2">（完整向导：世界观 → PC → NPC → 剧本）</span>
          </el-radio>
        </div>
      </el-radio-group>

      <!-- Tier 3: full wizard -->
      <div v-if="createMode === 'fresh'" class="space-y-3 p-2 bg-slate-50 border border-slate-200 rounded">
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

      <!-- Tier 2: existing world, new screenplay -->
      <div v-else-if="createMode === 'new-screenplay'" class="p-2 bg-slate-50 border border-slate-200 rounded">
        <div class="bg-blue-50 border border-blue-200 rounded p-3 text-xs text-blue-800 mb-3 leading-relaxed">
          💡 沿用一个已有世界观，向导从「主角生成」步骤开始（节省 2-3 分钟世界观生成时间）。
        </div>
        <el-form label-width="100px">
          <el-form-item label="存档名称">
            <el-input v-model="form.name" placeholder="留空则进入向导后自动命名" />
          </el-form-item>
          <el-form-item label="世界观" required>
            <el-select v-model="tier2WorldId" placeholder="选择已有世界观">
              <el-option
                v-for="w in worldsStore.items"
                :key="w.id"
                :label="w.name"
                :value="w.id"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="GM 模型">
            <el-select v-model="form.gm_model_config_id" placeholder="向导内可改">
              <el-option
                v-for="m in modelsStore.items"
                :key="m.id"
                :label="`${m.name} (${m.model_name})`"
                :value="m.id"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="摘要模型">
            <el-select v-model="form.summarizer_model_config_id" placeholder="向导内可改">
              <el-option
                v-for="m in modelsStore.items"
                :key="m.id"
                :label="`${m.name} (${m.model_name})`"
                :value="m.id"
              />
            </el-select>
          </el-form-item>
        </el-form>
        <el-button type="primary" size="large" :disabled="!tier2WorldId" @click="goWizardWithWorld">
          📜 进入向导（从主角开始）
        </el-button>
      </div>

      <!-- Tier 1: existing screenplay -->
      <div v-else class="p-2 bg-slate-50 border border-slate-200 rounded">
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
      </div>
      <template #footer>
        <el-button @click="dialogOpen = false">取消</el-button>
        <el-button
          v-if="createMode === 'screenplay'"
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
