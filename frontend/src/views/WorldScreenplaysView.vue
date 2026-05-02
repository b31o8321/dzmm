<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useScreenplaysStore } from '@/stores/screenplays'
import { useWorldsStore } from '@/stores/worlds'
import type { StandaloneScreenplayIn } from '@/api/types'
import { KNOWN_GENRES } from '@/api/screenplay'

const route = useRoute()
const worldId = computed(() => Number(route.params.id))

const spStore = useScreenplaysStore()
const worldsStore = useWorldsStore()

const items = computed(() => spStore.byWorld.get(worldId.value) ?? [])
const world = computed(() => worldsStore.items.find(w => w.id === worldId.value))

const showForm = ref(false)
const saving = ref(false)

function blankForm(): StandaloneScreenplayIn {
  return {
    title: '',
    genre: '',
    pc_name: '',
    pc_profile_md: '',
    pc_base_stats_json: '{}',
    custom_prompt: '',
    outline_md: '',
    chapters_json: '[]',
    main_characters_json: '[]',
    ending_md: '',
    opening_hook: '',
  }
}
const form = ref<StandaloneScreenplayIn>(blankForm())

async function onSubmit() {
  if (!form.value.title || !form.value.pc_name) {
    ElMessage.warning('剧本标题和 PC 名称为必填项')
    return
  }
  saving.value = true
  try {
    await spStore.create(worldId.value, form.value)
    ElMessage.success('剧本已创建')
    showForm.value = false
    form.value = blankForm()
  } catch {
    ElMessage.error('创建失败')
  } finally {
    saving.value = false
  }
}

async function onDelete(sp: { id: number; title: string }) {
  await ElMessageBox.confirm(`删除剧本「${sp.title}」？此操作不可撤销。`, '确认删除', {
    type: 'warning',
    confirmButtonText: '删除',
    cancelButtonText: '取消',
  })
  await spStore.remove(sp.id, worldId.value)
  ElMessage.success('已删除')
}

onMounted(async () => {
  await Promise.all([
    worldsStore.refresh(),
    spStore.fetchByWorld(worldId.value),
  ])
})
</script>

<template>
  <div class="world-screenplays">
    <div class="header">
      <h2>{{ world?.name ?? '世界观' }} — 剧本列表</h2>
      <el-button type="primary" @click="showForm = true">＋ 新建剧本</el-button>
    </div>

    <el-empty v-if="items.length === 0" description="暂无剧本，点击「新建剧本」开始创作" />

    <div class="sp-grid">
      <el-card v-for="sp in items" :key="sp.id" class="sp-card">
        <template #header>
          <div class="card-header">
            <span class="sp-title">{{ sp.title }}</span>
            <el-tag size="small">{{ sp.genre || '自定义' }}</el-tag>
          </div>
        </template>
        <div class="sp-pc">
          <strong>PC：</strong>{{ sp.pc_name }}
          <div v-if="sp.pc_profile_md" class="sp-profile">
            {{ sp.pc_profile_md.slice(0, 60) }}{{ sp.pc_profile_md.length > 60 ? '…' : '' }}
          </div>
        </div>
        <template #footer>
          <el-button size="small" type="danger" text @click="onDelete(sp)">删除</el-button>
        </template>
      </el-card>
    </div>

    <el-dialog v-model="showForm" title="新建剧本" width="520px">
      <el-form :model="form" label-width="80px">
        <el-form-item label="剧本标题" required>
          <el-input v-model="form.title" placeholder="例：迷雾中的红玫瑰" />
        </el-form-item>
        <el-form-item label="类型">
          <el-select v-model="form.genre" placeholder="选择类型">
            <el-option v-for="g in KNOWN_GENRES" :key="g.key" :label="g.label" :value="g.key" />
          </el-select>
        </el-form-item>
        <el-form-item label="PC 名称" required>
          <el-input v-model="form.pc_name" placeholder="主角姓名" />
        </el-form-item>
        <el-form-item label="PC 背景">
          <el-input v-model="form.pc_profile_md" type="textarea" :rows="3"
            placeholder="角色背景简述（支持 Markdown）" />
        </el-form-item>
        <el-form-item label="初始属性">
          <el-input v-model="form.pc_base_stats_json" placeholder='{"力量":5,"敏捷":5}' />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showForm = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="onSubmit">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.world-screenplays { padding: 20px; }
.header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
.sp-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 16px; }
.sp-card { cursor: default; }
.card-header { display: flex; justify-content: space-between; align-items: center; }
.sp-title { font-weight: 600; }
.sp-pc { font-size: 14px; }
.sp-profile { color: #888; margin-top: 4px; font-size: 12px; }
</style>
