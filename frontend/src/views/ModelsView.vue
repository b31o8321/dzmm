<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useModelConfigsStore } from '@/stores/modelConfigs'
import { backendOrigin } from '@/api/client'
import type { ModelConfig, ModelConfigIn } from '@/api/types'

const store = useModelConfigsStore()
const recsOpen = ref(['recs'])
const dialogOpen = ref(false)
const editingId = ref<number | null>(null)
const submitting = ref(false)
const testing = ref<number | null>(null)
const removing = ref<number | null>(null)

const form = reactive<ModelConfigIn>({
  name: '',
  type: 'ollama',
  base_url: 'http://localhost:11434',
  model_name: '',
  api_key: '',
  timeout: 60,
  max_concurrent: 0,
})

function resetForm() {
  Object.assign(form, {
    name: '',
    type: 'ollama',
    base_url: 'http://localhost:11434',
    model_name: '',
    api_key: '',
    timeout: 60,
    max_concurrent: 0,
  })
}

const TYPE_DEFAULTS: Record<string, { base_url: string; model_placeholder: string }> = {
  ollama: { base_url: 'http://localhost:11434', model_placeholder: '例如：qwen2.5:7b' },
  lm_studio: { base_url: 'http://localhost:1234/v1', model_placeholder: '例如：Qwen2.5-7B-Instruct（LM Studio 中加载的模型 id）' },
  openai_compat: { base_url: 'https://api.openai.com/v1', model_placeholder: '例如：gpt-4o-mini' },
}

const modelPlaceholder = computed(
  () => TYPE_DEFAULTS[form.type]?.model_placeholder ?? '',
)

function onTypeChange(t: string) {
  // Auto-fill base_url with the type's default — but only if user hasn't
  // typed a custom URL or is leaving an empty form.
  const defaults = TYPE_DEFAULTS[t]
  if (!defaults) return
  const isDefaultUrl = Object.values(TYPE_DEFAULTS).some((d) => d.base_url === form.base_url)
  if (!form.base_url || isDefaultUrl) {
    form.base_url = defaults.base_url
  }
  // Clear api_key when switching to a local type (not used).
  if (t !== 'openai_compat') {
    form.api_key = ''
  }
}

function openCreate() {
  editingId.value = null
  resetForm()
  dialogOpen.value = true
}

function openEdit(row: ModelConfig) {
  editingId.value = row.id
  Object.assign(form, {
    name: row.name,
    type: row.type,
    base_url: row.base_url,
    model_name: row.model_name,
    api_key: '',
    timeout: row.timeout,
    max_concurrent: row.max_concurrent ?? 0,
  })
  dialogOpen.value = true
}

async function onSubmit() {
  submitting.value = true
  try {
    const payload: ModelConfigIn = { ...form }
    if (!payload.api_key) delete (payload as any).api_key
    if (editingId.value === null) {
      await store.create(payload)
      ElMessage.success('已添加')
    } else {
      await store.update(editingId.value, payload)
      ElMessage.success('已更新')
    }
    dialogOpen.value = false
    resetForm()
    editingId.value = null
  } catch (e: any) {
    ElMessage.error(e.message)
  } finally {
    submitting.value = false
  }
}

async function onDelete(row: ModelConfig) {
  try {
    await ElMessageBox.confirm(
      `确认删除模型配置 "${row.name}"?`,
      '确认',
      { type: 'warning' },
    )
  } catch {
    return
  }
  removing.value = row.id
  try {
    await store.remove(row.id)
    ElMessage.success('已删除')
  } catch (e: any) {
    ElMessage.error(e.message)
  } finally {
    removing.value = null
  }
}

async function onTest(id: number) {
  testing.value = id
  try {
    const r = await store.test(id)
    if (r.ok) {
      ElMessageBox.alert(r.info, '连接成功', { type: 'success' })
    } else {
      ElMessageBox.alert(r.info, '连接失败', { type: 'error' })
    }
  } catch (e: any) {
    ElMessage.error(e.message)
  } finally {
    testing.value = null
  }
}

