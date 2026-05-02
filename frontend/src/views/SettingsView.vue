<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElButton, ElCard, ElMessage, ElTag, ElDivider } from 'element-plus'
import { useUpdater, type UpdateInfo } from '@/composables/useUpdater'
import { useAppStore } from '@/stores/app'
import { fetchHealth } from '@/api/client'
import TtsSettingsCard from '@/components/TtsSettingsCard.vue'

const { checkForUpdates, downloadAndInstall } = useUpdater()
const appStore = useAppStore()

const frontendVersion = __APP_VERSION__
const backendVersion = ref<string | null>(null)

const checking = ref(false)
const installing = ref(false)
const update = ref<UpdateInfo>({ available: false })

onMounted(async () => {
  const h = await fetchHealth()
  backendVersion.value = h?.version ?? null
})

async function onCheck() {
  if (!appStore.isTauri) {
    ElMessage.info('自动更新仅在桌面端可用（开发 / 浏览器模式无效）')
    return
  }
  checking.value = true
  try {
    const info = await checkForUpdates()
    update.value = info
    if (!info.available) ElMessage.success('当前已是最新版本')
    else ElMessage.warning(`发现新版本 v${info.version}`)
  } catch (e: any) {
    ElMessage.error(`检查失败：${e?.message ?? e}`)
  } finally {
    checking.value = false
  }
}

async function onInstall() {
  installing.value = true
  try {
    await downloadAndInstall()
    // relaunch 之后这段不会执行
  } catch (e: any) {
    ElMessage.error(`安装失败：${e?.message ?? e}`)
  } finally {
    installing.value = false
  }
}

function replayOnboarding() {
  appStore.tourCompleted = false
  appStore.tourStep = 0
  // 刷新到 /welcome
  window.location.href = '#/welcome'
  window.location.reload()
}
</script>

<template>
  <div class="h-full overflow-auto p-6 max-w-2xl mx-auto space-y-4">
    <header class="flex items-center justify-between">
      <h1 class="text-2xl font-bold text-slate-800">⚙️ 设置</h1>
    </header>

    <!-- 版本 + 更新 -->
    <el-card>
      <template #header>
        <strong>版本与更新</strong>
      </template>
      <div class="space-y-2 text-sm">
        <div>
          前端：<el-tag size="small">v{{ frontendVersion }}</el-tag>
          后端：<el-tag
            v-if="backendVersion"
            size="small"
            :type="backendVersion === frontendVersion ? 'success' : 'danger'"
          >v{{ backendVersion }}</el-tag>
          <el-tag v-else size="small" type="info">未连接</el-tag>
        </div>

        <div v-if="backendVersion && backendVersion !== frontendVersion"
             class="bg-red-50 border border-red-200 rounded p-2 text-xs text-red-700">
          ⚠️ 前后端版本不一致。源码构建请重打包：<code>python packaging/build.py</code>
        </div>

        <div class="pt-2 flex flex-wrap gap-2 items-center">
          <el-button :loading="checking" @click="onCheck">🔄 检查更新</el-button>
          <el-button
            v-if="update.available"
            type="primary"
            :loading="installing"
            @click="onInstall"
          >
            📥 下载并安装 v{{ update.version }}
          </el-button>
          <span v-if="!appStore.isTauri" class="text-xs text-slate-400">
            （仅桌面端有效）
          </span>
        </div>

        <div v-if="update.available && update.body"
             class="bg-slate-50 border border-slate-200 rounded p-3 text-xs whitespace-pre-wrap mt-2">
          <strong>更新说明：</strong>{{ '\n' }}{{ update.body }}
        </div>
      </div>
    </el-card>

    <!-- 引导 -->
    <el-card>
      <template #header>
        <strong>引导 / 帮助</strong>
      </template>
      <div class="space-y-2 text-sm">
        <div class="text-slate-600">
          首次启动时的 4 分钟引导可以重新查看。
        </div>
        <el-button @click="replayOnboarding">🔄 重新查看引导</el-button>
        <router-link to="/help" class="ml-2 text-blue-600 hover:underline text-sm">
          📖 打开说明 / 帮助页
        </router-link>
      </div>
    </el-card>

    <!-- TTS -->
    <TtsSettingsCard />

  </div>
</template>
