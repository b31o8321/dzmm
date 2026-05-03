<script setup lang="ts">
import { ref, watch, computed } from 'vue'
import { ElMessage } from 'element-plus'
import { sessionsApi, type Npc } from '@/api/sessions'
import { useAppStore } from '@/stores/app'
import { archetypeEdgeMap, archetypeKokoroMap } from '@/utils/ttsArchetype'
import { useTTS } from '@/composables/useTTS'

const edgeVoiceOptions = [
  { voice: 'zh-CN-XiaoxiaoNeural',   label: '晓晓（温柔/旁白）' },
  { voice: 'zh-CN-XiaohanNeural',    label: '晓涵（活泼）' },
  { voice: 'zh-CN-XiaomoNeural',     label: '晓墨（冷静）' },
  { voice: 'zh-CN-XiaoqiuNeural',    label: '晓秋（沉稳/智者）' },
  { voice: 'zh-CN-XiaoshuangNeural', label: '晓双（儿童）' },
  { voice: 'zh-CN-XiaozhenNeural',   label: '晓甄（平民）' },
  { voice: 'zh-CN-YunfengNeural',    label: '云枫（守卫/武将）' },
  { voice: 'zh-CN-YunxiNeural',      label: '云希（盟友）' },
  { voice: 'zh-CN-YunyangNeural',    label: '云扬（商人/权威）' },
  { voice: 'zh-CN-YunyeNeural',      label: '云野（导师/反派）' },
]

const kokoroVoiceOptions = [
  { value: 'zf_xiaobei', label: '小北（中文女，温柔）' },
  { value: 'zf_xiaoni',  label: '小妮（中文女，活泼）' },
  { value: 'zm_yunxi',   label: '云希（中文男，稳重）' },
  { value: 'zm_yundong', label: '云动（中文男，低沉）' },
]

const props = defineProps<{
  modelValue: boolean
  sessionId: number
  npc: Npc | null
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: boolean): void
  (e: 'updated', npc: Npc): void
}>()

const local = ref<Npc | null>(null)
const saving = ref(false)
const appStore = useAppStore()
const voiceSaving = ref(false)

watch(
  () => props.npc,
  (n) => {
    local.value = n ? { ...n, affinity: { ...n.affinity }, notes: [...(n.notes ?? [])] } : null
  },
  { immediate: true },
)

function close() {
  emit('update:modelValue', false)
}

async function togglePin() {
  if (!local.value) return
  saving.value = true
  try {
    const next = !local.value.pinned
    const updated = await sessionsApi.pinNpc(props.sessionId, local.value.id, next)
    local.value = { ...updated, affinity: { ...updated.affinity }, notes: [...(updated.notes ?? [])] }
    emit('updated', updated)
    ElMessage.success(next ? '已置顶到关键 NPC' : '已取消置顶')
  } catch (e: any) {
    ElMessage.error(e.message ?? '操作失败')
  } finally {
    saving.value = false
  }
}

async function saveVoice(voice: string) {
  if (!local.value) return
  voiceSaving.value = true
  try {
    const updated = await sessionsApi.patchNpcVoice(props.sessionId, local.value.id, voice)
    local.value = { ...updated, affinity: { ...updated.affinity }, notes: [...(updated.notes ?? [])] }
    emit('updated', updated)
  } catch (e: any) {
    ElMessage.error(e.message ?? '保存音色失败')
  } finally {
    voiceSaving.value = false
  }
}

// Map an integer affinity value to a 0-100 bar width and a tone color.
// Affinity in our system is unbounded (additive deltas), but typical
// gameplay-meaningful range is roughly -20..+20; we clamp visually.
function barWidth(v: number): string {
  const clamped = Math.max(-20, Math.min(20, v))
  const pct = ((clamped + 20) / 40) * 100
  return `${pct}%`
}

function barColor(v: number): string {
  if (v >= 5) return 'bg-emerald-500'
  if (v > 0) return 'bg-emerald-300'
  if (v === 0) return 'bg-slate-300'
  if (v > -5) return 'bg-rose-300'
  return 'bg-rose-500'
}

