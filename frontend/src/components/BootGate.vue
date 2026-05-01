<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api, pingBackend } from '@/api/client'
import { useAppStore } from '@/stores/app'

interface SystemStatus {
  backend: string
  platform: string
  ollama: { running: boolean; installed: boolean }
}

type Phase =
  | 'choose_mode'      // tauri: show welcome dialog
  | 'backend'          // waiting for /health
  | 'ollama_starting'  // ollama not yet up
  | 'ollama_missing'   // ollama install required
  | 'ready'

const appStore = useAppStore()
const phase = ref<Phase>(appStore.isTauri ? 'choose_mode' : 'backend')
const elapsed = ref(0)
const platform = ref('')
const errorDetail = ref('')

async function fetchStatus(): Promise<SystemStatus | null> {
  try {
    const r = await api.get<SystemStatus>('/system/status')
    return r.data
  } catch {
    return null
  }
}

async function ensureOllama(): Promise<boolean> {
  const st = await fetchStatus()
  if (!st) return false
  platform.value = st.platform
  if (st.ollama.running) return true

  if (!st.ollama.installed && st.platform !== 'darwin') {
    phase.value = 'ollama_missing'
    return false
  }

  phase.value = 'ollama_starting'
  try {
    await api.post('/system/ollama/start')
  } catch {
    /* ignore */
  }

  for (let i = 0; i < 60; i++) {
    await new Promise((r) => setTimeout(r, 500))
    const s = await fetchStatus()
    if (s?.ollama.running) return true
  }

  phase.value = 'ollama_missing'
  return false
}

async function bootAfterBackendStarted() {
  phase.value = 'backend'
  const start = Date.now()

  while (phase.value === 'backend') {
    if (await pingBackend(1500)) break
    elapsed.value = Math.floor((Date.now() - start) / 1000)
    await new Promise((r) => setTimeout(r, 500))
  }

  if (await ensureOllama()) {
    phase.value = 'ready'

    // 后台检查更新（不阻塞 UI）
    import('@/composables/useUpdater').then(({ useUpdater }) => {
      const { checkForUpdates } = useUpdater()
      checkForUpdates().then((info) => {
        if (info.available) {
          ElMessage({
            message: `🆕 新版本 v${info.version} 可用！打开侧栏的「⚙️ 设置」点「检查更新」安装。`,
            type: 'info',
            duration: 8000,
          })
        }
      })
    })
  }
}

async function chooseLocal() {
  if (appStore.isTauri) {
    try {
      const { invoke } = await import('@tauri-apps/api/core')
      await invoke('start_backend', { lanMode: false })
    } catch (e: any) {
      errorDetail.value = `start_backend failed: ${e.message ?? e}`
      return
    }
  }
  appStore.lanMode = false
  appStore.lanUrl = null
  await bootAfterBackendStarted()
}

async function chooseLan() {
  if (appStore.isTauri) {
    try {
      const { invoke } = await import('@tauri-apps/api/core')
      await invoke('start_backend', { lanMode: true })
      const url = await invoke<string>('get_lan_url')
      appStore.lanUrl = url
    } catch (e: any) {
      errorDetail.value = `start_backend failed: ${e.message ?? e}`
      return
    }
  }
  appStore.lanMode = true
  await bootAfterBackendStarted()
}

async function retry() {
  errorDetail.value = ''
  if (appStore.isTauri) {
    phase.value = 'choose_mode'
  } else {
    phase.value = 'backend'
    elapsed.value = 0
    await bootAfterBackendStarted()
  }
}

onMounted(async () => {
  if (!appStore.isTauri) {
    // Browser dev mode — backend is already running externally.
    await bootAfterBackendStarted()
  }
  // Tauri mode — wait for user to click a button in the welcome dialog.
})
</script>

<template>
  <slot v-if="phase === 'ready'" />

  <div v-else-if="phase === 'choose_mode'"
       class="h-full flex items-center justify-center bg-slate-50 px-6">
    <div class="max-w-xl w-full space-y-6">
      <div class="text-center space-y-2">
        <div class="text-3xl font-bold text-slate-800">欢迎使用 dzmm</div>
        <div class="text-sm text-slate-500">启动前选一个模式</div>
      </div>

      <div class="grid grid-cols-1 gap-3">
        <button
          type="button"
          class="text-left bg-white hover:bg-slate-100 active:bg-slate-200 border border-slate-200 rounded-lg p-5 transition shadow-sm"
          @click="chooseLocal"
        >
          <div class="font-bold text-lg text-slate-800 mb-1">仅本机使用</div>
          <div class="text-sm text-slate-500">
            后端只监听本机 127.0.0.1，最安全。
          </div>
        </button>

        <button
          type="button"
          class="text-left bg-amber-50 hover:bg-amber-100 active:bg-amber-200 border border-amber-300 rounded-lg p-5 transition shadow-sm"
          @click="chooseLan"
        >
          <div class="font-bold text-lg text-amber-900 mb-1">
            启用手机访问 <span class="text-xs font-normal text-amber-700 ml-1">(同 WiFi)</span>
          </div>
          <div class="text-sm text-amber-800">
            后端监听 0.0.0.0，启动后会显示手机要访问的地址。
            <strong>仅在你信任当前网络时使用</strong>（家里 WiFi OK，咖啡店 WiFi 别开）。
          </div>
        </button>
      </div>

      <div v-if="errorDetail"
           class="bg-red-50 border border-red-200 text-red-700 text-sm p-3 rounded">
        {{ errorDetail }}
      </div>
    </div>
  </div>

  <div v-else-if="phase === 'backend'"
       class="h-full flex items-center justify-center bg-slate-50">
    <div class="text-center space-y-3 max-w-sm">
      <div class="text-2xl font-bold text-slate-700">正在启动后端…</div>
      <div class="text-sm text-slate-500">
        首次启动需要解压依赖，通常 5–25 秒（已等待 {{ elapsed }}s）
      </div>
      <el-progress :percentage="Math.min(elapsed * 5, 95)" :show-text="false" />
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
