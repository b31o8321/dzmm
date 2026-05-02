<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useAppStore } from '@/stores/app'
import { useModelConfigsStore } from '@/stores/modelConfigs'

const appStore = useAppStore()
const modelsStore = useModelConfigsStore()

const webSpeechVoices = ref<{ name: string; lang: string }[]>([])

onMounted(async () => {
  await modelsStore.refresh()
  if (typeof window !== 'undefined' && window.speechSynthesis) {
    const load = () => {
      webSpeechVoices.value = window.speechSynthesis.getVoices().map((v) => ({
        name: v.name,
        lang: v.lang,
      }))
    }
    load()
    window.speechSynthesis.onvoiceschanged = load
  }
})

const chineseVoices = computed(() =>
  webSpeechVoices.value.filter((v) => v.lang.startsWith('zh') || v.lang.startsWith('cmn')),
)
const otherVoices = computed(() =>
  webSpeechVoices.value.filter((v) => !v.lang.startsWith('zh') && !v.lang.startsWith('cmn')),
)

function save() {
  appStore.saveTtsSettings()
}
</script>

<template>
  <el-card>
    <template #header>
      <strong>🔊 语音朗读（TTS）</strong>
    </template>
    <el-form label-width="110px" class="space-y-2 text-sm">

      <el-form-item label="启用 TTS">
        <el-switch v-model="appStore.ttsEnabled" @change="save" />
      </el-form-item>

      <template v-if="appStore.ttsEnabled">
        <el-form-item label="朗读模式">
          <el-radio-group v-model="appStore.ttsMode" @change="save">
            <el-radio value="webspeech">浏览器内置（Web Speech API）</el-radio>
            <el-radio value="local">本地 TTS 模型（OpenAI 兼容 API）</el-radio>
          </el-radio-group>
        </el-form-item>

        <el-form-item v-if="appStore.ttsMode === 'local'" label="TTS 模型配置">
          <el-select v-model="appStore.ttsModelConfigId" @change="save" placeholder="选择模型配置">
            <el-option
              v-for="m in modelsStore.items"
              :key="m.id"
              :label="`${m.name} (${m.model_name})`"
              :value="m.id"
            />
          </el-select>
          <div class="text-xs text-slate-400 mt-1">
            在「模型配置」中添加 TTS 服务的 base_url 与 model_name（如 kokoro / tts-1）。
          </div>
        </el-form-item>

        <el-form-item label="GM 旁白音色">
          <template v-if="appStore.ttsMode === 'webspeech'">
            <el-select
              v-model="appStore.ttsGmVoice"
              @change="save"
              placeholder="系统默认"
              clearable
              filterable
            >
              <el-option-group v-if="chineseVoices.length" label="中文">
                <el-option v-for="v in chineseVoices" :key="v.name" :label="v.name" :value="v.name" />
              </el-option-group>
              <el-option-group v-if="otherVoices.length" label="其他">
                <el-option v-for="v in otherVoices" :key="v.name" :label="`${v.name} (${v.lang})`" :value="v.name" />
              </el-option-group>
            </el-select>
          </template>
          <template v-else>
            <el-input v-model="appStore.ttsGmVoice" @change="save" placeholder="如 af_sky / zh_female_1" />
          </template>
        </el-form-item>

        <el-form-item label="主角（PC）音色">
          <template v-if="appStore.ttsMode === 'webspeech'">
            <el-select
              v-model="appStore.ttsPcVoice"
              @change="save"
              placeholder="与旁白相同"
              clearable
              filterable
            >
              <el-option-group v-if="chineseVoices.length" label="中文">
                <el-option v-for="v in chineseVoices" :key="v.name" :label="v.name" :value="v.name" />
              </el-option-group>
              <el-option-group v-if="otherVoices.length" label="其他">
                <el-option v-for="v in otherVoices" :key="v.name" :label="`${v.name} (${v.lang})`" :value="v.name" />
              </el-option-group>
            </el-select>
          </template>
          <template v-else>
            <el-input v-model="appStore.ttsPcVoice" @change="save" placeholder="如 zh_male_1" />
          </template>
        </el-form-item>

        <div class="text-xs text-slate-400 pl-1">
          各 NPC 的专属音色可在游戏中的「NPC 图鉴」里单独设置。
        </div>
      </template>
    </el-form>
  </el-card>
</template>
