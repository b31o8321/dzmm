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
const showGuide = ref(false)

// webspeech
const webSpeechVoices = ref<{ name: string; lang: string; uri: string }[]>([])

function handleVoicesChanged() {
  if (typeof window !== 'undefined' && window.speechSynthesis) {
    webSpeechVoices.value = window.speechSynthesis.getVoices().map((v) => ({
      name: v.name,
      lang: v.lang,
      uri: v.voiceURI,
    }))
  }
}

// edge-tts
const edgeVoices = ref<{ voice: string; label: string }[]>([])

// kokoro
const kokoroReady = ref<boolean | null>(null)
const kokoroDownloading = ref(false)
const kokoroError = ref('')

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

// 6 install steps; derive rough % from log length
const COSY_TOTAL_STEPS = 6
const cosyInstallPct = computed(() => {
  if (!cosyStatus.value?.installing && cosyStatus.value?.installed) return 100
  const n = cosyStatus.value?.install_log?.length ?? 0
  return Math.min(Math.round((n / COSY_TOTAL_STEPS) * 95), 95)
})

const KOKORO_ZH_VOICES = [
  { value: 'zf_xiaobei',  label: '小北（女，温柔）' },
  { value: 'zf_xiaoni',   label: '小妮（女，活泼）' },
  { value: 'zf_xiaoxiao', label: '晓晓（女，沉稳）' },
  { value: 'zf_xiaoyi',   label: '晓伊（女，明快）' },
  { value: 'zm_yunjian',  label: '云健（男，低沉）' },
  { value: 'zm_yunxi',    label: '云希（男，稳重）' },
  { value: 'zm_yunxia',   label: '云夏（男，青年）' },
  { value: 'zm_yunyang',  label: '云扬（男，权威）' },
]

onMounted(async () => {
  await modelsStore.refresh()

  if (typeof window !== 'undefined' && window.speechSynthesis) {
    handleVoicesChanged()
    window.speechSynthesis.addEventListener('voiceschanged', handleVoicesChanged)
  }

  try {
    const r = await fetch(`${backendOrigin}/tts/voices`)
    if (r.ok) edgeVoices.value = await r.json()
  } catch { /* ignore */ }

  await refreshKokoroStatus()
  await refreshCosyStatus()
})

onUnmounted(() => {
  if (typeof window !== 'undefined' && window.speechSynthesis) {
    window.speechSynthesis.removeEventListener('voiceschanged', handleVoicesChanged)
  }
  if (cosyPollTimer) clearInterval(cosyPollTimer)
})

async function refreshKokoroStatus() {
  try {
    const r = await fetch(`${backendOrigin}/tts/kokoro/status`)
    if (r.ok) kokoroReady.value = (await r.json()).ready
    else kokoroReady.value = false
  } catch { kokoroReady.value = false }
}

async function refreshCosyStatus() {
  try {
    const r = await fetch(`${backendOrigin}/tts/cosyvoice/status`)
    if (r.ok) cosyStatus.value = await r.json()
  } catch { /* ignore */ }
}