const autoVoiceLabel = computed(() => {
  const arch = local.value?.archetype ?? ''
  const voice = archetypeEdgeMap[arch] ?? 'zh-CN-XiaoxiaoNeural'
  return edgeVoiceOptions.find((v) => v.voice === voice)?.label ?? voice
})

const autoKokoroVoiceLabel = computed(() => {
  const arch = local.value?.archetype ?? ''
  const voice = archetypeKokoroMap[arch] ?? 'zf_xiaobei'
  return kokoroVoiceOptions.find((v) => v.value === voice)?.label ?? voice
})

const { previewVoice, speaking: ttsSpeaking } = useTTS()

const effectiveEdgeVoice = computed(() =>
  local.value?.tts_voice ||
  (local.value?.archetype ? archetypeEdgeMap[local.value.archetype] ?? 'zh-CN-XiaoxiaoNeural' : 'zh-CN-XiaoxiaoNeural')
)
const effectiveKokoroVoice = computed(() =>
  local.value?.tts_voice ||
  (local.value?.archetype ? archetypeKokoroMap[local.value.archetype] ?? 'zf_xiaobei' : 'zf_xiaobei')
)

const affinityEntries = computed(() => {
  if (!local.value) return []
  return Object.entries(local.value.affinity ?? {})
    .filter(([, v]) => typeof v === 'number')
    .sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]))
})

const EMOTION_LABELS: Record<string, string> = {
  anger: '怒',
  love: '爱',
  fear: '惧',
  respect: '敬',
  jealousy: '妒',
}
const EMOTION_NEGATIVE = new Set(['anger', 'fear', 'jealousy'])

const emotionEntries = computed(() => {
  if (!local.value || !local.value.emotion) return []
  return Object.entries(local.value.emotion)
    .filter(([, v]) => typeof v === 'number')
    .sort((a, b) => b[1] - a[1])
})

const timelineEntries = computed(() => {
  const list = local.value?.notes ?? []
  return [...list].sort((a, b) => b.turn - a.turn)
})

// v0.11 progressive reveal: each named field is hidden until the GM emits
// `<npc_update reveal="field_a,field_b">`. The backend ships a `revealed`
// map on every Npc payload (default `{name: true}` plus whatever was
// revealed at creation time). When the entire map is missing — old backend,
// mock data — fall back to "everything revealed" so we don't regress UX.
function isRevealed(field: string): boolean {
  if (!local.value) return false
  if (field === 'name') return true
  const r = local.value.revealed
  if (!r) return true
  return r[field] === true
}

const HIDDEN_HINT = '（尚未通过对话/调查得知）'

