<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useAppStore } from '@/stores/app'
import { useModelConfigsStore } from '@/stores/modelConfigs'
import { backendOrigin } from '@/api/client'
import { useTTS } from '@/composables/useTTS'

const appStore = useAppStore()
const modelsStore = useModelConfigsStore()
const { previewVoice, speaking, stop } = useTTS()
const previewText = ref('天地玄黄，宇宙洪荒。日月盈昃，辰宿列张。')

// edge-tts voices
const edgeVoices = ref<{ voice: string; label: string }[]>([])

// cosyvoice
interface CosyStatus {
  installed: boolean
  running: boolean
  port: number
  installing: boolean
  install_log: string[]
  install_error: string
}
const cosyStatus = ref<CosyStatus | null>(null)
let cosyPollTimer: ReturnType<typeof setInterval> | null = null
const showCosyLog = ref(false)

const COSY_TOTAL_STEPS = 8
const cosyInstallPct = computed(() => {
  if (!cosyStatus.value?.installing && cosyStatus.value?.installed) return 100
  const n = cosyStatus.value?.install_log?.length ?? 0
  return Math.min(Math.round((n / COSY_TOTAL_STEPS) * 95), 95)
})

onMounted(async () => {
  await modelsStore.refresh()
  try {
    const r = await fetch(`${backendOrigin}/tts/voices`)
    if (r.ok) edgeVoices.value = await r.json()
  } catch { /* ignore */ }
  await refreshCosyStatus()
})

onUnmounted(() => {
  if (cosyPollTimer) clearInterval(cosyPollTimer)
})

async function refreshCosyStatus() {
  try {
    const r = await fetch(`${backendOrigin}/tts/cosyvoice/status`)
    if (r.ok) cosyStatus.value = await r.json()
  } catch { /* ignore */ }
}

async function cosyInstall() {
  await fetch(`${backendOrigin}/tts/cosyvoice/install`, { method: 'POST' })
  showCosyLog.value = true
  if (cosyPollTimer) clearInterval(cosyPollTimer)
  cosyPollTimer = setInterval(async () => {
    await refreshCosyStatus()
    if (cosyStatus.value && !cosyStatus.value.installing) {
      clearInterval(cosyPollTimer!)
      cosyPollTimer = null
    }
  }, 2000)
  await refreshCosyStatus()
}

async function cosyStart() {
  const r = await fetch(`${backendOrigin}/tts/cosyvoice/start`, { method: 'POST' })
  if (!r.ok) {
    const body = await r.json().catch(() => ({ detail: r.statusText }))
    alert(body.detail ?? '启动失败')
  }
  await refreshCosyStatus()
}

async function cosyStop() {
  await fetch(`${backendOrigin}/tts/cosyvoice/stop`, { method: 'POST' })
  await refreshCosyStatus()
}
</script>