async function cosyInstall() {
  await fetch(`${backendOrigin}/tts/cosyvoice/install`, { method: 'POST' })
  // Poll for progress every 2s while installing
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

async function downloadKokoro() {
  kokoroDownloading.value = true
  kokoroError.value = ''
  try {
    const r = await fetch(`${backendOrigin}/tts/kokoro/ensure`, { method: 'POST' })
    if (r.ok) {
      kokoroReady.value = true
    } else {
      const body = await r.json().catch(() => ({ detail: r.statusText }))
      kokoroError.value = body.detail ?? '下载失败'
    }
  } catch (e: any) {
    kokoroError.value = e?.message ?? '网络错误'
  } finally {
    kokoroDownloading.value = false
  }
}

const chineseVoices = computed(() =>
  webSpeechVoices.value.filter((v) => v.lang.startsWith('zh') || v.lang.startsWith('cmn')),
)
const otherVoices = computed(() =>
  webSpeechVoices.value.filter((v) => !v.lang.startsWith('zh') && !v.lang.startsWith('cmn')),
)

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
        <el-form-item label="朗读模式">
          <el-radio-group
            v-model="appStore.ttsMode"
            @change="appStore.saveTtsSettings"
            style="display: flex; flex-direction: column; gap: 8px; align-items: flex-start;"
          >
            <el-radio value="edge">内置 edge-tts（在线免费，Neural音色）</el-radio>
            <el-radio value="kokoro">本地 Kokoro（离线，需下载 ~82MB）</el-radio>
            <el-radio value="cosyvoice">本地 CosyVoice（离线，需安装 ~2.5GB）</el-radio>
            <el-radio value="webspeech">浏览器内置（Web Speech API）</el-radio>
            <el-radio value="local">外部 TTS 服务（OpenAI 兼容）</el-radio>
          </el-radio-group>
        </el-form-item>

        <!-- edge-tts mode -->
        <template v-if="appStore.ttsMode === 'edge'">
          <el-form-item label="GM 旁白音色">
            <el-select v-model="appStore.ttsGmVoice" @change="appStore.saveTtsSettings" placeholder="晓晓（温柔/旁白）" clearable filterable>
              <el-option v-for="v in edgeVoices" :key="v.voice" :label="v.label" :value="v.voice" />
            </el-select>
          </el-form-item>
          <el-form-item label="主角（PC）音色">
            <el-select v-model="appStore.ttsPcVoice" @change="appStore.saveTtsSettings" placeholder="与旁白相同" clearable filterable>
              <el-option v-for="v in edgeVoices" :key="v.voice" :label="v.label" :value="v.voice" />
            </el-select>
          </el-form-item>
        </template>

        <!-- kokoro mode -->
        <template v-if="appStore.ttsMode === 'kokoro'">
          <el-form-item label="模型状态">
            <div class="flex items-center gap-3">
              <el-tag v-if="kokoroReady === true" type="success">已就绪</el-tag>
              <el-tag v-else-if="kokoroReady === false" type="info">未下载</el-tag>
              <el-tag v-else type="warning">检测中…</el-tag>
              <el-button
                v-if="kokoroReady === false"
                type="primary"
                size="small"
                :loading="kokoroDownloading"
                @click="downloadKokoro"
              >
                {{ kokoroDownloading ? '下载中… (~82MB)' : '立即下载' }}
              </el-button>
            </div>
            <div v-if="kokoroError" class="text-xs text-red-500 mt-1">{{ kokoroError }}</div>
          </el-form-item>
          <el-form-item label="GM 旁白音色">
            <el-select v-model="appStore.ttsGmVoice" @change="appStore.saveTtsSettings" placeholder="小北（中文女，温柔）" clearable>
              <el-option v-for="v in KOKORO_ZH_VOICES" :key="v.value" :label="v.label" :value="v.value" />
            </el-select>
          </el-form-item>
          <el-form-item label="主角（PC）音色">
            <el-select v-model="appStore.ttsPcVoice" @change="appStore.saveTtsSettings" placeholder="与旁白相同" clearable>
              <el-option v-for="v in KOKORO_ZH_VOICES" :key="v.value" :label="v.label" :value="v.value" />
            </el-select>
          </el-form-item>
        </template>

        <!-- cosyvoice mode -->
        <template v-if="appStore.ttsMode === 'cosyvoice'">
          <el-form-item label="安装状态">
            <div class="flex flex-col gap-2 w-full">
              <div class="flex items-center gap-3 flex-wrap">
                <template v-if="cosyStatus">
                  <el-tag v-if="cosyStatus.running" type="success">运行中（端口 {{ cosyStatus.port }}）</el-tag>
                  <el-tag v-else-if="cosyStatus.installed" type="info">已安装，未启动</el-tag>
                  <el-tag v-else-if="cosyStatus.installing" type="warning">安装中…</el-tag>
                  <el-tag v-else type="danger">未安装</el-tag>

                  <el-button
                    v-if="!cosyStatus.installed && !cosyStatus.installing"
                    type="primary" size="small"
                    @click="cosyInstall"
                  >安装（~2.5GB）</el-button>

                  <el-button
                    v-if="cosyStatus.installed && !cosyStatus.running"
                    type="primary" size="small"
                    @click="cosyStart"
                  >启动</el-button>

                  <el-button
                    v-if="cosyStatus.running"
                    type="danger" size="small"
                    @click="cosyStop"
                  >停止</el-button>

                  <el-button size="small" text @click="refreshCosyStatus">刷新</el-button>
                </template>
                <span v-else class="text-xs text-slate-400">检测中…</span>
              </div>

              <!-- install progress bar -->
              <template v-if="cosyStatus?.installing">
                <el-progress
                  :percentage="cosyInstallPct"
                  :striped="true"
                  :striped-flow="true"
                  :duration="8"
                  status=""
                />
                <div class="text-xs text-slate-500 animate-pulse">
                  {{ cosyStatus.install_log[cosyStatus.install_log.length - 1] || '准备中…' }}
                </div>
              </template>

              <!-- collapsible log -->
              <div v-if="cosyStatus?.install_log?.length">
                <button
                  type="button"
                  class="flex items-center gap-1 text-xs text-slate-400 hover:text-slate-600 cursor-pointer select-none"
                  @click="showCosyLog = !showCosyLog"
                >
                  <span>{{ showCosyLog ? '▾' : '▸' }}</span>
                  <span>详细日志（{{ cosyStatus.install_log.length }} 行）</span>
                </button>
                <div v-if="showCosyLog" class="mt-1 text-xs text-slate-500 bg-slate-50 rounded p-2 max-h-40 overflow-y-auto font-mono space-y-0.5">
                  <div v-for="(line, i) in cosyStatus.install_log" :key="i">{{ line }}</div>
                  <div v-if="cosyStatus.installing" class="animate-pulse text-slate-400">…</div>
                </div>
              </div>

              <div v-if="cosyStatus?.install_error" class="text-xs text-red-500">{{ cosyStatus.install_error }}</div>

              <div class="text-xs text-slate-400">
                首次使用需 <strong>uv</strong>（<code>curl -LsSf https://astral.sh/uv/install.sh | sh</code>）；Windows 用 <code>winget install astral-sh.uv</code>。
                安装完成后点击「启动」，每次重启应用需手动启动。
              </div>
            </div>
          </el-form-item>
          <el-form-item label="GM 旁白音色">
            <el-select v-model="appStore.ttsGmVoice" @change="appStore.saveTtsSettings" placeholder="中文女" clearable>
              <el-option label="中文女" value="中文女" />
              <el-option label="中文男" value="中文男" />
              <el-option label="粤语女" value="粤语女" />
              <el-option label="英文女" value="英文女" />
              <el-option label="英文男" value="英文男" />
            </el-select>
          </el-form-item>
          <el-form-item label="主角（PC）音色">
            <el-select v-model="appStore.ttsPcVoice" @change="appStore.saveTtsSettings" placeholder="与旁白相同" clearable>
              <el-option label="中文女" value="中文女" />
              <el-option label="中文男" value="中文男" />
              <el-option label="粤语女" value="粤语女" />
              <el-option label="英文女" value="英文女" />
              <el-option label="英文男" value="英文男" />
            </el-select>
          </el-form-item>
        </template>

        <!-- webspeech mode -->
        <template v-if="appStore.ttsMode === 'webspeech'">
          <el-form-item label="GM 旁白音色">
            <el-select v-model="appStore.ttsGmVoice" @change="appStore.saveTtsSettings" placeholder="系统默认" clearable filterable>
              <el-option-group v-if="chineseVoices.length" label="中文">
                <el-option v-for="v in chineseVoices" :key="v.name" :label="v.name" :value="v.name" />
              </el-option-group>
              <el-option-group v-if="otherVoices.length" label="其他">
                <el-option v-for="v in otherVoices" :key="v.name" :label="`${v.name} (${v.lang})`" :value="v.name" />
              </el-option-group>
            </el-select>
          </el-form-item>
          <el-form-item label="主角（PC）音色">
            <el-select v-model="appStore.ttsPcVoice" @change="appStore.saveTtsSettings" placeholder="与旁白相同" clearable filterable>
              <el-option-group v-if="chineseVoices.length" label="中文">
                <el-option v-for="v in chineseVoices" :key="v.name" :label="v.name" :value="v.name" />
              </el-option-group>
              <el-option-group v-if="otherVoices.length" label="其他">
                <el-option v-for="v in otherVoices" :key="v.name" :label="`${v.name} (${v.lang})`" :value="v.name" />
              </el-option-group>
            </el-select>
          </el-form-item>
        </template>

        <!-- local proxy mode -->
        <template v-if="appStore.ttsMode === 'local'">
          <el-form-item label="服务地址">
            <el-input
              v-model="appStore.ttsDirectUrl"
              @change="appStore.saveTtsSettings"
              placeholder="http://192.168.1.x:5001（留空则用下方模型配置）"
              clearable
            />
            <div class="text-xs text-slate-400 mt-1">
              填入局域网（或本机）OpenAI 兼容 TTS 服务的根地址，留空则走「模型配置」。<br>
              CosyVoice / Kokoro / Fish-Speech 等部署后直接填此地址即可使用，无需另建配置。
            </div>
          </el-form-item>
          <el-form-item v-if="!appStore.ttsDirectUrl" label="模型配置">
            <el-select v-model="appStore.ttsModelConfigId" @change="appStore.saveTtsSettings" placeholder="选择模型配置">
              <el-option v-for="m in modelsStore.items" :key="m.id" :label="`${m.name} (${m.model_name})`" :value="m.id" />
            </el-select>
            <div class="text-xs text-slate-400 mt-1">
              在「模型配置」中添加 TTS 服务的 base_url 与 model_name。
            </div>
          </el-form-item>
          <el-form-item label="GM 旁白音色">
            <el-input v-model="appStore.ttsGmVoice" @change="appStore.saveTtsSettings" placeholder="如 中文女 / af_sky / zh_female_1" />
          </el-form-item>
          <el-form-item label="主角（PC）音色">
            <el-input v-model="appStore.ttsPcVoice" @change="appStore.saveTtsSettings" placeholder="如 中文男 / zh_male_1" />
          </el-form-item>
        </template>

        <div v-if="appStore.ttsMode !== 'local'" class="text-xs text-slate-400 pl-1">
          各 NPC 的专属音色可在游戏中的「NPC 图鉴」里单独设置；新 NPC 会按性格原型自动分配。
        </div>

        <!-- 试听 -->
        <el-divider />
        <el-form-item label="试听">
          <div class="flex flex-col gap-2 w-full">
            <el-input
              v-model="previewText"
              placeholder="输入试听文本"
              size="small"
              :disabled="speaking"
            />
            <div class="flex gap-2">
              <el-button
                size="small"
                :loading="speaking"
                :disabled="!appStore.ttsEnabled"
                @click="previewVoice(previewText, appStore.ttsGmVoice || '')"
              >试听旁白</el-button>
              <el-button
                size="small"
                :loading="speaking"
                :disabled="!appStore.ttsEnabled"
                @click="previewVoice(previewText, appStore.ttsPcVoice || appStore.ttsGmVoice || '')"
              >试听PC</el-button>
              <el-button
                v-if="speaking"
                size="small"
                type="danger"
                @click="stop()"
              >停止</el-button>
            </div>
          </div>
        </el-form-item>

        <!-- 部署指南 -->
        <el-divider />
        <div>
          <button
            type="button"
            class="flex items-center gap-1 text-xs text-slate-500 hover:text-slate-700 cursor-pointer select-none"
            @click="showGuide = !showGuide"
          >
            <span>{{ showGuide ? '▾' : '▸' }}</span>
            <span>部署指南 / 帮助</span>
          </button>

          <div v-if="showGuide" class="mt-3 space-y-4 text-xs text-slate-600">

            <!-- 模式对比 -->
            <div>
              <div class="font-semibold text-slate-700 mb-1">各模式对比</div>
              <table class="w-full border-collapse text-xs">
                <thead>
                  <tr class="bg-slate-50 text-slate-500">
                    <th class="border border-slate-200 px-2 py-1 text-left font-medium">模式</th>
                    <th class="border border-slate-200 px-2 py-1 text-left font-medium">是否离线</th>
                    <th class="border border-slate-200 px-2 py-1 text-left font-medium">下载量</th>
                    <th class="border border-slate-200 px-2 py-1 text-left font-medium">音质</th>
                    <th class="border border-slate-200 px-2 py-1 text-left font-medium">备注</th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <td class="border border-slate-200 px-2 py-1">edge-tts</td>
                    <td class="border border-slate-200 px-2 py-1">❌ 需联网</td>
                    <td class="border border-slate-200 px-2 py-1">无</td>
                    <td class="border border-slate-200 px-2 py-1">★★★★☆</td>
                    <td class="border border-slate-200 px-2 py-1">微软 Neural，免费，无需配置</td>
                  </tr>
                  <tr class="bg-slate-50">
                    <td class="border border-slate-200 px-2 py-1">Kokoro</td>
                    <td class="border border-slate-200 px-2 py-1">✅ 离线</td>
                    <td class="border border-slate-200 px-2 py-1">~82 MB</td>
                    <td class="border border-slate-200 px-2 py-1">★★★☆☆</td>
                    <td class="border border-slate-200 px-2 py-1">ONNX，点击即下载，本机 CPU 运行</td>
                  </tr>
                  <tr>
                    <td class="border border-slate-200 px-2 py-1">CosyVoice（本机）</td>
                    <td class="border border-slate-200 px-2 py-1">✅ 离线</td>
                    <td class="border border-slate-200 px-2 py-1">~2.5 GB</td>
                    <td class="border border-slate-200 px-2 py-1">★★★★★</td>
                    <td class="border border-slate-200 px-2 py-1">需先安装 uv；CPU 推理较慢</td>
                  </tr>
                  <tr class="bg-slate-50">
                    <td class="border border-slate-200 px-2 py-1">外部服务</td>
                    <td class="border border-slate-200 px-2 py-1">取决于服务</td>
                    <td class="border border-slate-200 px-2 py-1">—</td>
                    <td class="border border-slate-200 px-2 py-1">取决于服务</td>
                    <td class="border border-slate-200 px-2 py-1">局域网另一台机器 / 云服务</td>
                  </tr>
                  <tr>
                    <td class="border border-slate-200 px-2 py-1">浏览器内置</td>
                    <td class="border border-slate-200 px-2 py-1">✅ 离线</td>
                    <td class="border border-slate-200 px-2 py-1">无</td>
                    <td class="border border-slate-200 px-2 py-1">★★☆☆☆</td>
                    <td class="border border-slate-200 px-2 py-1">依赖系统已安装语音，因平台差异较大</td>
                  </tr>
                </tbody>
              </table>
            </div>

            <!-- edge-tts -->
            <div>
              <div class="font-semibold text-slate-700 mb-1">edge-tts（无需安装）</div>
              <p>选择此模式后直接启用即可。调用微软 Azure 的 Neural TTS，不产生费用，但需要可以访问 <code>speech.platform.bing.com</code> 的网络环境。</p>
            </div>

            <!-- Kokoro -->
            <div>
              <div class="font-semibold text-slate-700 mb-1">Kokoro ONNX（本机离线）</div>
              <ol class="list-decimal list-inside space-y-1">
                <li>切换到「本地 Kokoro」模式</li>
                <li>模型状态显示「未下载」时，点击「立即下载」</li>
                <li>等待 ~82 MB 下载完成（仅首次），之后每次打开应用自动就绪</li>
              </ol>
            </div>

            <!-- CosyVoice 本机 -->
            <div>
              <div class="font-semibold text-slate-700 mb-1">CosyVoice 本机安装</div>
              <p class="mb-1">前置条件：安装 <strong>uv</strong>（跨平台 Python 包管理器）。</p>
              <div class="bg-slate-900 text-green-300 rounded p-2 font-mono space-y-1 leading-5">
                <div class="text-slate-400"># macOS / Linux</div>
                <div>curl -LsSf https://astral.sh/uv/install.sh | sh</div>
                <div class="text-slate-400 mt-1"># Windows（PowerShell 或 winget）</div>
                <div>winget install astral-sh.uv</div>
                <div class="text-slate-400"><!-- 或 --></div>
                <div>irm https://astral.sh/uv/install.ps1 | iex</div>
              </div>
              <ol class="list-decimal list-inside space-y-1 mt-2">
                <li>安装 uv 后，回到此页切换到「本地 CosyVoice」模式</li>
                <li>点击「安装（~2.5GB）」，等待进度日志显示「安装完成」</li>
                <li>点击「启动」，状态变为「运行中」后即可使用</li>
                <li><strong>注意：</strong>应用重启后需要手动回到此页再次点击「启动」</li>
              </ol>
              <p class="mt-1 text-slate-400">CPU 推理速度约 2–5 倍实时。有 NVIDIA GPU 可在安装后手动将 torch 换成 CUDA 版本以大幅提速。</p>
            </div>

            <!-- 局域网 CosyVoice -->
            <div>
              <div class="font-semibold text-slate-700 mb-1">局域网另一台机器运行 CosyVoice</div>
              <p class="mb-1">在配置较好的机器（如带 GPU 的台式机）上部署，笔记本连接使用。</p>
              <div class="bg-slate-900 text-green-300 rounded p-2 font-mono space-y-1 leading-5 text-[11px]">
                <div class="text-slate-400"># 1. 安装 uv（见上方）</div>
                <div class="text-slate-400 mt-1"># 2. 创建环境 + 安装依赖</div>
                <div>uv venv cosy-env --python 3.10</div>
                <div>uv pip install --python cosy-env/bin/python \</div>
                <div>&nbsp;&nbsp;torch torchaudio \</div>
                <div>&nbsp;&nbsp;--index-url https://download.pytorch.org/whl/cpu</div>
                <div>uv pip install --python cosy-env/bin/python \</div>
                <div>&nbsp;&nbsp;fastapi "uvicorn[standard]" modelscope \</div>
                <div>&nbsp;&nbsp;"git+https://github.com/FunAudioLLM/CosyVoice.git"</div>
                <div class="text-slate-400 mt-1"># 3. 下载模型（~1.8 GB）</div>
                <div>cosy-env/bin/python -c \</div>
                <div>&nbsp;&nbsp;"from modelscope import snapshot_download; \</div>
                <div>&nbsp;&nbsp; snapshot_download('iic/CosyVoice-300M-Instruct', \</div>
                <div>&nbsp;&nbsp; local_dir='./model')"</div>
                <div class="text-slate-400 mt-1"># 4. 启动服务（监听局域网 IP，端口 5001）</div>
                <div>cosy-env/bin/python cosyvoice_server_script.py \</div>
                <div>&nbsp;&nbsp;--port 5001 --model-dir ./model --host 0.0.0.0</div>
              </div>
              <p class="mt-2">然后在本机 TTS 设置中选「外部 TTS 服务」，服务地址填 <code>http://&lt;局域网IP&gt;:5001</code>。</p>
              <p class="mt-1 text-slate-400">
                <code>cosyvoice_server_script.py</code> 随 dzmm 后端安装，位于
                <code>~/.dzmm/</code> 解压目录中，或从 dzmm 源码 <code>backend/src/dzmm/tts/</code> 取得。
              </p>
            </div>

            <!-- Fish-Speech / 其他服务 -->
            <div>
              <div class="font-semibold text-slate-700 mb-1">其他 OpenAI 兼容 TTS 服务</div>
              <p class="mb-1">任何实现了 <code>POST /v1/audio/speech</code> 接口的服务均可使用。常见选项：</p>
              <ul class="list-disc list-inside space-y-1">
                <li>
                  <strong>Fish-Speech</strong>（高音质克隆）—
                  <code>pip install fish-speech</code>，然后 <code>fish_speech server --listen 0.0.0.0:5001</code>
                </li>
                <li>
                  <strong>GPT-SoVITS</strong>（音色克隆）— 参考官方文档开启 API 模式后填入地址
                </li>
                <li>
                  <strong>OpenAI TTS</strong> / <strong>Azure TTS</strong> — 填 API base URL，将 API key 配置在「模型配置」中
                </li>
              </ul>
              <p class="mt-1 text-slate-400">voice 字段含义取决于具体服务；CosyVoice 使用中文音色名（「中文女」「中文男」等），Fish-Speech 使用角色 ID。</p>
            </div>

          </div>
        </div>

      </template>
    </el-form>
  </el-card>
</template>