function npcAvatarColor(name: string): string {
  let h = 0
  for (let i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) & 0xffff
  return `hsl(${h % 360}, 52%, 50%)`
}
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    @update:model-value="(v: boolean) => emit('update:modelValue', v)"
    :title="local?.name || 'NPC'"
    width="560px"
    @close="close"
  >
    <div v-if="local" class="space-y-4">
      <div class="flex items-center gap-3 mb-1">
        <span
          class="inline-flex items-center justify-center w-12 h-12 rounded-full text-white text-xl font-bold shrink-0 select-none shadow-sm"
          :style="{ backgroundColor: npcAvatarColor(local.name) }"
        >{{ local.name[0] }}</span>
        <div>
          <div class="font-bold text-slate-800 text-base">{{ local.name }}</div>
          <div class="text-xs text-slate-400">上次出现：第 {{ local.last_seen_turn }} 回合</div>
        </div>
      </div>
      <div class="flex items-center gap-2 flex-wrap">
        <span v-if="isRevealed('archetype') && local.archetype"
              class="text-xs px-2 py-0.5 bg-amber-100 text-amber-800 rounded">
          {{ local.archetype }}
        </span>
        <span v-else-if="!isRevealed('archetype') && local.archetype"
              class="text-xs px-2 py-0.5 bg-slate-100 text-slate-400 italic rounded"
              :title="HIDDEN_HINT">
          原型 ****
        </span>
        <span v-if="isRevealed('state') && local.state && local.state !== '未知'"
              class="text-xs px-2 py-0.5 bg-slate-100 text-slate-700 rounded">
          状态：{{ local.state }}
        </span>
        <span v-else-if="!isRevealed('state') && local.state && local.state !== '未知'"
              class="text-xs px-2 py-0.5 bg-slate-100 text-slate-400 italic rounded"
              :title="HIDDEN_HINT">
          状态 ****
        </span>
      </div>

      <section v-if="local.purpose || isRevealed('purpose')">
        <h4 class="text-sm font-bold text-slate-600 mb-1">动机</h4>
        <p v-if="isRevealed('purpose') && local.purpose" class="text-sm text-slate-800">
          {{ local.purpose }}
        </p>
        <p v-else-if="!isRevealed('purpose') && local.purpose"
           class="text-sm text-slate-400 italic">**** {{ HIDDEN_HINT }}</p>
      </section>

      <section v-if="local.description || isRevealed('description')">
        <h4 class="text-sm font-bold text-slate-600 mb-1">描述</h4>
        <p v-if="isRevealed('description') && local.description"
           class="text-sm text-slate-800 whitespace-pre-line">
          {{ local.description }}
        </p>
        <p v-else-if="!isRevealed('description') && local.description"
           class="text-sm text-slate-400 italic">**** {{ HIDDEN_HINT }}</p>
      </section>

      <section v-if="isRevealed('favor') || affinityEntries.length">
        <h4 class="text-sm font-bold text-slate-600 mb-2">亲密度</h4>
        <div class="space-y-2 text-sm">
          <div v-if="isRevealed('favor')" class="flex items-center gap-2">
            <span class="w-16 text-slate-500">好感度</span>
            <div class="flex-1 bg-slate-100 rounded h-3 relative overflow-hidden">
              <div class="absolute top-0 bottom-0 left-1/2 w-px bg-slate-400/40"></div>
              <div
                class="absolute top-0 bottom-0"
                :class="barColor(local.favor)"
                :style="{ width: barWidth(local.favor), left: local.favor >= 0 ? '50%' : 'auto', right: local.favor < 0 ? '50%' : 'auto' }"
              ></div>
            </div>
            <span class="w-12 text-right font-mono text-slate-600">
              {{ local.favor >= 0 ? '+' : '' }}{{ local.favor }}
            </span>
          </div>
          <template v-if="isRevealed('affinity') && affinityEntries.length">
            <div
              v-for="[axis, val] in affinityEntries"
              :key="axis"
              class="flex items-center gap-2"
            >
              <span class="w-16 text-slate-500">{{ axis }}</span>
              <div class="flex-1 bg-slate-100 rounded h-3 relative overflow-hidden">
                <div class="absolute top-0 bottom-0 left-1/2 w-px bg-slate-400/40"></div>
                <div
                  class="absolute top-0 bottom-0"
                  :class="barColor(val)"
                  :style="{ width: barWidth(val), left: val >= 0 ? '50%' : 'auto', right: val < 0 ? '50%' : 'auto' }"
                ></div>
              </div>
              <span class="w-12 text-right font-mono text-slate-600">
                {{ val >= 0 ? '+' : '' }}{{ val }}
              </span>
            </div>
          </template>
        </div>
      </section>

      <section v-if="isRevealed('emotion') && emotionEntries.length">
        <h4 class="text-sm font-bold text-slate-600 mb-2">情绪</h4>
        <div class="space-y-1 text-xs">
          <div
            v-for="[axis, val] in emotionEntries"
            :key="axis"
            class="flex items-center gap-2"
          >
            <span class="w-12 text-slate-500">
              {{ EMOTION_LABELS[axis] || axis }}
            </span>
            <div class="flex-1 h-1.5 bg-slate-200 rounded overflow-hidden">
              <div
                class="h-full transition-all"
                :class="EMOTION_NEGATIVE.has(axis) ? 'bg-rose-400' : 'bg-emerald-400'"
                :style="{ width: Math.max(0, Math.min(100, val)) + '%' }"
              ></div>
            </div>
            <span class="font-mono w-8 text-right">{{ val }}</span>
          </div>
        </div>
      </section>

      <section v-if="timelineEntries.length">
        <h4 class="text-sm font-bold text-slate-600 mb-2">互动时间线</h4>
        <ul class="space-y-1 text-sm">
          <li
            v-for="(n, i) in timelineEntries"
            :key="i"
            class="flex gap-2 border-l-2 border-slate-200 pl-3"
          >
            <span class="text-xs text-slate-400 font-mono shrink-0 w-12">
              T{{ n.turn }}
            </span>
            <span class="text-slate-700">{{ n.text }}</span>
          </li>
        </ul>
      </section>

      <section v-if="appStore.ttsEnabled">
        <h4 class="text-sm font-bold text-slate-600 mb-1">TTS 音色</h4>

        <!-- edge mode: dropdown -->
        <template v-if="appStore.ttsMode === 'edge'">
          <div class="flex items-center gap-2">
            <el-select
              style="flex:1"
              :model-value="local.tts_voice ?? ''"
              :disabled="voiceSaving"
              placeholder="自动（按性格原型）"
              clearable
              filterable
              @change="(v: string) => saveVoice(v)"
              @clear="saveVoice('')"
            >
              <el-option label="自动（按性格原型）" value="" />
              <el-option v-for="v in edgeVoiceOptions" :key="v.voice" :label="v.label" :value="v.voice" />
            </el-select>
            <el-button size="small" circle :loading="ttsSpeaking"
              title="试听" @click="previewVoice(local.name + '，你好', effectiveEdgeVoice)">🔊</el-button>
          </div>
          <div class="text-xs text-slate-400 mt-1">
            留空则根据「{{ local.archetype || '性格原型' }}」自动分配：{{ autoVoiceLabel }}
          </div>
        </template>

        <!-- kokoro mode: dropdown -->
        <template v-else-if="appStore.ttsMode === 'kokoro'">
          <div class="flex items-center gap-2">
            <el-select
              style="flex:1"
              :model-value="local.tts_voice ?? ''"
              :disabled="voiceSaving"
              placeholder="自动（按性格原型）"
              clearable
              filterable
              @change="(v: string) => saveVoice(v)"
              @clear="saveVoice('')"
            >
              <el-option label="自动（按性格原型）" value="" />
              <el-option v-for="v in kokoroVoiceOptions" :key="v.value" :label="v.label" :value="v.value" />
            </el-select>
            <el-button size="small" circle :loading="ttsSpeaking"
              title="试听" @click="previewVoice(local.name + '，你好', effectiveKokoroVoice)">🔊</el-button>
          </div>
          <div class="text-xs text-slate-400 mt-1">
            留空则根据「{{ local.archetype || '性格原型' }}」自动分配：{{ autoKokoroVoiceLabel }}
          </div>
        </template>

        <!-- webspeech / local: free text -->
        <template v-else>
          <div class="flex items-center gap-2">
            <el-input
              style="flex:1"
              :model-value="local.tts_voice ?? ''"
              :disabled="voiceSaving"
              placeholder="留空则使用旁白默认音色"
              clearable
              @change="(v: string) => saveVoice(v)"
              @clear="saveVoice('')"
            />
            <el-button size="small" circle :loading="ttsSpeaking"
              title="试听" @click="previewVoice(local.name + '，你好', local.tts_voice || '')">🔊</el-button>
          </div>
          <div class="text-xs text-slate-400 mt-1">
            本地模式填 voice 参数名（如 af_sky）；Web Speech 填音色全名。
          </div>
        </template>
      </section>
    </div>

    <template #footer>
      <div class="flex items-center justify-between w-full">
        <el-button
          :type="local?.pinned ? 'warning' : 'default'"
          :loading="saving"
          @click="togglePin"
        >
          {{ local?.pinned ? '★ 已置顶（再次点击取消）' : '☆ 置顶到关键 NPC' }}
        </el-button>
        <el-button @click="close">关闭</el-button>
      </div>
    </template>
  </el-dialog>
</template>