<template>
  <el-card>
    <template #header>
      <strong>🔊 语音朗读（TTS）</strong>
    </template>
    <el-form label-width="110px" class="space-y-2 text-sm">

      <el-form-item label="启用 TTS">
        <el-switch v-model="appStore.ttsEnabled" @change="appStore.saveTtsSettings" />
      </el-form-item>

      <template v-if="appStore.ttsEnabled">

        <!-- 模式选择 -->
        <el-form-item label="朗读模式">
          <el-radio-group
            v-model="appStore.ttsMode"
            @change="appStore.saveTtsSettings"
            style="display: flex; flex-direction: column; gap: 8px; align-items: flex-start;"
          >
            <div class="flex items-center gap-1">
              <el-radio value="edge">内置 edge-tts（在线，免费）</el-radio>
              <el-tooltip content="调用微软 Azure Neural TTS，无需安装，需能访问 speech.platform.bing.com" placement="right">
                <span class="text-slate-400 cursor-help text-xs">?</span>
              </el-tooltip>
            </div>
            <div class="flex items-center gap-1">
              <el-radio value="cosyvoice">本机 CosyVoice（离线，需安装）</el-radio>
              <el-tooltip content="本机安装隔离 Python 环境 + 下载模型（~2.5GB）。需先安装 uv 包管理器。" placement="right">
                <span class="text-slate-400 cursor-help text-xs">?</span>
              </el-tooltip>
            </div>
            <div class="flex items-center gap-1">
              <el-radio value="local">外部 TTS 服务（OpenAI 兼容）</el-radio>
              <el-tooltip content="局域网另一台机器或云端的 OpenAI 兼容 TTS 服务，填入根地址即可，无需在本机安装模型。" placement="right">
                <span class="text-slate-400 cursor-help text-xs">?</span>
              </el-tooltip>
            </div>
          </el-radio-group>
        </el-form-item>

        <!-- edge-tts -->
        <template v-if="appStore.ttsMode === 'edge'">
          <el-form-item label="GM 旁白音色">
            <el-select v-model="appStore.ttsGmVoice" @change="appStore.saveTtsSettings"
              placeholder="晓晓（温柔/旁白）" clearable filterable style="width:100%">
              <el-option v-for="v in edgeVoices" :key="v.voice" :label="v.label" :value="v.voice" />
            </el-select>
          </el-form-item>
          <el-form-item label="主角（PC）音色">
            <el-select v-model="appStore.ttsPcVoice" @change="appStore.saveTtsSettings"
              placeholder="与旁白相同" clearable filterable style="width:100%">
              <el-option v-for="v in edgeVoices" :key="v.voice" :label="v.label" :value="v.voice" />
            </el-select>
          </el-form-item>
        </template>

        <!-- CosyVoice 本机 -->
        <template v-if="appStore.ttsMode === 'cosyvoice'">
          <el-form-item label="安装状态">
            <div class="flex flex-col gap-2 w-full">
              <!-- 状态 + 操作按钮 -->
              <div class="flex items-center gap-2 flex-wrap">
                <template v-if="cosyStatus">
                  <el-tag v-if="cosyStatus.running" type="success">运行中（端口 {{ cosyStatus.port }}）</el-tag>
                  <el-tag v-else-if="cosyStatus.installed" type="info">已安装，未启动</el-tag>
                  <el-tag v-else-if="cosyStatus.installing" type="warning">安装中…</el-tag>
                  <el-tag v-else type="danger">未安装</el-tag>

                  <el-button v-if="!cosyStatus.installed && !cosyStatus.installing"
                    type="primary" size="small" @click="cosyInstall">安装（~2.5GB）</el-button>
                  <el-button v-if="cosyStatus.installed && !cosyStatus.running"
                    type="primary" size="small" @click="cosyStart">启动</el-button>
                  <el-button v-if="cosyStatus.running"
                    type="danger" size="small" @click="cosyStop">停止</el-button>
                  <el-button size="small" text @click="refreshCosyStatus">刷新</el-button>

                  <el-tooltip placement="right" :width="280">
                    <template #content>
                      <div class="text-xs space-y-1">
                        <div>前置：安装 <strong>uv</strong>（跨平台 Python 包管理器）</div>
                        <div class="font-mono bg-black/20 px-1 rounded">curl -LsSf https://astral.sh/uv/install.sh | sh</div>
                        <div class="font-mono bg-black/20 px-1 rounded">winget install astral-sh.uv</div>
                        <div class="mt-1">uv 装好后，点「安装（~2.5GB）」。安装完成后点此行旁边的「启动」按钮启动 CosyVoice 服务。</div>
                        <div class="text-slate-300">每次重启应用后需手动回到此页再点「启动」。</div>
                      </div>
                    </template>
                    <span class="text-slate-400 cursor-help text-xs">安装说明 ?</span>
                  </el-tooltip>
                </template>
                <span v-else class="text-xs text-slate-400">检测中…</span>
              </div>

              <!-- 进度条（安装中） -->
              <template v-if="cosyStatus?.installing">
                <el-progress :percentage="cosyInstallPct" :striped="true" :striped-flow="true" :duration="8" />
                <div class="text-xs text-slate-500 animate-pulse">
                  {{ cosyStatus.install_log[cosyStatus.install_log.length - 1] || '准备中…' }}
                </div>
              </template>

              <!-- 可折叠日志 -->
              <div v-if="cosyStatus?.install_log?.length">
                <button type="button"
                  class="flex items-center gap-1 text-xs text-slate-400 hover:text-slate-600 cursor-pointer select-none"
                  @click="showCosyLog = !showCosyLog">
                  <span>{{ showCosyLog ? '▾' : '▸' }}</span>
                  <span>详细日志（{{ cosyStatus.install_log.length }} 行）</span>
                </button>
                <div v-if="showCosyLog"
                  class="mt-1 text-xs text-slate-500 bg-slate-50 rounded p-2 max-h-40 overflow-y-auto font-mono space-y-0.5">
                  <div v-for="(line, i) in cosyStatus.install_log" :key="i">{{ line }}</div>
                  <div v-if="cosyStatus.installing" class="animate-pulse text-slate-400">…</div>
                </div>
              </div>

              <div v-if="cosyStatus?.install_error" class="text-xs text-red-500">{{ cosyStatus.install_error }}</div>
            </div>
          </el-form-item>

          <el-form-item label="GM 旁白音色">
            <el-select v-model="appStore.ttsGmVoice" @change="appStore.saveTtsSettings"
              placeholder="中文女" clearable style="width:100%">
              <el-option label="中文女" value="中文女" />
              <el-option label="中文男" value="中文男" />
              <el-option label="粤语女" value="粤语女" />
              <el-option label="日语男" value="日语男" />
              <el-option label="英文女" value="英文女" />
              <el-option label="英文男" value="英文男" />
              <el-option label="韩语女" value="韩语女" />
            </el-select>
          </el-form-item>
          <el-form-item label="主角（PC）音色">
            <el-select v-model="appStore.ttsPcVoice" @change="appStore.saveTtsSettings"
              placeholder="与旁白相同" clearable style="width:100%">
              <el-option label="中文女" value="中文女" />
              <el-option label="中文男" value="中文男" />
              <el-option label="粤语女" value="粤语女" />
              <el-option label="日语男" value="日语男" />
              <el-option label="英文女" value="英文女" />
              <el-option label="英文男" value="英文男" />
              <el-option label="韩语女" value="韩语女" />
            </el-select>
          </el-form-item>
        </template>

        <!-- 外部 TTS 服务 -->
        <template v-if="appStore.ttsMode === 'local'">
          <el-form-item>
            <template #label>
              <span class="flex items-center gap-1">
                服务地址
                <el-tooltip content="OpenAI 兼容 TTS 服务的根地址，如 http://192.168.1.x:5001。CosyVoice / Fish-Speech / MLX-Qwen3-TTS 等部署后直接填此地址。留空则使用下方模型配置。" placement="right" :width="300">
                  <span class="text-slate-400 cursor-help text-xs">?</span>
                </el-tooltip>
              </span>
            </template>
            <el-input v-model="appStore.ttsDirectUrl" @change="appStore.saveTtsSettings"
              placeholder="http://192.168.1.x:5001（留空则用模型配置）" clearable />
          </el-form-item>

          <el-form-item v-if="!appStore.ttsDirectUrl" label="模型配置">
            <el-select v-model="appStore.ttsModelConfigId" @change="appStore.saveTtsSettings"
              placeholder="选择模型配置" style="width:100%">
              <el-option v-for="m in modelsStore.items" :key="m.id"
                :label="`${m.name} (${m.model_name})`" :value="m.id" />
            </el-select>
          </el-form-item>

          <el-form-item label="GM 旁白音色">
            <el-input v-model="appStore.ttsGmVoice" @change="appStore.saveTtsSettings"
              placeholder="如 中文女 / af_sky / zh_female_1" />
          </el-form-item>
          <el-form-item label="主角（PC）音色">
            <el-input v-model="appStore.ttsPcVoice" @change="appStore.saveTtsSettings"
              placeholder="如 中文男 / zh_male_1" />
          </el-form-item>
        </template>

        <div v-if="appStore.ttsMode !== 'local'" class="text-xs text-slate-400 pl-1">
          各 NPC 的专属音色可在游戏中「NPC 图鉴」里单独设置；新 NPC 会按性格原型自动分配。
        </div>

        <!-- 试听 -->
        <el-divider />
        <el-form-item label="试听">
          <div class="flex flex-col gap-2 w-full">
            <el-input v-model="previewText" placeholder="输入试听文本" size="small" :disabled="speaking" />
            <div class="flex gap-2">
              <el-button size="small" :loading="speaking" :disabled="!appStore.ttsEnabled"
                @click="previewVoice(previewText, appStore.ttsGmVoice || '')">试听旁白</el-button>
              <el-button size="small" :loading="speaking" :disabled="!appStore.ttsEnabled"
                @click="previewVoice(previewText, appStore.ttsPcVoice || appStore.ttsGmVoice || '')">试听PC</el-button>
              <el-button v-if="speaking" size="small" type="danger" @click="stop()">停止</el-button>
            </div>
          </div>
        </el-form-item>

      </template>
    </el-form>
  </el-card>
</template>
