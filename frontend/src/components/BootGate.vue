<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { ElMessage, ElDialog, ElButton } from 'element-plus'
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

// Boot log: timestamped events from frontend + Tauri-spawned backend stdout/stderr.
interface LogEntry {
  ts: number          // unix ms
  source: 'frontend' | 'stdout' | 'stderr' | 'system'
  level: 'info' | 'warn' | 'error'
  msg: string
}
const bootLog = ref<LogEntry[]>([])
const logDialogOpen = ref(false)

function logIt(source: LogEntry['source'], level: LogEntry['level'], msg: string) {
  bootLog.value.push({ ts: Date.now(), source, level, msg })
  // Cap so a stuck loop doesn't OOM us.
  if (bootLog.value.length > 500) bootLog.value.splice(0, bootLog.value.length - 500)
}

function fmt(e: LogEntry): string {
  const t = new Date(e.ts).toISOString().substring(11, 23)  // HH:MM:SS.mmm
  const tag = e.source === 'frontend' ? 'FE' : e.source.toUpperCase()
  return `[${t}] [${tag}] ${e.msg}`
}

async function copyLog() {
  const text = bootLog.value.map(fmt).join('\n')
  try {
    await navigator.clipboard.writeText(text)
    ElMessage.success('已复制到剪贴板')
  } catch {
    ElMessage.warning('复制失败，请手动选中复制')
  }
}

let unlistenBackendLog: (() => void) | null = null
async function attachTauriBackendLog() {
  if (!appStore.isTauri) return
  try {
    const { listen } = await import('@tauri-apps/api/event')
    unlistenBackendLog = await listen<{ stream: string; line: string; ts_ms: number }>(
      'backend-log',
      (event) => {
        const p = event.payload
        const source = (p.stream === 'stdout' || p.stream === 'stderr' || p.stream === 'system')
          ? p.stream as LogEntry['source']
          : 'system'
        const level: LogEntry['level'] = p.stream === 'stderr' ? 'warn' : 'info'
        bootLog.value.push({
          ts: p.ts_ms || Date.now(),
          source,
          level,
          msg: p.line,
        })
        if (bootLog.value.length > 500) {
          bootLog.value.splice(0, bootLog.value.length - 500)
        }
      },
    )
    logIt('frontend', 'info', 'Tauri backend-log 监听已建立')
  } catch (e: any) {
    logIt('frontend', 'warn', `Tauri 事件监听不可用: ${e?.message ?? e}`)
  }
}

async function fetchStatus(): Promise<SystemStatus | null> {
  try {
    const r = await api.get<SystemStatus>('/system/status')
    return r.data
  } catch (e: any) {
    logIt('frontend', 'warn', `/system/status 失败: ${e?.message ?? e}`)
    return null
  }
}

async function ensureOllama(): Promise<boolean> {
  logIt('frontend', 'info', '查询 Ollama 状态…')
  const st = await fetchStatus()
  if (!st) {
    logIt('frontend', 'error', 'Ollama 状态查询失败（后端无响应）')
    return false
  }
  platform.value = st.platform
  logIt('frontend', 'info', `平台=${st.platform}, ollama 已安装=${st.ollama.installed}, 运行中=${st.ollama.running}`)
  if (st.ollama.running) return true

  if (!st.ollama.installed && st.platform !== 'darwin') {
    logIt('frontend', 'warn', 'Ollama 未安装且非 macOS，无法自动安装')
    phase.value = 'ollama_missing'
    return false
  }

  phase.value = 'ollama_starting'
  logIt('frontend', 'info', '尝试启动 Ollama…')
  try {
    await api.post('/system/ollama/start')
    logIt('frontend', 'info', '已请求 Ollama 启动')
  } catch (e: any) {
    logIt('frontend', 'warn', `Ollama 启动请求失败: ${e?.message ?? e}`)
  }

  for (let i = 0; i < 60; i++) {
    await new Promise((r) => setTimeout(r, 500))
    const s = await fetchStatus()
    if (s?.ollama.running) {
      logIt('frontend', 'info', `Ollama 启动成功（轮询 ${i + 1} 次）`)
      return true
    }
  }

  logIt('frontend', 'error', 'Ollama 60 次轮询仍未运行，放弃')
  phase.value = 'ollama_missing'
  return false
}

