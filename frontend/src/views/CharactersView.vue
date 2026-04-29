<script setup lang="ts">
import { onMounted, reactive, ref, computed } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useCharactersStore } from '@/stores/characters'
import { useWorldsStore } from '@/stores/worlds'
import { charactersApi } from '@/api/characters'
import type { Character, CharacterIn } from '@/api/types'
import CharacterAvatar from '@/components/CharacterAvatar.vue'

const charsStore = useCharactersStore()
const worldsStore = useWorldsStore()

const dialogOpen = ref(false)
const editingId = ref<number | null>(null)
const editingPortraitPath = ref<string>('')
const portraitVersion = ref(0)  // bump after upload to bust img cache
const submitting = ref(false)
const removing = ref<number | null>(null)
const uploadingPortrait = ref(false)
const portraitInput = ref<HTMLInputElement | null>(null)

const form = reactive<CharacterIn>({
  world_id: 0,
  name: '',
  profile_md: '',
  base_stats_json: '{"hp":20,"sanity":15,"stamina":10}',
})

function reset() {
  Object.assign(form, {
    world_id: worldsStore.items[0]?.id ?? 0,
    name: '',
    profile_md: '',
    base_stats_json: '{"hp":20,"sanity":15,"stamina":10}',
  })
  editingPortraitPath.value = ''
}

function openCreate() {
  editingId.value = null
  reset()
  dialogOpen.value = true
}

function openEdit(row: Character) {
  editingId.value = row.id
  editingPortraitPath.value = row.portrait_path ?? ''
  Object.assign(form, {
    world_id: row.world_id,
    name: row.name,
    profile_md: row.profile_md,
    base_stats_json: row.base_stats_json,
  })
  dialogOpen.value = true
}

async function onPortraitChange(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  // Reset the input so selecting the same file twice still triggers change.
  input.value = ''
  if (!file || editingId.value === null) return
  uploadingPortrait.value = true
  try {
    const updated = await charactersApi.uploadPortrait(editingId.value, file)
    editingPortraitPath.value = updated.portrait_path ?? ''
    portraitVersion.value++
    // Update the row in the store too so the list thumbnail refreshes.
    const idx = charsStore.items.findIndex((c) => c.id === updated.id)
    if (idx >= 0) charsStore.items[idx] = updated
    ElMessage.success('头像已更新')
  } catch (err: any) {
    ElMessage.error(err.message ?? '上传失败')
  } finally {
    uploadingPortrait.value = false
  }
}

const worldNameById = computed(() => {
  const m = new Map<number, string>()
  for (const w of worldsStore.items) m.set(w.id, w.name)
  return m
})

async function onSubmit() {
  submitting.value = true
  try {
    if (!form.world_id) {
      ElMessage.warning('请先选择世界观')
      return
    }
    try { JSON.parse(form.base_stats_json) }
    catch { ElMessage.error('属性 JSON 格式错误'); return }

    if (editingId.value === null) {
      await charsStore.create(form)
      ElMessage.success('已创建')
    } else {
      await charsStore.update(editingId.value, form)
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

async function onDelete(row: Character) {
  try {
    await ElMessageBox.confirm(
      `确认删除角色 "${row.name}"?`,
      '确认',
      { type: 'warning' },
    )
  } catch { return }
  removing.value = row.id
  try {
    await charsStore.remove(row.id)
    ElMessage.success('已删除')
  } catch (e: any) {
    ElMessage.error(e.message)
  } finally {
    removing.value = null
  }
}

onMounted(async () => {
  await Promise.all([worldsStore.refresh(), charsStore.refresh()])
  reset()
})
</script>

<template>
  <div class="p-6">
    <div class="flex items-center justify-between mb-4">
      <h2 class="text-2xl font-bold">角色</h2>
      <el-button type="primary" @click="openCreate">+ 新建角色</el-button>
    </div>

    <el-table :data="charsStore.items" v-loading="charsStore.loading" border>
      <el-table-column label="姓名" width="180">
        <template #default="{ row }">
          <div class="flex items-center gap-2">
            <CharacterAvatar
              :character-id="row.id"
              :has-portrait="!!row.portrait_path"
              :fallback-name="row.name"
              :size="32"
            />
            <span>{{ row.name }}</span>
          </div>
        </template>
      </el-table-column>
      <el-table-column label="世界观" width="200">
        <template #default="{ row }">{{ worldNameById.get(row.world_id) ?? '?' }}</template>
      </el-table-column>
      <el-table-column prop="base_stats_json" label="属性" width="280" />
      <el-table-column label="简介">
        <template #default="{ row }">
          <div class="line-clamp-2 text-sm text-slate-600">{{ row.profile_md }}</div>
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
      :title="editingId === null ? '新建角色' : '编辑角色'"
      width="640px"
    >
      <el-form :model="form" label-width="80px">
        <el-form-item label="头像">
          <div class="flex items-center gap-3">
            <CharacterAvatar
              :key="portraitVersion"
              :character-id="editingId"
              :has-portrait="!!editingPortraitPath"
              :fallback-name="form.name"
              :size="64"
            />
            <input
              ref="portraitInput"
              type="file"
              accept="image/png,image/jpeg,image/webp,image/svg+xml,image/gif"
              class="hidden"
              @change="onPortraitChange"
            />
            <el-button
              :disabled="editingId === null"
              :loading="uploadingPortrait"
              @click="portraitInput?.click()"
            >上传图片</el-button>
            <span v-if="editingId === null" class="text-xs text-slate-500">
              请先保存角色再上传头像
            </span>
          </div>
        </el-form-item>
        <el-form-item label="世界观" required>
          <el-select v-model="form.world_id">
            <el-option
              v-for="w in worldsStore.items"
              :key="w.id"
              :label="w.name"
              :value="w.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="姓名" required>
          <el-input v-model="form.name" />
        </el-form-item>
        <el-form-item label="属性">
          <el-input v-model="form.base_stats_json" placeholder="JSON 格式" />
        </el-form-item>
        <el-form-item label="角色简介">
          <el-input
            v-model="form.profile_md"
            type="textarea"
            :rows="8"
            placeholder="姓名、职业、外貌、性格、背景、目标..."
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogOpen = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="onSubmit">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>
