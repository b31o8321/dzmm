<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import {
  ElAlert,
  ElButton,
  ElCard,
  ElCheckbox,
  ElEmpty,
  ElMessage,
  ElMessageBox,
  ElTag,
} from 'element-plus'
import QRCode from 'qrcode'

import { fetchHealth } from '@/api/client'
import {
  remoteApi,
  type PairedDevice,
  type PinPairingWindow,
  type QrPairingWindow,
  type RemoteAdminStatus,
  type RemotePairRequest,
} from '@/api/remote'
import { useAppStore } from '@/stores/app'

const appStore = useAppStore()
const loading = ref(true)
const refreshing = ref(false)
const errorMessage = ref('')
const trustedNetwork = ref(false)
const adminStatus = ref<RemoteAdminStatus | null>(null)
const pairRequests = ref<RemotePairRequest[]>([])
const devices = ref<PairedDevice[]>([])
const pinWindow = ref<PinPairingWindow | null>(null)
const qrWindow = ref<QrPairingWindow | null>(null)
const qrDataUrl = ref('')
const now = ref(Date.now())

const remoteEnabled = computed(() => appStore.backendMode === 'remote')
const transitioning = computed(() =>
  appStore.backendMode === 'starting' || appStore.backendMode === 'restarting',
)
const hostStateLabel = computed(() => {
  const labels: Record<string, string> = {
    stopped: '已停止',
    starting: '正在启动',
    local: '仅本机',
    remote: '局域网已开放',
    restarting: '正在切换',
    error: '启动异常',
  }
  return labels[appStore.backendMode] ?? '未知'
})
const hostStateType = computed(() => {
  if (appStore.backendMode === 'remote') return 'warning'
  if (appStore.backendMode === 'error') return 'danger'
  if (transitioning.value) return 'info'
  return 'success'
})

function remaining(expiresAt: string): number {
  return Math.max(0, Math.ceil((new Date(expiresAt).getTime() - now.value) / 1000))
}

function expiryLabel(expiresAt: string): string {
  const seconds = remaining(expiresAt)
  const minutes = Math.floor(seconds / 60)
  return `${minutes}:${String(seconds % 60).padStart(2, '0')}`
}

function formatTime(value: string | null): string {
  if (!value) return '尚未连接'
  return new Date(value).toLocaleString('zh-CN', { hour12: false })
}

async function copyText(value: string, label: string) {
  try {
    await navigator.clipboard.writeText(value)
    ElMessage.success(`${label}已复制`)
  } catch {
    ElMessage.warning('复制失败，请手动复制')
  }
}

async function loadAdminData() {
  const [status, pending, paired] = await Promise.all([
    remoteApi.status(),
    remoteApi.pairRequests(),
    remoteApi.devices(),
  ])
  adminStatus.value = status
  pairRequests.value = pending
  devices.value = paired
}

async function refresh(options: { quiet?: boolean } = {}) {
  if (refreshing.value) return
  refreshing.value = true
  if (!options.quiet) errorMessage.value = ''
  try {
    if (appStore.isTauri) await appStore.refreshBackendStatus()
    const health = await fetchHealth()
    if (!health) throw new Error('后端健康检查无响应')
    if (!appStore.isTauri) {
      appStore.backendMode = health.remote_access ? 'remote' : 'local'
    }
    await loadAdminData()
    errorMessage.value = ''
  } catch (error: any) {
    if (!options.quiet || !adminStatus.value) {
      errorMessage.value = error?.message ?? String(error)
    }
  } finally {
    refreshing.value = false
    loading.value = false
  }
}

async function waitForBackendMode(expectedRemote: boolean): Promise<void> {
  const deadline = Date.now() + 30_000
  while (Date.now() < deadline) {
    const health = await fetchHealth(750)
    if (health?.remote_access === expectedRemote) return
    await new Promise((resolve) => setTimeout(resolve, 250))
  }
  throw new Error('后端重启后未在 30 秒内恢复，请查看启动日志')
}

