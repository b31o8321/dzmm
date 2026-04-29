<script setup lang="ts">
import { ref, watch, computed } from 'vue'
import { ElMessage } from 'element-plus'
import { sessionsApi, type Npc } from '@/api/sessions'

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

watch(
  () => props.npc,
  (n) => { local.value = n ? { ...n, affinity: { ...n.affinity }, notes: [...(n.notes ?? [])] } : null },
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

const affinityEntries = computed(() => {
  if (!local.value) return []
  return Object.entries(local.value.affinity ?? {})
    .filter(([, v]) => typeof v === 'number')
    .sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]))
})

const timelineEntries = computed(() => {
  const list = local.value?.notes ?? []
  return [...list].sort((a, b) => b.turn - a.turn)
})
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
      <div class="flex items-center gap-2 flex-wrap">
        <span v-if="local.archetype"
              class="text-xs px-2 py-0.5 bg-amber-100 text-amber-800 rounded">
          {{ local.archetype }}
        </span>
        <span class="text-xs px-2 py-0.5 bg-slate-100 text-slate-700 rounded">
          状态：{{ local.state || '未知' }}
        </span>
        <span class="text-xs text-slate-400 ml-auto">
          上次出现：第 {{ local.last_seen_turn }} 回合
        </span>
      </div>

      <section v-if="local.purpose">
        <h4 class="text-sm font-bold text-slate-600 mb-1">动机</h4>
        <p class="text-sm text-slate-800">{{ local.purpose }}</p>
      </section>

      <section v-if="local.description">
        <h4 class="text-sm font-bold text-slate-600 mb-1">描述</h4>
        <p class="text-sm text-slate-800 whitespace-pre-line">{{ local.description }}</p>
      </section>

      <section>
        <h4 class="text-sm font-bold text-slate-600 mb-2">亲密度</h4>
        <div class="space-y-2 text-sm">
          <div class="flex items-center gap-2">
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
          <div v-if="!affinityEntries.length" class="text-xs text-slate-400 italic">
            （GM 尚未为此 NPC 标注多维亲密度）
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
