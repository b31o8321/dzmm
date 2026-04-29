<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { pingBackend } from '@/api/client'

const ready = ref(false)
const elapsed = ref(0)

async function waitForBackend() {
  const start = Date.now()
  while (!ready.value) {
    if (await pingBackend(1500)) {
      ready.value = true
      return
    }
    elapsed.value = Math.floor((Date.now() - start) / 1000)
    await new Promise((r) => setTimeout(r, 500))
  }
}

onMounted(waitForBackend)
</script>

<template>
  <slot v-if="ready" />
  <div v-else class="h-full flex items-center justify-center bg-slate-50">
    <div class="text-center space-y-3">
      <div class="text-2xl font-bold text-slate-700">正在启动后端…</div>
      <div class="text-sm text-slate-500">
        首次启动需要解压依赖，通常 5–10 秒（已等待 {{ elapsed }}s）
      </div>
      <el-progress :percentage="Math.min(elapsed * 10, 95)" :show-text="false" />
    </div>
  </div>
</template>