function copyText(text: string) {
  navigator.clipboard.writeText(text).then(() => ElMessage.success('已复制'))
}

const gmLocalModels = [
  { id: 'qwen2.5:14b',       vram: '~10 GB', note: '中文叙事明显优于 7b，格式遵循稳定，推荐首选' },
  { id: 'qwen2.5:32b',       vram: '~20 GB', note: '本地中文 RP 最佳，指令遵循和叙事质量均衡' },
  { id: 'mistral-nemo:12b',  vram: '~8 GB',  note: '创意写作强，多语言，指令遵循好' },
  { id: 'gemma3:12b',        vram: '~8 GB',  note: 'Google 最新，格式遵循稳定，创意性好' },
  { id: 'llama3.1:8b',       vram: '~6 GB',  note: '效果中等，VRAM 有限时的最低可用选项' },
]

const gmCloudModels = [
  { id: 'deepseek-chat',         baseUrl: 'https://api.deepseek.com/v1',       note: '即 DeepSeek-V3，中文 RP 性价比最高，注意勿用 deepseek-reasoner（r1）' },
  { id: 'gpt-4o-mini',           baseUrl: 'https://api.openai.com/v1',         note: '稳定可靠，格式遵循极好，综合性价比高' },
  { id: 'gpt-4o',                baseUrl: 'https://api.openai.com/v1',         note: '叙事质量最强，成本较高' },
  { id: 'gemini-2.0-flash',      baseUrl: 'https://generativelanguage.googleapis.com/v1beta/openai', note: '速度快，中文可用，需 Google API Key' },
  { id: 'claude-haiku-4-5-20251001', baseUrl: '（需 OpenAI 兼容转发层）',     note: 'Roleplay 细腻，直接调用建议用官方 SDK 而非此处' },
]

// TTS external services with install/uninstall scripts (uv-based, no Docker required)
interface TtsExternalService {
  id: string
  name: string
  tier: number
  platform: string
  quality: string
  baseUrl: string
  defaultVoice: string
  note: string
  installScript: string
  startScript: string
  uninstallScript: string
  healthPath: string
}

