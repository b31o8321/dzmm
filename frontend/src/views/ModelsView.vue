<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useModelConfigsStore } from '@/stores/modelConfigs'
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
})

function resetForm() {
  Object.assign(form, {
    name: '',
    type: 'ollama',
    base_url: 'http://localhost:11434',
    model_name: '',
    api_key: '',
    timeout: 60,
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

const ttsBuiltinModes = [
  {
    name: 'edge-tts（内置，在线）',
    desc: '微软 Azure Neural TTS，无需安装，需联网。中文 Neural 音色丰富，NPC 按性格原型自动分配。',
    setup: '无需配置',
  },
  {
    name: 'CosyVoice（本机离线）',
    desc: '高质量中文 TTS，在设置页安装（需 uv 包管理器，下载 ~2.5GB）。安装完成后点「启动」使用。',
    setup: '设置页点击「安装」',
  },
]

const ttsLocalServices = [
  { name: 'openedai-speech (Kokoro)', baseUrl: 'http://localhost:8000', note: '高质量多音色，兼容 OpenAI /v1/audio/speech；推荐 Docker 部署' },
  { name: 'AllTalk TTS',              baseUrl: 'http://localhost:7851', note: '支持声音克隆，本地 WebUI，Base URL 填到 /v1' },
  { name: 'Kokoro-FastAPI',           baseUrl: 'http://localhost:8880', note: '轻量 Python 服务，仅 Kokoro 引擎，启动快' },
]

const ttsCloudModels = [
  { id: 'tts-1',    baseUrl: 'https://api.openai.com/v1', note: '标准质量，延迟低；音色：alloy / echo / fable / onyx / nova / shimmer' },
  { id: 'tts-1-hd', baseUrl: 'https://api.openai.com/v1', note: '高质量，略慢，同上 6 种音色' },
]

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
              <p class="text-xs text-slate-500 mb-3">在<strong>「设置」→「语音朗读」</strong>切换模式。</p>

              <p class="text-xs font-semibold text-slate-600 mb-2">内置引擎（推荐）</p>
              <table class="w-full text-sm mb-4">
                <thead>
                  <tr class="border-b border-slate-200 text-xs text-slate-500">
                    <th class="text-left py-1 pr-4 font-medium">引擎</th>
                    <th class="text-left py-1 pr-4 font-medium">配置方式</th>
                    <th class="text-left py-1 font-medium">说明</th>
                  </tr>
                </thead>
                <tbody class="text-slate-700">
                  <tr v-for="m in ttsBuiltinModes" :key="m.name" class="border-b border-slate-100 last:border-0">
                    <td class="py-1.5 pr-4 text-xs font-medium whitespace-nowrap">{{ m.name }}</td>
                    <td class="py-1.5 pr-4 text-xs text-slate-500 whitespace-nowrap">{{ m.setup }}</td>
                    <td class="py-1.5 text-xs text-slate-600">{{ m.desc }}</td>
                  </tr>
                </tbody>
              </table>

              <p class="text-xs font-semibold text-slate-600 mb-2">外部 TTS 服务（「外部服务」模式，OpenAI 兼容接口）</p>
              <table class="w-full text-sm mb-4">
                <thead>
                  <tr class="border-b border-slate-200 text-xs text-slate-500">
                    <th class="text-left py-1 pr-4 font-medium">服务</th>
                    <th class="text-left py-1 pr-4 font-medium">默认 Base URL</th>
                    <th class="text-left py-1 font-medium">说明</th>
                  </tr>
                </thead>
                <tbody class="text-slate-700">
                  <tr v-for="m in ttsLocalServices" :key="m.name" class="border-b border-slate-100 last:border-0">
                    <td class="py-1.5 pr-4 text-xs font-medium">{{ m.name }}</td>
                    <td class="py-1.5 pr-4">
                      <code class="bg-slate-100 text-slate-800 px-1.5 py-0.5 rounded text-xs">{{ m.baseUrl }}</code>
                      <el-button link size="small" class="ml-1 text-xs text-slate-400" @click="copyText(m.baseUrl)">复制</el-button>
                    </td>
                    <td class="py-1.5 text-xs text-slate-600">{{ m.note }}</td>
                  </tr>
                </tbody>
              </table>

              <p class="text-xs font-semibold text-slate-600 mb-2">云端语音（OpenAI）</p>
              <table class="w-full text-sm">
                <thead>
                  <tr class="border-b border-slate-200 text-xs text-slate-500">
                    <th class="text-left py-1 pr-4 font-medium">模型 ID</th>
                    <th class="text-left py-1 pr-4 font-medium">Base URL</th>
                    <th class="text-left py-1 font-medium">说明</th>
                  </tr>
                </thead>
                <tbody class="text-slate-700">
                  <tr v-for="m in ttsCloudModels" :key="m.id" class="border-b border-slate-100 last:border-0">
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
      </el-form>
      <template #footer>
        <el-button @click="dialogOpen = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="onSubmit">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>
