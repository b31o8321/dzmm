<script setup lang="ts">
import { computed } from 'vue'
import { ElDrawer, ElProgress, ElTag, ElDivider, ElButton } from 'element-plus'
import MarkdownView from './MarkdownView.vue'
import CharacterAvatar from './CharacterAvatar.vue'
import type { Character } from '@/api/types'
import { useAppStore } from '@/stores/app'
import { useTTS } from '@/composables/useTTS'
const appStore = useAppStore()
const { previewVoice, speaking: ttsSpeaking } = useTTS()

const props = defineProps<{
  modelValue: boolean
  character: Character | null
  stats?: Record<string, number>
  inventory?: string[]
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: boolean): void
}>()

// Parse base_stats_json (a JSON-encoded string on Character).
const baseStats = computed<Record<string, number>>(() => {
  try {
    return JSON.parse(props.character?.base_stats_json || '{}')
  } catch {
    return {}
  }
})

const liveStats = computed<Record<string, number>>(() => props.stats ?? {})
const liveInventory = computed<string[]>(() => props.inventory ?? [])

// Mirror GameView's XP threshold formula: 100 * lv * (lv + 1) / 2
const xpThreshold = computed(() => {
  const lv = props.character?.level ?? 1
  return (100 * lv * (lv + 1)) / 2
})
const xpProgress = computed(() => {
  const xp = props.character?.xp ?? 0
  if (!xpThreshold.value) return 0
  return Math.min(100, (xp / xpThreshold.value) * 100)
})

function close() {
  emit('update:modelValue', false)
}
</script>

<template>
  <el-drawer
    :model-value="modelValue"
    @update:model-value="(v: boolean) => emit('update:modelValue', v)"
    title="角色卡"
    direction="rtl"
    size="450px"
    @close="close"
  >
    <div v-if="character" class="space-y-4">
      <!-- 头像 + 基本信息 -->
      <div class="flex items-center gap-4">
        <CharacterAvatar
          :character-id="character.id"
          :has-portrait="!!character.portrait_path"
          :fallback-name="character.name"
          :size="72"
        />
        <div>
          <div class="text-2xl font-bold">{{ character.name }}</div>
          <div class="text-sm text-slate-500">Lv {{ character.level ?? 1 }}</div>
        </div>
      </div>

      <!-- XP 进度 -->
      <div>
        <div class="text-xs text-slate-500 mb-1">
          XP {{ character.xp ?? 0 }} / {{ xpThreshold }}
        </div>
        <el-progress :percentage="xpProgress" :show-text="false" />
      </div>

      <el-divider />

      <!-- 当前状态 -->
      <div v-if="Object.keys(liveStats).length">
        <div class="text-sm font-bold text-slate-700 mb-2">当前状态</div>
        <div class="grid grid-cols-2 gap-2 text-sm">
          <div
            v-for="(v, k) in liveStats"
            :key="k"
            class="flex justify-between bg-slate-50 px-2 py-1 rounded"
          >
            <span class="text-slate-600">{{ k }}</span>
            <span class="font-mono">{{ v }}</span>
          </div>
        </div>
      </div>

      <!-- 基础属性 -->
      <div v-if="Object.keys(baseStats).length">
        <div class="text-sm font-bold text-slate-700 mb-2">基础属性</div>
        <div class="grid grid-cols-2 gap-2 text-sm">
          <div
            v-for="(v, k) in baseStats"
            :key="k"
            class="flex justify-between bg-slate-50 px-2 py-1 rounded"
          >
            <span class="text-slate-600">{{ k }}</span>
            <span class="font-mono">{{ v }}</span>
          </div>
        </div>
      </div>

      <!-- 物品 -->
      <div v-if="liveInventory.length">
        <div class="text-sm font-bold text-slate-700 mb-2">物品</div>
        <div class="flex flex-wrap gap-1">
          <el-tag
            v-for="(it, i) in liveInventory"
            :key="i"
            type="info"
            size="small"
          >{{ it }}</el-tag>
        </div>
      </div>

      <el-divider />

      <!-- profile_md 完整渲染 -->
      <div>
        <div class="text-sm font-bold text-slate-700 mb-2">角色档案</div>
        <div class="prose prose-sm max-w-none">
          <MarkdownView :source="character.profile_md || '（无档案）'" />
        </div>
      </div>

      <el-divider />

      <!-- TTS 音色 -->
      <div>
        <div class="text-sm font-bold text-slate-700 mb-2">旁白 / 主角音色</div>
        <div v-if="appStore.ttsEnabled" class="flex items-center gap-3 flex-wrap">
          <span class="text-xs text-slate-500">
            模式：<strong>{{ { edge: 'edge-tts', kokoro: 'Kokoro', webspeech: '浏览器', local: '外部服务' }[appStore.ttsMode] ?? appStore.ttsMode }}</strong>
          </span>
          <span v-if="appStore.ttsGmVoice" class="text-xs text-slate-500">
            旁白：<code class="bg-slate-100 px-1 rounded text-xs">{{ appStore.ttsGmVoice }}</code>
          </span>
          <el-button
            size="small"
            :loading="ttsSpeaking"
            @click="previewVoice(character?.name ? character.name + '，今日天气不错。' : '测试音色', appStore.ttsPcVoice || appStore.ttsGmVoice || '')"
          >🔊 试听主角音色</el-button>
        </div>
        <div v-else class="text-xs text-slate-400">TTS 未启用（可在设置页开启）</div>
      </div>
    </div>
    <div v-else class="text-slate-400 italic">（角色信息加载中…）</div>
  </el-drawer>
</template>
