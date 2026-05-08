<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useRouter } from 'vue-router'
import { useWorldsStore } from '@/stores/worlds'
import { standaloneScreenplayApi } from '@/api/screenplays'
import type { StandaloneScreenplay } from '@/api/types'

const router = useRouter()
const worldsStore = useWorldsStore()

const items = ref<StandaloneScreenplay[]>([])
const loading = ref(false)
const removing = ref<number | null>(null)
const filterWorldId = ref<number | null>(null)

const worldNameById = computed(() =>
  new Map(worldsStore.items.map(w => [w.id, w.name])),
)

const filtered = computed(() =>
  filterWorldId.value
    ? items.value.filter(sp => sp.world_id === filterWorldId.value)
    : items.value,
)

async function refresh() {
  loading.value = true
  try {
    items.value = await standaloneScreenplayApi.listAll()
  } catch (e: any) {
    ElMessage.error(e.message ?? '加载剧本失败')
  } finally {
    loading.value = false
  }
}

async function onDelete(row: StandaloneScreenplay) {
  let inUse = 0
  try {
    inUse = (await standaloneScreenplayApi.refs(row.id)).sessions
  } catch { /* allow user to attempt anyway */ }

  if (inUse > 0) {
    ElMessage.warning(`剧本「${row.title}」正被 ${inUse} 个存档使用，无法删除。请先删除这些存档。`)
    return
  }
  try {
    await ElMessageBox.confirm(
      `确认删除剧本「${row.title}」？该操作不可恢复。`,
      '删除剧本',
      {
        confirmButtonText: '删除',
        cancelButtonText: '取消',
        type: 'warning',
        confirmButtonClass: 'el-button--danger',
      },
    )
  } catch { return }

  removing.value = row.id
  try {
    await standaloneScreenplayApi.remove(row.id)
    items.value = items.value.filter(x => x.id !== row.id)
    ElMessage.success('已删除')
  } catch (e: any) {
    ElMessage.error(e.message ?? '删除失败')
  } finally {
    removing.value = null
  }
}

function onView(row: StandaloneScreenplay) {
  router.push(`/worlds/${row.world_id}/screenplays`)
}

const statusLabel: Record<StandaloneScreenplay['status'], string> = {
  active: '进行中',
  concluded: '已完结',
  superseded: '已废弃',
}

const statusType: Record<StandaloneScreenplay['status'], 'success' | 'info' | 'warning'> = {
  active: 'success',
  concluded: 'info',
  superseded: 'warning',
}

onMounted(async () => {
  await Promise.all([worldsStore.refresh(), refresh()])
})
</script>

<template>
  <div class="p-6">
    <div class="flex items-center justify-between mb-4 gap-4 flex-wrap">
      <h2 class="text-2xl font-bold">剧本</h2>
      <div class="flex items-center gap-2">
        <el-select
          v-model="filterWorldId"
          placeholder="按世界观筛选"
          clearable
          style="width: 220px"
        >
          <el-option
            v-for="w in worldsStore.items"
            :key="w.id"
            :label="w.name"
            :value="w.id"
          />
        </el-select>
        <el-button @click="refresh" :loading="loading">刷新</el-button>
      </div>
    </div>

    <el-empty
      v-if="!loading && items.length === 0"
      description="还没有剧本。可在世界观列表里点「剧本」进入对应世界后创建。"
    />

    <el-table
      v-else
      :data="filtered"
      v-loading="loading"
      border
      empty-text="无符合筛选条件的剧本"
    >
      <el-table-column label="标题" min-width="200">
        <template #default="{ row }">
          <div class="flex items-center gap-2">
            <span class="font-medium">{{ row.title }}</span>
            <el-tag size="small" :type="statusType[row.status as StandaloneScreenplay['status']]">
              {{ statusLabel[row.status as StandaloneScreenplay['status']] }}
            </el-tag>
          </div>
        </template>
      </el-table-column>
      <el-table-column label="世界观" width="180">
        <template #default="{ row }">
          {{ worldNameById.get(row.world_id) ?? `#${row.world_id}` }}
        </template>
      </el-table-column>
      <el-table-column label="题材" width="120">
        <template #default="{ row }">{{ row.genre || '—' }}</template>
      </el-table-column>
      <el-table-column label="主角" width="140">
        <template #default="{ row }">{{ row.pc_name || '—' }}</template>
      </el-table-column>
      <el-table-column label="进度" width="100">
        <template #default="{ row }">
          第 {{ row.current_chapter || 0 }} 章
        </template>
      </el-table-column>
      <el-table-column label="开篇引子" min-width="200">
        <template #default="{ row }">
          <div class="line-clamp-2 text-sm text-slate-600">{{ row.opening_hook }}</div>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="180" fixed="right">
        <template #default="{ row }">
          <el-button size="small" @click="onView(row)">在世界中查看</el-button>
          <el-button
            size="small"
            type="danger"
            :loading="removing === row.id"
            @click="onDelete(row)"
          >删除</el-button>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>