async function enableRemoteAccess() {
  if (!trustedNetwork.value) return
  errorMessage.value = ''
  try {
    await appStore.setRemoteAccess(true)
    await waitForBackendMode(true)
    await refresh()
    ElMessage.success('局域网访问已开启')
  } catch (error: any) {
    errorMessage.value = error?.message ?? String(error)
  }
}

async function disableRemoteAccess() {
  try {
    await ElMessageBox.confirm(
      '关闭后，手机会立即断开；已配对设备仍会保留。',
      '关闭局域网访问？',
      { confirmButtonText: '关闭访问', cancelButtonText: '取消', type: 'warning' },
    )
  } catch {
    return
  }
  errorMessage.value = ''
  try {
    await appStore.setRemoteAccess(false)
    await waitForBackendMode(false)
    pinWindow.value = null
    qrWindow.value = null
    qrDataUrl.value = ''
    await refresh()
    ElMessage.success('已恢复为仅本机模式')
  } catch (error: any) {
    errorMessage.value = error?.message ?? String(error)
  }
}

async function openPin() {
  try {
    pinWindow.value = await remoteApi.openPin()
  } catch (error: any) {
    errorMessage.value = error?.message ?? String(error)
  }
}

async function createQr() {
  try {
    const window = await remoteApi.createQr()
    if (!adminStatus.value) await loadAdminData()
    const payload = JSON.stringify({
      type: 'dzmm_pair',
      version: 1,
      server_id: adminStatus.value?.server_id,
      api_version: 1,
      hosts: appStore.lanAddresses,
      claim: window.claim,
    })
    qrDataUrl.value = await QRCode.toDataURL(payload, {
      width: 224,
      margin: 1,
      color: { dark: '#0f172a', light: '#ffffff' },
    })
    qrWindow.value = window
  } catch (error: any) {
    errorMessage.value = error?.message ?? String(error)
  }
}

async function decideRequest(requestId: string, approve: boolean) {
  try {
    if (approve) await remoteApi.approveRequest(requestId)
    else await remoteApi.denyRequest(requestId)
    await loadAdminData()
    ElMessage.success(approve ? '设备已批准' : '配对请求已拒绝')
  } catch (error: any) {
    errorMessage.value = error?.message ?? String(error)
  }
}

async function revokeDevice(device: PairedDevice) {
  try {
    await ElMessageBox.confirm(
      `撤销后，“${device.name}”需要重新配对才能连接。`,
      '撤销设备？',
      { confirmButtonText: '撤销设备', cancelButtonText: '取消', type: 'warning' },
    )
  } catch {
    return
  }
  try {
    await remoteApi.revokeDevice(device.device_id)
    await loadAdminData()
    ElMessage.success('设备访问权限已撤销')
  } catch (error: any) {
    errorMessage.value = error?.message ?? String(error)
  }
}

let pollTimer: ReturnType<typeof setInterval> | null = null
let clockTimer: ReturnType<typeof setInterval> | null = null

onMounted(async () => {
  await refresh()
  pollTimer = setInterval(() => refresh({ quiet: true }), 3000)
  clockTimer = setInterval(() => {
    now.value = Date.now()
    if (pinWindow.value && remaining(pinWindow.value.expires_at) === 0) pinWindow.value = null
    if (qrWindow.value && remaining(qrWindow.value.expires_at) === 0) {
      qrWindow.value = null
      qrDataUrl.value = ''
    }
  }, 1000)
})

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
  if (clockTimer) clearInterval(clockTimer)
})
</script>

