<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed } from 'vue'
import { useAppStore } from '@/stores/app'
import { useModelConfigsStore } from '@/stores/modelConfigs'
import { backendOrigin } from '@/api/client'
import { useTTS } from '@/composables/useTTS'

const appStore = useAppStore()
const modelsStore = useModelConfigsStore()
const { previewVoice, speaking, stop } = useTTS()
const previewText = ref('天地玄黄，宇宙洪荒。日月盈昃，辰宿列张。')

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

const KOKORO_ZH_VOICES = [
  { value: 'zf_xiaobei', label: '小北（中文女，温柔）' },
  { value: 'zf_xiaoni',  label: '小妮（中文女，活泼）' },
  { value: 'zm_yunxi',   label: '云希（中文男，稳重）' },
  { value: 'zm_yundong', label: '云动（中文男，低沉）' },
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
          <el-radio-group v-model="appStore.ttsMode" @change="appStore.saveTtsSettings" class="flex flex-col gap-1">
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

              <!-- install progress log -->
              <div v-if="cosyStatus?.installing || cosyStatus?.install_log.length" class="text-xs text-slate-500 bg-slate-50 rounded p-2 max-h-32 overflow-y-auto font-mono space-y-0.5">
                <div v-for="(line, i) in cosyStatus?.install_log" :key="i">{{ line }}</div>
                <div v-if="cosyStatus?.installing" class="animate-pulse">…</div>
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
          <el-form-item label="TTS 模型配置">
            <el-select v-model="appStore.ttsModelConfigId" @change="appStore.saveTtsSettings" placeholder="选择模型配置">
              <el-option v-for="m in modelsStore.items" :key="m.id" :label="`${m.name} (${m.model_name})`" :value="m.id" />
            </el-select>
            <div class="text-xs text-slate-400 mt-1">
              在「模型配置」中添加 TTS 服务的 base_url 与 model_name（如 kokoro / tts-1）。
            </div>
          </el-form-item>
          <el-form-item label="GM 旁白音色">
            <el-input v-model="appStore.ttsGmVoice" @change="appStore.saveTtsSettings" placeholder="如 af_sky / zh_female_1" />
          </el-form-item>
          <el-form-item label="主角（PC）音色">
            <el-input v-model="appStore.ttsPcVoice" @change="appStore.saveTtsSettings" placeholder="如 zh_male_1" />
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
      </template>
    </el-form>
  </el-card>
</template>