async function bootAfterBackendStarted() {
  phase.value = 'backend'
  const start = Date.now()
  logIt('frontend', 'info', '开始等待后端 /health 响应…')

  let pingCount = 0
  while (phase.value === 'backend') {
    pingCount += 1
    if (await pingBackend(1500)) {
      logIt('frontend', 'info', `后端响应正常（共 ping ${pingCount} 次）`)
      break
    }
    elapsed.value = Math.floor((Date.now() - start) / 1000)
    if (pingCount % 6 === 0) {
      // Every ~3s log a summary so the user can see we're still alive.
      logIt('frontend', 'info', `已等待 ${elapsed.value}s，后端 /health 仍未响应（ping ${pingCount} 次）`)
    }
    await new Promise((r) => setTimeout(r, 500))
  }

  if (await ensureOllama()) {
    phase.value = 'ready'
    logIt('frontend', 'info', '✅ 启动完成')

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
    logIt('frontend', 'info', '用户选择仅本机模式，调用 start_backend(lanMode=false)')
    try {
      const { invoke } = await import('@tauri-apps/api/core')
      await invoke('start_backend', { lanMode: false })
      logIt('frontend', 'info', 'start_backend 命令成功返回')
    } catch (e: any) {
      const msg = `start_backend failed: ${e.message ?? e}`
      logIt('frontend', 'error', msg)
      errorDetail.value = msg
      return
    }
  }
  appStore.lanMode = false
  appStore.lanUrl = null
  await bootAfterBackendStarted()
}

async function chooseLan() {
  if (appStore.isTauri) {
    logIt('frontend', 'info', '用户选择 LAN 模式，调用 start_backend(lanMode=true)')
    try {
      const { invoke } = await import('@tauri-apps/api/core')
      await invoke('start_backend', { lanMode: true })
      const url = await invoke<string>('get_lan_url')
      appStore.lanUrl = url
      logIt('frontend', 'info', `LAN URL: ${url}`)
    } catch (e: any) {
      const msg = `start_backend failed: ${e.message ?? e}`
      logIt('frontend', 'error', msg)
      errorDetail.value = msg
      return
    }
  }
  appStore.lanMode = true
  await bootAfterBackendStarted()
}

async function retry() {
  errorDetail.value = ''
  logIt('frontend', 'info', '用户点击重试')
  if (appStore.isTauri) {
    phase.value = 'choose_mode'
  } else {
    phase.value = 'backend'
    elapsed.value = 0
    await bootAfterBackendStarted()
  }
}

onMounted(async () => {
  logIt('frontend', 'info', `BootGate 挂载，模式=${appStore.isTauri ? 'tauri' : 'browser'}`)
  await attachTauriBackendLog()
  if (!appStore.isTauri) {
    // Browser dev mode — backend is already running externally.
    await bootAfterBackendStarted()
  }
  // Tauri mode — wait for user to click a button in the welcome dialog.
})

onUnmounted(() => {
  if (unlistenBackendLog) unlistenBackendLog()
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

      <div class="text-center">
        <el-button size="small" link @click="logDialogOpen = true">
          📋 启动日志（{{ bootLog.length }} 条）
        </el-button>
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
      <div class="pt-2">
        <el-button size="small" @click="logDialogOpen = true">
          📋 查看启动日志（{{ bootLog.length }} 条）
        </el-button>
      </div>
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
      <div class="pt-2">
        <el-button size="small" @click="logDialogOpen = true">
          📋 查看启动日志（{{ bootLog.length }} 条）
        </el-button>
      </div>
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
      <div>
        <el-button size="small" link @click="logDialogOpen = true">
          📋 启动日志（{{ bootLog.length }} 条）
        </el-button>
      </div>
    </div>
  </div>

  <!-- 启动日志弹窗 -->
  <el-dialog
    v-model="logDialogOpen"
    title="启动日志"
    width="780px"
  >
    <div class="text-xs text-slate-500 mb-2">
      展示前端启动流程的每一步 + Tauri 端 spawn 的后端 stdout/stderr。
      启动卡住时把这些发给我帮你定位问题。
    </div>
    <div class="bg-slate-900 text-slate-100 rounded p-3 text-xs font-mono whitespace-pre-wrap overflow-auto max-h-[60vh]">
      <template v-if="bootLog.length === 0">
        （暂无日志）
      </template>
      <div
        v-for="(e, i) in bootLog"
        :key="i"
        :class="{
          'text-red-400': e.level === 'error' || e.source === 'stderr',
          'text-yellow-300': e.level === 'warn' && e.source !== 'stderr',
          'text-slate-300': e.level === 'info' && e.source === 'frontend',
          'text-emerald-300': e.source === 'stdout',
          'text-slate-500': e.source === 'system',
        }"
      >{{ fmt(e) }}</div>
    </div>
    <template #footer>
      <el-button @click="copyLog">📋 复制全部</el-button>
      <el-button @click="bootLog = []">清空</el-button>
      <el-button type="primary" @click="logDialogOpen = false">关闭</el-button>
    </template>
  </el-dialog>
</template>