<template>
  <el-card class="remote-access-card" data-testid="remote-access-card">
    <template #header>
      <div class="flex items-center justify-between gap-4">
        <div class="flex items-center gap-3">
          <span class="host-beacon" :class="{ 'host-beacon--remote': remoteEnabled }" aria-hidden="true">
            <span />
          </span>
          <div>
            <strong class="block text-slate-800">手机局域网访问</strong>
            <span class="text-xs text-slate-500">Mac 保留模型和存档，手机只进入跑团</span>
          </div>
        </div>
        <el-tag :type="hostStateType" effect="light" data-testid="backend-mode">
          {{ hostStateLabel }}
        </el-tag>
      </div>
    </template>

    <div v-if="loading" class="py-8 text-center text-sm text-slate-500">正在读取主机状态…</div>

    <div v-else class="space-y-5">
      <el-alert
        v-if="!appStore.isTauri"
        type="info"
        :closable="false"
        title="请在 dzmm Mac 应用中控制局域网访问；浏览器开发模式只显示当前状态。"
      />
      <el-alert
        v-if="errorMessage || appStore.backendError"
        type="error"
        :closable="false"
        :title="errorMessage || appStore.backendError || '主机状态异常'"
      >
        <template #default>
          <el-button size="small" class="mt-2" @click="refresh()">重新读取</el-button>
        </template>
      </el-alert>

      <section class="rounded-lg border border-slate-200 bg-slate-50 p-4">
        <div class="flex items-start justify-between gap-4">
          <div>
            <div class="text-sm font-semibold text-slate-800">
              {{ remoteEnabled ? '同一局域网中的已配对手机可以连接' : '后端只监听这台 Mac' }}
            </div>
            <p class="mt-1 text-xs leading-5 text-slate-500">
              {{ remoteEnabled
                ? '模型、世界观、向导和调试接口仍只允许本机访问。'
                : '每次打开应用都会从仅本机模式开始，不会自动暴露到新网络。' }}
            </p>
          </div>
          <el-button
            v-if="remoteEnabled"
            type="danger"
            plain
            :loading="transitioning"
            :disabled="!appStore.isTauri"
            @click="disableRemoteAccess"
          >关闭访问</el-button>
        </div>

        <template v-if="!remoteEnabled">
          <el-checkbox v-model="trustedNetwork" class="mt-4" :disabled="!appStore.isTauri">
            我确认当前是可信网络（例如家中 Wi-Fi）
          </el-checkbox>
          <div class="mt-3">
            <el-button
              type="primary"
              :loading="transitioning"
              :disabled="!appStore.isTauri || !trustedNetwork"
              @click="enableRemoteAccess"
            >开启局域网访问</el-button>
          </div>
        </template>
      </section>

      <section v-if="remoteEnabled" class="space-y-3">
        <div class="section-title">连接地址</div>
        <div v-if="appStore.lanAddresses.length" class="space-y-2">
          <button
            v-for="address in appStore.lanAddresses"
            :key="address"
            type="button"
            class="address-row"
            @click="copyText(address, '地址')"
          >
            <code>{{ address }}</code>
            <span>复制</span>
          </button>
        </div>
        <el-alert v-else type="warning" :closable="false" title="没有检测到可用的 IPv4 局域网地址" />
      </section>

      <section v-if="remoteEnabled" class="space-y-3">
        <div class="flex items-center justify-between gap-3">
          <div class="section-title">配对新手机</div>
          <div class="flex gap-2">
            <el-button size="small" @click="openPin">生成 PIN</el-button>
            <el-button size="small" type="primary" @click="createQr">生成二维码</el-button>
          </div>
        </div>

        <div v-if="pinWindow" class="pairing-panel">
          <div>
            <div class="text-xs text-slate-500">手机输入 6 位 PIN</div>
            <button class="pin-code" type="button" @click="copyText(pinWindow.pin, 'PIN')">
              {{ pinWindow.pin }}
            </button>
          </div>
          <el-tag type="warning">剩余 {{ expiryLabel(pinWindow.expires_at) }}</el-tag>
        </div>

        <div v-if="qrWindow && qrDataUrl" class="pairing-panel items-center">
          <img :src="qrDataUrl" width="180" height="180" alt="dzmm 手机配对二维码" class="rounded bg-white p-2" />
          <div class="space-y-2 text-xs leading-5 text-slate-500">
            <div>用 dzmm Android 扫描。二维码只包含一次性 claim、主机身份和局域网地址。</div>
            <el-tag type="warning">剩余 {{ expiryLabel(qrWindow.expires_at) }}</el-tag>
          </div>
        </div>
      </section>

      <section v-if="remoteEnabled" class="space-y-3">
        <div class="section-title">待确认请求</div>
        <div v-if="pairRequests.length" class="space-y-2">
          <div v-for="request in pairRequests" :key="request.request_id" class="device-row">
            <div class="min-w-0">
              <div class="truncate text-sm font-medium text-slate-800">{{ request.device_name }}</div>
              <div class="text-xs text-slate-500">{{ request.client_ip }} · {{ expiryLabel(request.expires_at) }} 后过期</div>
            </div>
            <div class="flex shrink-0 gap-2">
              <el-button size="small" @click="decideRequest(request.request_id, false)">拒绝</el-button>
              <el-button size="small" type="primary" @click="decideRequest(request.request_id, true)">批准</el-button>
            </div>
          </div>
        </div>
        <div v-else class="empty-copy">没有等待确认的手机。也可以直接使用上方二维码或 PIN。</div>
      </section>

      <section class="space-y-3">
        <div class="section-title">已配对设备</div>
        <div v-if="devices.length" class="space-y-2">
          <div v-for="device in devices" :key="device.device_id" class="device-row">
            <div class="min-w-0">
              <div class="truncate text-sm font-medium text-slate-800">{{ device.name }}</div>
              <div class="text-xs text-slate-500">最近连接：{{ formatTime(device.last_seen) }}</div>
            </div>
            <el-button size="small" type="danger" text @click="revokeDevice(device)">撤销</el-button>
          </div>
        </div>
        <el-empty v-else :image-size="48" description="还没有配对设备" />
      </section>
    </div>
  </el-card>
