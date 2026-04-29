<script setup lang="ts">
import { ElMessage } from 'element-plus'
import SidebarNav from '@/components/SidebarNav.vue'
import { useAppStore } from '@/stores/app'

const appStore = useAppStore()

async function copyLan() {
  if (!appStore.lanUrl) return
  try {
    await navigator.clipboard.writeText(appStore.lanUrl)
    ElMessage.success('已复制到剪贴板')
  } catch {
    ElMessage.warning('请手动复制')
  }
}
</script>

<template>
  <div class="flex flex-col h-full">
    <div
      v-if="appStore.lanUrl"
      class="bg-amber-100 border-b border-amber-300 text-amber-900 px-4 py-2 text-sm flex items-center justify-between gap-3"
    >
      <span>
        <strong>📱 手机访问：</strong>
        在同一 WiFi 下，用手机浏览器打开
        <code class="bg-white/60 px-1.5 py-0.5 rounded font-mono mx-1 select-all">
          {{ appStore.lanUrl }}
        </code>
      </span>
      <button
        type="button"
        class="px-2 py-1 bg-white hover:bg-amber-50 border border-amber-300 rounded text-xs shrink-0"
        @click="copyLan"
      >复制</button>
    </div>

    <div class="flex flex-col md:flex-row flex-1 min-h-0">
      <SidebarNav />
      <main class="flex-1 overflow-auto bg-slate-50 min-h-0">
        <router-view />
      </main>
    </div>
  </div>
</template>