const ttsExternalServices: TtsExternalService[] = [
  {
    id: 'fish_speech',
    name: 'Fish-Speech',
    tier: 3,
    platform: '跨平台（macOS / Linux / Windows）',
    quality: '★★★★★',
    baseUrl: 'http://localhost:8080',
    defaultVoice: 'default',
    note: '最佳中文音质，支持零样本声音克隆。CPU 可运行（慢），有 GPU 速度快很多。',
    installScript: `#!/bin/bash
# Fish-Speech 安装脚本（需要 uv：curl -LsSf https://astral.sh/uv/install.sh | sh）
set -e
VENV="$HOME/.dzmm/fish_speech_env"
echo "[1/2] 创建 Python 3.10 环境..."
uv venv "$VENV" --python 3.10
echo "[2/2] 安装 Fish-Speech..."
uv pip install --python "$VENV/bin/python" fish-speech
echo ""
echo "✅ 安装完成！运行以下命令启动服务："
echo "  bash ~/.dzmm/start_fish_speech.sh"`,
    startScript: `#!/bin/bash
# Fish-Speech 启动脚本
VENV="$HOME/.dzmm/fish_speech_env"
echo "正在启动 Fish-Speech（端口 8080）..."
"$VENV/bin/python" -m fish_speech.api --listen 0.0.0.0:8080`,
    uninstallScript: `#!/bin/bash
# Fish-Speech 卸载脚本
rm -rf "$HOME/.dzmm/fish_speech_env"
rm -f "$HOME/.dzmm/start_fish_speech.sh"
echo "✅ Fish-Speech 已卸载"`,
    healthPath: '/health',
  },
  {
    id: 'mlx_qwen3_tts',
    name: 'MLX-Qwen3-TTS',
    tier: 3,
    platform: 'Apple Silicon（M1/M2/M3/M4）',
    quality: '★★★★★',
    baseUrl: 'http://localhost:8000',
    defaultVoice: 'default',
    note: '阿里 Qwen3-TTS，M 系芯片原生 MLX 加速，0.2–0.3s/句，中文自然度极高。仅限 Apple Silicon Mac。',
    installScript: `#!/bin/bash
# MLX-Qwen3-TTS 安装脚本（需要 uv + Apple Silicon Mac）
set -e
VENV="$HOME/.dzmm/mlx_tts_env"
echo "[1/2] 创建 Python 3.11 环境..."
uv venv "$VENV" --python 3.11
echo "[2/2] 安装 MLX-Qwen3-TTS..."
uv pip install --python "$VENV/bin/python" mlx-lm mlx-audio
uv pip install --python "$VENV/bin/python" fastapi uvicorn huggingface_hub
# 下载启动脚本
cat > "$HOME/.dzmm/mlx_tts_server.py" << 'EOF'
import asyncio, io, os
from fastapi import FastAPI
from fastapi.responses import Response
from pydantic import BaseModel
import mlx_audio, soundfile as sf, numpy as np

app = FastAPI()
_model = None

def get_model():
    global _model
    if _model is None:
        from mlx_audio.tts.models.qwen3 import Qwen3TTS
        _model = Qwen3TTS.from_pretrained("Qwen/Qwen3-TTS-0.6B")
    return _model

class Req(BaseModel):
    input: str
    voice: str = "default"

@app.post("/v1/audio/speech")
async def synth(req: Req):
    model = get_model()
    audio = await asyncio.get_event_loop().run_in_executor(
        None, lambda: model.generate(req.input))
    buf = io.BytesIO()
    sf.write(buf, np.array(audio), 22050, format="WAV")
    buf.seek(0)
    return Response(content=buf.read(), media_type="audio/wav")

@app.get("/health")
def health(): return {"ok": True}
EOF
echo ""
echo "✅ 安装完成！运行以下命令启动服务："
echo "  $VENV/bin/python $HOME/.dzmm/mlx_tts_server.py"`,
    startScript: `#!/bin/bash
VENV="$HOME/.dzmm/mlx_tts_env"
echo "正在启动 MLX-Qwen3-TTS（端口 8000）..."
"$VENV/bin/python" "$HOME/.dzmm/mlx_tts_server.py"`,
    uninstallScript: `#!/bin/bash
rm -rf "$HOME/.dzmm/mlx_tts_env"
rm -f "$HOME/.dzmm/mlx_tts_server.py"
echo "✅ MLX-Qwen3-TTS 已卸载"`,
    healthPath: '/health',
  },
]

const ttsServiceStatus = ref<Record<string, 'idle' | 'checking' | 'ok' | 'fail'>>({})
const ttsExpandedScript = ref<Record<string, 'install' | 'start' | 'uninstall' | null>>({})

async function checkTtsService(svc: TtsExternalService) {
  ttsServiceStatus.value[svc.id] = 'checking'
  try {
    const r = await fetch(`${backendOrigin}/tts/probe?url=${encodeURIComponent(svc.baseUrl)}`)
    const data = await r.json()
    ttsServiceStatus.value[svc.id] = data.ok ? 'ok' : 'fail'
  } catch {
    ttsServiceStatus.value[svc.id] = 'fail'
  }
}