</template>

<style scoped>
.host-beacon {
  display: grid;
  width: 2.25rem;
  height: 2.25rem;
  flex: 0 0 auto;
  place-items: center;
  border: 1px solid #cbd5e1;
  border-radius: 9999px;
  background: #f8fafc;
}

.host-beacon span {
  width: 0.625rem;
  height: 0.625rem;
  border-radius: 9999px;
  background: #64748b;
}

.host-beacon--remote {
  border-color: #f59e0b;
  background: #fffbeb;
  box-shadow: 0 0 0 5px rgb(245 158 11 / 10%);
}

.host-beacon--remote span {
  background: #d97706;
  animation: beacon-pulse 2.2s ease-out infinite;
}

.section-title {
  font-size: 0.75rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  color: #475569;
  text-transform: uppercase;
}

.address-row,
.device-row,
.pairing-panel {
  display: flex;
  width: 100%;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  border: 1px solid #e2e8f0;
  border-radius: 0.625rem;
  background: #fff;
  padding: 0.75rem 0.875rem;
}

.address-row {
  color: #334155;
  text-align: left;
  transition: border-color 150ms ease, background-color 150ms ease;
}

.address-row:hover,
.address-row:focus-visible {
  border-color: #94a3b8;
  background: #f8fafc;
  outline: none;
}

.address-row span {
  font-size: 0.75rem;
  color: #64748b;
}

.pairing-panel {
  align-items: flex-start;
  background: #f8fafc;
}

.pin-code {
  margin-top: 0.25rem;
  color: #0f172a;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 1.75rem;
  font-weight: 700;
  letter-spacing: 0.22em;
}

.pin-code:focus-visible {
  border-radius: 0.25rem;
  outline: 2px solid #f59e0b;
  outline-offset: 3px;
}

.empty-copy {
  border: 1px dashed #cbd5e1;
  border-radius: 0.625rem;
  padding: 0.875rem;
  color: #64748b;
  font-size: 0.8125rem;
  line-height: 1.25rem;
}

@keyframes beacon-pulse {
  0% { box-shadow: 0 0 0 0 rgb(217 119 6 / 35%); }
  70%, 100% { box-shadow: 0 0 0 8px rgb(217 119 6 / 0%); }
}

@media (prefers-reduced-motion: reduce) {
  .host-beacon--remote span { animation: none; }
}

@media (max-width: 640px) {
  .device-row,
  .pairing-panel {
    align-items: flex-start;
    flex-direction: column;
  }
}
</style>
