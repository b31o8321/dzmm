<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import {
  ElDialog,
  ElButton,
  ElUpload,
  ElMessage,
  type UploadRawFile,
} from 'element-plus'
import { assetsApi, type Asset } from '@/api/assets'

const props = defineProps<{
  modelValue: number | null
  kind: 'image' | 'audio'
  category: string
  label?: string
  archetypeFilter?: string
}>()
const emit = defineEmits<{ (e: 'update:modelValue', v: number | null): void }>()

const dialogOpen = ref(false)
const assets = ref<Asset[]>([])
const loading = ref(false)
const selectedAsset = ref<Asset | null>(null)

const apiBase = import.meta.env.VITE_API_BASE ?? ''

async function loadAssets() {
  loading.value = true
  try {
    assets.value = await assetsApi.list({ kind: props.kind, category: props.category })
    if (props.archetypeFilter) {
      assets.value.sort((a, b) => {
        const aMatch = (a.tag as { archetype?: string }).archetype === props.archetypeFilter ? -1 : 0
        const bMatch = (b.tag as { archetype?: string }).archetype === props.archetypeFilter ? -1 : 0
        return aMatch - bMatch
      })
    }
  } catch (e: any) {
    ElMessage.error(`加载失败：${e?.message ?? e}`)
  } finally {
    loading.value = false
  }
}

watch(
  () => props.modelValue,
  async (id) => {
    if (id == null) {
      selectedAsset.value = null
      return
    }
    if (assets.value.length === 0) await loadAssets()
    selectedAsset.value = assets.value.find((a) => a.id === id) ?? null
    if (selectedAsset.value == null) {
      // selected id not in list (e.g. just-uploaded local asset) — refetch
      try {
        const all = await assetsApi.list({ kind: props.kind })
        selectedAsset.value = all.find((a) => a.id === id) ?? null
      } catch {
        /* ignore */
      }
    }
  },
  { immediate: true },
)

async function openPicker() {
  await loadAssets()
  dialogOpen.value = true
}

function pick(a: Asset) {
  emit('update:modelValue', a.id)
  selectedAsset.value = a
  dialogOpen.value = false
}

function clear() {
  emit('update:modelValue', null)
  selectedAsset.value = null
}

async function handleUpload(file: UploadRawFile): Promise<boolean> {
  try {
    const a = await assetsApi.upload(file, props.kind, props.category, file.name)
    ElMessage.success('上传成功')
    pick(a)
  } catch (e: any) {
    ElMessage.error(`上传失败：${e?.message ?? e}`)
  }
  return false  // prevent auto-upload by ElUpload
}

const previewUrl = computed(() =>
  selectedAsset.value ? `${apiBase}${selectedAsset.value.url}` : null,
)
</script>

<template>
  <div class="space-y-2">
    <div v-if="label" class="text-sm font-medium text-slate-700">{{ label }}</div>
    <div class="flex gap-3 items-start">
      <!-- Preview -->
      <div
        v-if="kind === 'image' && previewUrl"
        class="w-24 h-24 border border-slate-200 rounded overflow-hidden flex-shrink-0"
      >
        <img :src="previewUrl" class="w-full h-full object-cover" />
      </div>
      <audio
        v-else-if="kind === 'audio' && previewUrl"
        :src="previewUrl"
        controls
        class="h-8 max-w-xs"
      />
      <div
        v-else
        class="w-24 h-24 border border-dashed border-slate-300 rounded flex items-center justify-center text-slate-400 text-xs"
      >
        未选择
      </div>

      <div class="flex flex-col gap-1">
        <el-button size="small" @click="openPicker">📚 选择资源</el-button>
        <el-upload
          :show-file-list="false"
          :before-upload="handleUpload"
          :accept="kind === 'image' ? 'image/*' : 'audio/*'"
        >
          <el-button size="small">⬆️ 上传</el-button>
        </el-upload>
        <el-button v-if="modelValue != null" size="small" link @click="clear">清除</el-button>
      </div>
    </div>

    <el-dialog v-model="dialogOpen" title="选择资源" width="700px">
      <div v-if="loading" class="text-slate-500">加载中…</div>
      <div v-else-if="!assets.length" class="text-slate-500 italic">
        库里暂无{{ kind === 'image' ? '图片' : '音频' }}，请上传。
      </div>
      <div v-else-if="kind === 'image'" class="grid grid-cols-4 gap-3 max-h-96 overflow-auto">
        <button
          v-for="a in assets"
          :key="a.id"
          type="button"
          class="border-2 border-transparent hover:border-blue-400 rounded overflow-hidden text-left transition"
          :class="{ 'border-blue-500': a.id === modelValue }"
          @click="pick(a)"
        >
          <img :src="`${apiBase}${a.url}`" class="w-full h-32 object-cover" />
          <div class="text-xs p-1 truncate text-slate-600">{{ a.title }}</div>
        </button>
      </div>
      <ul v-else class="space-y-2 max-h-96 overflow-auto">
        <li
          v-for="a in assets"
          :key="a.id"
          class="flex items-center gap-3 p-2 border rounded hover:bg-slate-50 cursor-pointer"
          :class="{ 'border-blue-500 bg-blue-50': a.id === modelValue }"
          @click="pick(a)"
        >
          <span class="font-medium text-sm flex-1 truncate">{{ a.title }}</span>
          <audio :src="`${apiBase}${a.url}`" controls class="h-8 flex-shrink-0" />
        </li>
      </ul>
    </el-dialog>
  </div>
</template>
