<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api, pingBackend } from '@/api/client'

interface SystemStatus {
  backend: string
  platform: string
  ollama: { running: boolean; installed: boolean }
}

type Phase = 'backend' | 'ollama_starting' | 'ollama_missing' | 'ready'

const phase = ref<Phase>('backend')
const elapsed = ref(0)
const platform = ref('')

async function fetchStatus(): Promise<SystemStatus | null> {
  try {
    const r = await api.get<SystemStatus>('/system/status')
    return r.data
  } catch {
    return null
  }
}

async function ensureOllama(): Promise<boolean> {
  // Try once to launch Ollama if it's installed but not running.
  const st = await fetchStatus()
  if (!st) return false
  platform.value = st.platform
  if (st.ollama.running) return true

  if (!st.ollama.installed && st.platform !== 'darwin') {
    // On macOS the .app may exist without ollama on PATH; we still try to launch.
    phase.value = 'ollama_missing'
    return false
  }

  phase.value = 'ollama_starting'
  try {
    await api.post('/system/ollama/start')
  } catch {
    /* ignore */
  }

  // Poll up to 30s for Ollama to come up.
  for (let i = 0; i < 60; i++) {
    await new Promise((r) => setTimeout(r, 500))
    const s = await fetchStatus()
    if (s?.ollama.running) return true
  }

  phase.value = 'ollama_missing'
  return false
}

async function boot() {
  const start = Date.now()

  // Phase 1: backend up
  while (phase.value === 'backend') {
    if (await pingBackend(1500)) break
    elapsed.value = Math.floor((Date.now() - start) / 1000)
    await new Promise((r) => setTimeout(r, 500))
  }

  // Phase 2: ollama up (auto-launch if needed)
  if (await ensureOllama()) {
    phase.value = 'ready'
  }
  // else stays in 'ollama_missing' — user takes manual action then clicks retry
}

async function retry() {
  phase.value = 'backend'
  elapsed.value = 0
  await boot()
}

onMounted(boot)
</script>

<template>
  <slot v-if="phase === 'ready'" />

  <div v-else-if="phase === 'backend'"
       class="h-full flex items-center justify-center bg-slate-50">
    <div class="text-center space-y-3 max-w-sm">
      <div class="text-2xl font-bold text-slate-700">正在启动后端…</div>
      <div class="text-sm text-slate-500">
        首次启动需要解压依赖，通常 5–10 秒（已等待 {{ elapsed }}s）
      </div>
      <el-progress :percentage="Math.min(elapsed * 10, 95)" :show-text="false" />
    </div>
  </div>

  <div v-else-if="phase === 'ollama_starting'"
       class="h-full flex items-center justify-center bg-slate-50">
    <div class="text-center space-y-3 max-w-sm">
      <div class="text-2xl font-bold text-slate-700">正在启动 Ollama…</div>
      <div class="text-sm text-slate-500">
        AI 模型服务正在加载（可能需要 5–20 秒）
      </div>
      <el-progress :percentage="50" :show-text="false" :indeterminate="true" />
    </div>
  </div>

  <div v-else class="h-full flex items-center justify-center bg-slate-50">
    <div class="text-center space-y-4 max-w-md">
      <div class="text-2xl font-bold text-slate-700">需要 Ollama</div>
      <div class="text-sm text-slate-600 space-y-2">
        <p>本地 AI 模型服务 <strong>Ollama</strong> 没有运行。</p>
        <p v-if="platform === 'darwin'">
          请到 <a href="https://ollama.com/download" target="_blank"
                class="text-blue-600 underline">ollama.com/download</a> 下载安装，
          然后再点重试。
        </p>
        <p v-else-if="platform === 'win32'">
          请到 <a href="https://ollama.com/download" target="_blank"
                class="text-blue-600 underline">ollama.com/download</a> 下载 Windows 安装包，
          安装后会自动启动后台服务，然后再点重试。
        </p>
        <p v-else>
          请安装 Ollama 后再启动本应用：
          <code>curl -fsSL https://ollama.com/install.sh | sh</code>
        </p>
        <p class="text-xs text-slate-500 pt-2">
          首次安装后还需要拉一个模型，例如 <code>ollama pull qwen2.5:7b</code>
        </p>
      </div>
      <el-button type="primary" @click="retry">重试</el-button>
    </div>
  </div>
</template>