function downloadScript(filename: string, content: string) {
  const blob = new Blob([content], { type: 'text/plain' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

function toggleScript(id: string, type: 'install' | 'start' | 'uninstall') {
  ttsExpandedScript.value[id] = ttsExpandedScript.value[id] === type ? null : type
}

onMounted(() => store.refresh())
</script>

<template>
  <div class="p-6">
    <div class="flex items-center justify-between mb-4">
      <h2 class="text-2xl font-bold">模型配置</h2>
      <el-button type="primary" @click="openCreate">+ 新增</el-button>
    </div>

    <el-collapse v-model="recsOpen" class="mb-4 border border-slate-200 rounded-lg overflow-hidden bg-white">
      <el-collapse-item name="recs">
        <template #title>
          <span class="font-semibold text-slate-700 pl-1">按用途推荐模型</span>
        </template>
        <div class="px-4 pb-4">
          <el-tabs>

            <!-- GM 引擎 -->
            <el-tab-pane label="GM 叙事引擎" name="gm">
              <div class="flex items-center gap-2 mb-3">
                <el-tag type="danger" size="small">避免推理模型</el-tag>
                <el-tooltip content="deepseek-r1、QwQ、qwen3 思考模式等推理模型会用思考过程占满输出，导致 XML 状态标签全部丢失，游戏无法正常运行。" placement="right" :width="300">
                  <span class="text-xs text-slate-500 cursor-help">deepseek-r1 / QwQ / qwen3 思考模式 — 会破坏输出格式 ?</span>
                </el-tooltip>
              </div>

              <p class="text-xs font-semibold text-slate-600 mb-2">本地模型（Ollama）</p>
              <table class="w-full text-sm mb-4">
                <thead>
                  <tr class="border-b border-slate-200 text-xs text-slate-500">
                    <th class="text-left py-1 pr-4 font-medium">模型</th>
                    <th class="text-left py-1 pr-4 font-medium">显存需求</th>
                    <th class="text-left py-1 font-medium">适用场景 / 说明</th>
                  </tr>
                </thead>
                <tbody class="text-slate-700">
                  <tr v-for="m in gmLocalModels" :key="m.id" class="border-b border-slate-100 last:border-0">
                    <td class="py-1.5 pr-4">
                      <code class="bg-slate-100 text-slate-800 px-1.5 py-0.5 rounded text-xs">{{ m.id }}</code>
                      <el-button
                        link size="small"
                        class="ml-1 text-xs text-slate-400"
                        @click="copyText(`ollama pull ${m.id}`)"
                      >复制拉取命令</el-button>
                    </td>
                    <td class="py-1.5 pr-4 text-xs text-slate-500 whitespace-nowrap">{{ m.vram }}</td>
                    <td class="py-1.5 text-xs text-slate-600">{{ m.note }}</td>
                  </tr>
                </tbody>
              </table>

              <p class="text-xs font-semibold text-slate-600 mb-2">云端模型（OpenAI 兼容接口）</p>
              <table class="w-full text-sm">
                <thead>
                  <tr class="border-b border-slate-200 text-xs text-slate-500">
                    <th class="text-left py-1 pr-4 font-medium">模型 ID</th>
                    <th class="text-left py-1 pr-4 font-medium">Base URL</th>
                    <th class="text-left py-1 font-medium">说明</th>
                  </tr>
                </thead>
                <tbody class="text-slate-700">
                  <tr v-for="m in gmCloudModels" :key="m.id" class="border-b border-slate-100 last:border-0">
                    <td class="py-1.5 pr-4">
                      <code class="bg-slate-100 text-slate-800 px-1.5 py-0.5 rounded text-xs">{{ m.id }}</code>
                      <el-button link size="small" class="ml-1 text-xs text-slate-400" @click="copyText(m.id)">复制</el-button>
                    </td>
                    <td class="py-1.5 pr-4 text-xs text-slate-500">
                      <code class="text-xs">{{ m.baseUrl }}</code>
                    </td>
                    <td class="py-1.5 text-xs text-slate-600">{{ m.note }}</td>
                  </tr>
                </tbody>
              </table>
            </el-tab-pane>

            <!-- TTS -->
            <el-tab-pane label="TTS 语音合成" name="tts">
              <p class="text-xs text-slate-500 mb-4">在<strong>「设置」→「语音朗读」</strong>切换模式。按性能需求选择合适方案。</p>

              <!-- Tier 1: 开箱即用 -->
              <div class="mb-3">
                <div class="flex items-center gap-2 mb-2">
                  <el-tag type="success" size="small">开箱即用</el-tag>
                  <span class="text-xs text-slate-500">无需额外安装</span>
                </div>
                <div class="border border-slate-200 rounded-lg p-3 bg-slate-50 flex items-center justify-between">
                  <div>
                    <span class="text-sm font-medium">edge-tts</span>
                    <span class="text-xs text-slate-500 ml-2">微软在线语音 · 中文音色丰富 · 需联网</span>
                  </div>
                  <el-tag type="info" size="small">内置默认</el-tag>
                </div>
              </div>

              <!-- Tier 2: 需要一定性能 -->
              <div class="mb-3">
                <div class="flex items-center gap-2 mb-2">
                  <el-tag type="warning" size="small">需要一定性能</el-tag>
                  <span class="text-xs text-slate-500">本地运行，离线可用，效果更好</span>
                </div>
                <div class="border border-slate-200 rounded-lg p-3 bg-slate-50 flex items-center justify-between">
                  <div>
                    <span class="text-sm font-medium">CosyVoice</span>
                    <span class="text-xs text-slate-500 ml-2">阿里 300M 模型 · 7 种中文音色 · CPU 可运行</span>
                  </div>
                  <el-button size="small" @click="$router.push('/settings')">前往设置安装</el-button>
                </div>
              </div>

              <!-- Tier 3: 需要很好的性能 -->
              <div>
                <div class="flex items-center gap-2 mb-2">
                  <el-tag type="danger" size="small">需要较好性能</el-tag>
                  <span class="text-xs text-slate-500">音质最佳，需要独立启动外部服务</span>
                </div>
                <div class="space-y-3">
                  <div
                    v-for="svc in ttsExternalServices"
                    :key="svc.id"
                    class="border border-slate-200 rounded-lg p-3 bg-white"
                  >
                    <!-- Header row -->
                    <div class="flex items-start justify-between gap-2 mb-2">
                      <div class="flex-1">
                        <div class="flex items-center gap-2 flex-wrap">
                          <span class="text-sm font-medium">{{ svc.name }}</span>
                          <span class="text-xs text-slate-400">{{ svc.quality }}</span>
                          <span class="text-xs text-slate-500">{{ svc.platform }}</span>
                        </div>
                        <p class="text-xs text-slate-500 mt-0.5">{{ svc.note }}</p>
                      </div>
                      <!-- Status + check -->
                      <div class="flex items-center gap-2 shrink-0">
                        <el-tag
                          v-if="ttsServiceStatus[svc.id] === 'ok'" type="success" size="small"
                        >已连接</el-tag>
                        <el-tag
                          v-else-if="ttsServiceStatus[svc.id] === 'fail'" type="danger" size="small"
                        >未运行</el-tag>
                        <el-button
                          size="small"
                          :loading="ttsServiceStatus[svc.id] === 'checking'"
                          @click="checkTtsService(svc)"
                        >检查连接</el-button>
                      </div>
                    </div>

                    <!-- Base URL row -->
                    <div class="flex items-center gap-2 mb-2">
                      <span class="text-xs text-slate-500 shrink-0">Base URL：</span>
                      <code class="bg-slate-100 text-slate-800 px-1.5 py-0.5 rounded text-xs flex-1">{{ svc.baseUrl }}</code>
                      <el-button type="button" link size="small" class="text-xs text-slate-400 shrink-0" @click="copyText(svc.baseUrl)">复制</el-button>
                    </div>

                    <!-- Script buttons -->
                    <div class="flex items-center gap-2 flex-wrap">
                      <el-button
                        size="small"
                        :type="ttsExpandedScript[svc.id] === 'install' ? 'primary' : 'default'"
                        plain
                        @click="toggleScript(svc.id, 'install')"
                      >安装脚本</el-button>
                      <el-button
                        size="small"
                        :type="ttsExpandedScript[svc.id] === 'start' ? 'primary' : 'default'"
                        plain
                        @click="toggleScript(svc.id, 'start')"
                      >启动脚本</el-button>
                      <el-button
                        size="small"
                        :type="ttsExpandedScript[svc.id] === 'uninstall' ? 'danger' : 'default'"
                        plain
                        @click="toggleScript(svc.id, 'uninstall')"
                      >卸载脚本</el-button>
                    </div>

                    <!-- Expanded script panel -->
                    <div
                      v-if="ttsExpandedScript[svc.id]"
                      class="mt-2 bg-slate-900 rounded p-3 relative"
                    >
                      <div class="flex items-center justify-between mb-1">
                        <span class="text-xs text-slate-400">
                          {{ ttsExpandedScript[svc.id] === 'install' ? '安装脚本' : ttsExpandedScript[svc.id] === 'start' ? '启动脚本' : '卸载脚本' }}
                        </span>
                        <div class="flex gap-2">
                          <el-button
                            type="button"
                            link
                            size="small"
                            class="!text-slate-300 text-xs"
                            @click="copyText(ttsExpandedScript[svc.id] === 'install' ? svc.installScript : ttsExpandedScript[svc.id] === 'start' ? svc.startScript : svc.uninstallScript)"
                          >复制</el-button>
                          <el-button
                            type="button"
                            link
                            size="small"
                            class="!text-slate-300 text-xs"
                            @click="downloadScript(
                              `${svc.id}_${ttsExpandedScript[svc.id]}.sh`,
                              ttsExpandedScript[svc.id] === 'install' ? svc.installScript : ttsExpandedScript[svc.id] === 'start' ? svc.startScript : svc.uninstallScript
                            )"
                          >下载</el-button>
                        </div>
                      </div>
                      <pre class="text-xs text-green-300 whitespace-pre-wrap font-mono leading-5 max-h-48 overflow-y-auto">{{
                        ttsExpandedScript[svc.id] === 'install' ? svc.installScript
                        : ttsExpandedScript[svc.id] === 'start' ? svc.startScript
                        : svc.uninstallScript
                      }}</pre>
                    </div>
                  </div>
                </div>
              </div>
            </el-tab-pane>

          </el-tabs>
        </div>
      </el-collapse-item>
    </el-collapse>

    <el-table :data="store.items" v-loading="store.loading" border>
      <el-table-column prop="name" label="名称" width="160" />
      <el-table-column prop="type" label="类型" width="140" />
      <el-table-column prop="base_url" label="Base URL" />
      <el-table-column prop="model_name" label="模型" width="200" />
      <el-table-column label="API Key" width="100">
        <template #default="{ row }">
          {{ row.api_key_ref ? '已设置' : '—' }}
        </template>
      </el-table-column>
      <el-table-column label="操作" width="240">
        <template #default="{ row }">
          <el-button
            size="small"
            :loading="testing === row.id"
            @click="onTest(row.id)"
          >测试</el-button>
          <el-button size="small" @click="openEdit(row)">编辑</el-button>
          <el-button
            size="small"
            type="danger"
            :loading="removing === row.id"
            @click="onDelete(row)"
          >删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog
      v-model="dialogOpen"
      :title="editingId === null ? '新增模型配置' : '编辑模型配置'"
      width="520px"
    >
      <el-form :model="form" label-width="100px">
        <el-form-item label="名称" required>
          <el-input v-model="form.name" placeholder="例如：本地 qwen" />
        </el-form-item>
        <el-form-item label="类型" required>
          <el-select v-model="form.type" @change="onTypeChange">
            <el-option label="Ollama 本地" value="ollama" />
            <el-option label="LM Studio 本地" value="lm_studio" />
            <el-option label="OpenAI 兼容（云端）" value="openai_compat" />
          </el-select>
        </el-form-item>
        <el-form-item label="Base URL" required>
          <el-input v-model="form.base_url" />
        </el-form-item>
        <el-form-item label="模型" required>
          <el-input
            v-model="form.model_name"
            :placeholder="modelPlaceholder"
          />
        </el-form-item>
        <el-form-item label="API Key" v-if="form.type === 'openai_compat'">
          <el-input
            v-model="form.api_key"
            type="password"
            show-password
            :placeholder="editingId !== null ? '留空则保留原密钥' : ''"
          />
        </el-form-item>
        <el-form-item label="超时（秒）">
          <el-input-number v-model="form.timeout" :min="5" :max="300" />
        </el-form-item>
        <el-form-item label="并发上限">
          <el-input-number v-model="form.max_concurrent" :min="0" :max="20" />
          <span class="text-xs text-slate-500 ml-2">
            0 = 不限。云端免费层（智谱 glm-4-flash 等）必须设 1，否则并发请求会被全部 429。
          </span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogOpen = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="onSubmit">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>
