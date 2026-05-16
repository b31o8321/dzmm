<script setup lang="ts">
import { computed, ref } from 'vue'
import type { PCGoalItem } from '@/api/sessions'
import type { StatBlock, Vitals, InventoryItem, CombatSlot, ResolutionRecord } from '@/api/sessions'
import { ElPopover, ElProgress, ElTooltip, ElTag } from 'element-plus'
import FactionGraph from './game/FactionGraph.vue'
import Timeline from './game/Timeline.vue'

const threadsExpanded = ref(false)
const skillsExpanded = ref(false)

const props = defineProps<{
  sessionId: number
  stats: Record<string, number>
  statsTrend?: Record<string, number[]>
  inventory: string[]
  npcs: { name: string; favor: number; state: string; pinned?: boolean; current_location?: string | null; met?: boolean; emotion?: Record<string, number> }[]
  threads: { type: string; description: string; importance: number }[]
  goals?: PCGoalItem[]
  pcMood?: Record<string, number>
  topologyWarnings?: string[]
  currentLocation?: {
    name: string
    description: string
    items?: { name: string; description: string }[]
  } | null
  worldTime?: { day: number; period: string; weather: string }
  // v0.15 new props — all optional for backwards compat
  vitals?: Vitals
  attributes?: StatBlock
  skills?: Record<string, number>
  inventoryV2?: InventoryItem[]
  equipment?: Record<string, string | null>
  combatOrder?: CombatSlot[]
  recentResolutions?: ResolutionRecord[]
}>()

const PERIOD_CN: Record<string, string> = {
  dawn: '凌晨', morning: '上午', noon: '正午',
  afternoon: '下午', dusk: '黄昏', night: '夜晚', midnight: '深夜',
}

const worldTimeStr = computed(() => {
  if (!props.worldTime) return ''
  const period = PERIOD_CN[props.worldTime.period] ?? props.worldTime.period
  const parts = [`第 ${props.worldTime.day} 天`, period]
  if (props.worldTime.weather) parts.push(props.worldTime.weather)
  return parts.join(' · ')
})

const presentNpcs = computed(() =>
  props.currentLocation
    ? props.npcs.filter(
        (n) =>
          n.current_location &&
          n.current_location.toLowerCase() === props.currentLocation!.name.toLowerCase(),
      )
    : [],
)

const emit = defineEmits<{
  (e: 'select-npc', name: string): void
  (e: 'goal-status', goalId: number, status: 'active' | 'completed' | 'abandoned'): void
}>()

// ── D&D attribute helpers ────────────────────────────────────────────
const ATTR_LABELS: { key: keyof StatBlock; cn: string; en: string }[] = [
  { key: 'strength',     cn: '力量', en: 'STR' },
  { key: 'dexterity',    cn: '敏捷', en: 'DEX' },
  { key: 'constitution', cn: '体质', en: 'CON' },
  { key: 'intelligence', cn: '智力', en: 'INT' },
  { key: 'wisdom',       cn: '感知', en: 'WIS' },
  { key: 'charisma',     cn: '魅力', en: 'CHA' },
]

function attrMod(val: number): string {
  const m = Math.floor((val - 10) / 2)
  return m >= 0 ? `+${m}` : `${m}`
}

const topTwoAttrKeys = computed<Set<keyof StatBlock>>(() => {
  if (!props.attributes) return new Set()
  const entries = ATTR_LABELS.map((a) => ({ key: a.key, val: props.attributes![a.key] }))
  entries.sort((a, b) => b.val - a.val)
  return new Set(entries.slice(0, 2).map((e) => e.key))
})

// ── Skills ─────────────────────────────────────────────────────────
const sortedSkills = computed(() => {
  if (!props.skills) return []
  return Object.entries(props.skills).sort((a, b) => b[1] - a[1])
})

const visibleSkills = computed(() =>
  skillsExpanded.value ? sortedSkills.value : sortedSkills.value.slice(0, 5),
)

// ── Inventory v2 ───────────────────────────────────────────────────
const ITEM_TYPE_LABELS: Record<string, string> = {
  weapon: '武器', armor: '护甲', consumable: '消耗品', key: '钥匙', quest: '任务物品',
}
const ITEM_ICONS: Record<string, string> = {
  weapon: '⚔️', armor: '🛡️', consumable: '🧪', key: '🔑', quest: '📜',
}
const EFFECT_ICONS: Record<string, string> = {
  heal_hp: '🩺', heal_sanity: '🧠', heal_stamina: '⚡',
  damage: '💥', stat_bonus: '📈', skill_bonus: '🎯',
  armor_bonus: '🛡️', attack_attribute: '⚔️', consume: '✨', unlock: '🔓',
}

const groupedInventory = computed(() => {
  if (!props.inventoryV2?.length) return []
  const groups: { type: string; label: string; icon: string; items: InventoryItem[] }[] = []
  const typeOrder = ['weapon', 'armor', 'consumable', 'key', 'quest']
  for (const t of typeOrder) {
    const items = props.inventoryV2!.filter((i) => i.item_type === t)
    if (items.length) {
      groups.push({ type: t, label: ITEM_TYPE_LABELS[t] ?? t, icon: ITEM_ICONS[t] ?? '📦', items })
    }
  }
  return groups
})

function effectChipLabel(eff: InventoryItem['effects'][number]): string {
  const icon = EFFECT_ICONS[eff.type] ?? '✨'
  if (eff.type === 'heal_hp') return `${icon} +${eff.amount ?? 0} HP`
  if (eff.type === 'heal_sanity') return `${icon} +${eff.amount ?? 0} SAN`
  if (eff.type === 'heal_stamina') return `${icon} +${eff.amount ?? 0} STA`
  if (eff.type === 'damage') return `${icon} ${eff.formula ?? eff.amount ?? '?'}`
  if (eff.type === 'armor_bonus') return `${icon} AC+${eff.amount ?? 0}`
  if (eff.type === 'stat_bonus') return `${icon} ${eff.stat ?? ''}`
  if (eff.type === 'skill_bonus') return `${icon} ${eff.skill ?? ''}`
  return `${icon} ${eff.type}`
}

// ── Equipment slots ─────────────────────────────────────────────────
const EQUIP_SLOTS = [
  { key: 'weapon', label: '武器', icon: '⚔️' },
  { key: 'armor', label: '护甲', icon: '🛡️' },
  { key: 'accessory', label: '饰品', icon: '💍' },
]

// ── Resolution feed ─────────────────────────────────────────────────
function formatResolution(r: ResolutionRecord): string {
  const k = r.kind
  const res = r.result as Record<string, unknown>
  const inp = r.input as Record<string, unknown>
  if (k === 'dice') {
    const expr = inp.expression ?? inp.formula ?? '?'
    const total = res.total ?? res.result ?? '?'
    return `🎲 ${expr} = ${total}`
  }
  if (k === 'skill') {
    const skill = inp.skill_name ?? inp.skill ?? '?'
    const dc = inp.dc ?? '?'
    const roll = res.roll ?? res.total ?? '?'
    const success = res.success ? '✅' : '❌'
    return `🎯 ${skill} vs DC${dc}: ${roll} → ${success}`
  }
  if (k === 'attack') {
    const attacker = inp.attacker_name ?? '你'
    const target = inp.target_name ?? '?'
    const hit = res.hit ? '命中' : '未中'
    const dmg = res.damage ?? ''
    const d20 = res.attack_roll ?? ''
    return `⚔️ ${attacker} → ${target}: d20=${d20} ${hit}${dmg ? ', ' + dmg + ' 伤害' : ''}`
  }
  if (k === 'initiative') {
    const order = (res.order ?? res.combat_order) as Array<{ name?: string; initiative_total?: number; total?: number }> | undefined
    if (Array.isArray(order) && order.length) {
      const parts = order.map((o) => `${o.name ?? '?'}(${o.initiative_total ?? o.total ?? '?'})`)
      return `先攻 ${parts.join(' → ')}`
    }
    return '先攻投骰'
  }
  if (k === 'item') {
    const item = inp.item_name ?? inp.name ?? '?'
    const summary = res.summary ?? res.result ?? ''
    return `🩹 ${item}${summary ? ' → ' + summary : ''}`
  }
  return `${k}: ${JSON.stringify(res).slice(0, 60)}`
}

// ── Legacy stats (fallback when no vitals) ──────────────────────────
const STAT_TOOLTIPS: Record<string, string> = {
  hp: '生命值。归 0 → 倒地或死亡。低于 30% 时 GM 会描写虚弱状态。',
  HP: '生命值。归 0 → 倒地或死亡。低于 30% 时 GM 会描写虚弱状态。',
  sanity: '理智值。受恐怖、超自然、心理压力影响。低于 5 → 可能出现幻觉；归 0 → 短暂崩溃。',
  san: '理智值。受恐怖、超自然、心理压力影响。低于 5 → 可能出现幻觉；归 0 → 短暂崩溃。',
  mp: '法力值 / 内力。释放法术或特殊技能时消耗。',
  MP: '法力值 / 内力。释放法术或特殊技能时消耗。',
}

function tooltipFor(key: string): string {
  return STAT_TOOLTIPS[key] || ''
}

function npcAvatarColor(name: string): string {
  let h = 0
  for (let i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) & 0xffff
  return `hsl(${h % 360}, 52%, 50%)`
}

function topEmotion(emotion?: Record<string, number>): string {
  if (!emotion || !Object.keys(emotion).length) return ''
  const [key] = Object.entries(emotion).sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]))[0]
  return key
}

function sparklinePath(values: number[]): string {
  if (values.length < 2) return ''
  const w = 40, h = 14
  const min = Math.min(...values), max = Math.max(...values)
  const range = max - min || 1
  const pts = values.map((v, i) => {
    const x = (i / (values.length - 1)) * w
    const y = h - ((v - min) / range) * h
    return `${x.toFixed(1)},${y.toFixed(1)}`
  })
  return 'M' + pts.join('L')
}

function sparklineColor(values: number[]): string {
  if (values.length < 2) return '#94a3b8'
  const delta = values[values.length - 1] - values[0]
  return delta > 0 ? '#22c55e' : delta < 0 ? '#ef4444' : '#94a3b8'
}

// ── Combat HUD ─────────────────────────────────────────────────────
const hasCombat = computed(() => (props.combatOrder?.length ?? 0) > 0)
// Determine the current first combatant (index 0 = current turn in initiative order)
const currentCombatantName = computed(() =>
  props.combatOrder && props.combatOrder.length > 0 ? props.combatOrder[0].name : '',
)

function npcHpFromList(name: string): number | null {
  const npc = props.npcs.find((n) => n.name === name)
  if (!npc) return null
  // Try stats if available (legacy), or use from vitals if it's the PC
  return null
}

function onEndCombat() {
  // Clear combat order locally; next state refetch will reconcile
  if (props.combatOrder) {
    props.combatOrder.splice(0, props.combatOrder.length)
  }
}
</script>

<template>
  <aside class="w-full bg-white">
    <!-- Sticky top bar: world time + faction/timeline popovers -->
    <div class="sticky top-0 z-10 px-3 py-2 border-b border-slate-200 bg-white/95 backdrop-blur flex items-center justify-between text-xs">
      <span v-if="worldTimeStr" class="text-slate-600 font-medium">🕐 {{ worldTimeStr }}</span>
      <span v-else class="text-slate-300">—</span>
      <div class="flex items-center gap-0.5">
        <el-popover :width="380" placement="bottom-end" trigger="click">
          <template #reference>
            <button type="button"
                    class="text-slate-500 hover:text-slate-700 px-1.5 py-0.5 rounded hover:bg-slate-100"
                    title="大事记">📅</button>
          </template>
          <Timeline :events="threads.map((t) => ({ ...t, introduced_turn: undefined, status: 'active' }))" />
        </el-popover>
        <el-popover :width="380" placement="bottom-end" trigger="click">
          <template #reference>
            <button type="button"
                    class="text-slate-500 hover:text-slate-700 px-1.5 py-0.5 rounded hover:bg-slate-100"
                    title="势力">⚖️</button>
          </template>
          <FactionGraph :session-id="sessionId" :visible="true" />
        </el-popover>
      </div>
    </div>

    <!-- Topology warnings -->
    <div v-if="topologyWarnings && topologyWarnings.length"
         class="px-3 py-1.5 bg-amber-50 border-b border-amber-200">
      <div class="text-xs font-medium text-amber-700 mb-0.5">⚠️ 拓扑警告</div>
      <ul class="space-y-0.5">
        <li v-for="(w, i) in topologyWarnings" :key="i" class="text-xs text-amber-600 leading-snug">{{ w }}</li>
      </ul>
    </div>

    <div class="p-3 space-y-4">

      <!-- ── g) Combat HUD — shown only when in combat ── -->
      <section v-if="hasCombat" class="border border-red-200 rounded bg-red-50 p-2">
        <div class="flex items-center justify-between mb-1.5">
          <span class="text-xs font-bold text-red-700">⚔️ 战斗中</span>
          <button type="button"
                  class="text-xs text-slate-400 hover:text-red-600 px-1.5 py-0.5 border border-slate-200 rounded hover:border-red-300"
                  @click="onEndCombat">结束战斗</button>
        </div>
        <div class="flex gap-1.5 overflow-x-auto pb-1">
          <div v-for="(slot, idx) in combatOrder" :key="slot.id + slot.kind"
               class="flex-shrink-0 flex flex-col items-center px-2 py-1 rounded text-xs font-medium border"
               :class="idx === 0
                 ? 'bg-red-500 text-white border-red-600'
                 : slot.kind === 'pc'
                   ? 'bg-blue-50 text-blue-700 border-blue-200'
                   : 'bg-slate-50 text-slate-700 border-slate-200'">
            <span class="truncate max-w-[4rem]">{{ slot.name }}</span>
            <span class="text-[10px] opacity-70">{{ slot.initiative_total }}</span>
          </div>
        </div>
      </section>

      <!-- ── Current location ── -->
      <div v-if="currentLocation" class="bg-blue-50 border border-blue-200 rounded px-3 py-2 text-sm">
        <div class="text-xs text-slate-500">当前场所</div>
        <div class="font-bold text-blue-800">📍 {{ currentLocation.name }}</div>
        <div v-if="currentLocation.description" class="text-xs text-slate-500 mt-0.5 leading-snug">
          {{ currentLocation.description }}
        </div>
        <div v-if="currentLocation.items?.length" class="text-xs text-slate-500 mt-1">
          <span class="font-medium">物品：</span>{{ currentLocation.items.map((i) => i.name).join('、') }}
        </div>
        <div v-if="presentNpcs.length" class="mt-2 pt-2 border-t border-blue-200">
          <div class="text-xs font-medium text-blue-700 mb-1">此处人物</div>
          <ul class="space-y-0.5">
            <li v-for="n in presentNpcs" :key="n.name" class="flex items-center gap-1.5 text-xs">
              <span class="w-2 h-2 rounded-full flex-shrink-0"
                    :class="n.favor >= 20 ? 'bg-green-400' : n.favor <= -20 ? 'bg-red-400' : 'bg-slate-300'" />
              <span class="text-slate-700 font-medium">{{ n.name }}</span>
              <span v-if="n.state" class="text-slate-400 truncate">· {{ n.state }}</span>
            </li>
          </ul>
        </div>
      </div>

      <!-- ── a) Vitals (v0.15) — HP / Sanity / Stamina progress bars ── -->
      <section v-if="vitals">
        <h3 class="font-bold text-slate-700 mb-2 text-sm">生命状态</h3>
        <div class="space-y-1.5">
          <!-- HP -->
          <div>
            <div class="flex justify-between text-xs text-slate-500 mb-0.5">
              <span class="font-medium text-red-600">❤️ HP</span>
              <span class="font-mono">{{ vitals.hp }} / {{ vitals.max_hp }}</span>
            </div>
            <el-progress
              :percentage="Math.round((vitals.hp / Math.max(vitals.max_hp, 1)) * 100)"
              :show-text="false"
              :stroke-width="8"
              color="#ef4444"
            />
          </div>
          <!-- Sanity -->
          <div>
            <div class="flex justify-between text-xs text-slate-500 mb-0.5">
              <span class="font-medium text-purple-600">🧠 理智</span>
              <span class="font-mono">{{ vitals.sanity }} / {{ vitals.max_sanity }}</span>
            </div>
            <el-progress
              :percentage="Math.round((vitals.sanity / Math.max(vitals.max_sanity, 1)) * 100)"
              :show-text="false"
              :stroke-width="8"
              color="#7c3aed"
            />
          </div>
          <!-- Stamina -->
          <div>
            <div class="flex justify-between text-xs text-slate-500 mb-0.5">
              <span class="font-medium text-yellow-600">⚡ 体力</span>
              <span class="font-mono">{{ vitals.stamina }} / {{ vitals.max_stamina }}</span>
            </div>
            <el-progress
              :percentage="Math.round((vitals.stamina / Math.max(vitals.max_stamina, 1)) * 100)"
              :show-text="false"
              :stroke-width="8"
              color="#d97706"
            />
          </div>
        </div>
      </section>

      <!-- Fallback: legacy free-form stats when no vitals -->
      <section v-else>
        <h3 class="font-bold text-slate-700 mb-2 text-sm">角色状态</h3>
        <div class="space-y-1 text-sm">
          <el-tooltip
            v-for="(v, k) in stats"
            :key="k"
            :content="tooltipFor(String(k))"
            :disabled="!tooltipFor(String(k))"
            placement="left"
          >
            <div
              class="flex items-center justify-between gap-2"
              :class="tooltipFor(String(k)) ? 'cursor-help' : ''"
            >
              <span class="text-slate-500 shrink-0">{{ k }}</span>
              <div class="flex items-center gap-1.5 ml-auto">
                <svg
                  v-if="statsTrend && statsTrend[String(k)] && statsTrend[String(k)].length >= 2"
                  width="40" height="14" class="shrink-0"
                >
                  <path
                    :d="sparklinePath(statsTrend[String(k)])"
                    fill="none"
                    :stroke="sparklineColor(statsTrend[String(k)])"
                    stroke-width="1.5"
                    stroke-linejoin="round"
                    stroke-linecap="round"
                  />
                </svg>
                <span class="font-mono">{{ v }}</span>
              </div>
            </div>
          </el-tooltip>
          <div v-if="!Object.keys(stats).length" class="text-slate-400 italic">尚未初始化</div>
        </div>
      </section>

      <!-- ── b) D&D Attributes ── -->
      <section v-if="attributes">
        <h3 class="font-bold text-slate-700 mb-2 text-sm">属性</h3>
        <div class="grid grid-cols-2 gap-x-3 gap-y-1">
          <div v-for="a in ATTR_LABELS" :key="a.key"
               class="flex items-center justify-between text-xs px-1.5 py-0.5 rounded"
               :class="topTwoAttrKeys.has(a.key) ? 'bg-blue-50 text-blue-800' : 'text-slate-600'">
            <span class="font-medium">{{ a.cn }} <span class="opacity-50">{{ a.en }}</span></span>
            <span class="font-mono">
              {{ attributes[a.key] }}
              <span class="text-slate-400 ml-0.5">({{ attrMod(attributes[a.key]) }})</span>
            </span>
          </div>
        </div>
      </section>

      <!-- ── c) Skills ── -->
      <section v-if="sortedSkills.length">
        <h3 class="font-bold text-slate-700 mb-2 text-sm">技能</h3>
        <div class="space-y-1">
          <div v-for="[name, level] in visibleSkills" :key="name"
               class="flex items-center gap-2 text-xs">
            <span class="text-slate-600 w-16 shrink-0 truncate" :title="name">{{ name }}</span>
            <div class="flex-1 bg-slate-100 rounded-full h-1.5 overflow-hidden">
              <div class="h-full bg-slate-500 rounded-full"
                   :style="{ width: level + '%' }" />
            </div>
            <span class="font-mono text-slate-500 w-7 text-right">{{ level }}%</span>
          </div>
        </div>
        <button
          v-if="sortedSkills.length > 5"
          type="button"
          class="text-xs text-slate-400 hover:text-amber-600 mt-1.5"
          @click="skillsExpanded = !skillsExpanded"
        >
          {{ skillsExpanded ? '收起' : `展开全部 (+${sortedSkills.length - 5})` }}
        </button>
      </section>

      <!-- ── d) Equipment ── -->
      <section v-if="equipment && Object.keys(equipment).length">
        <h3 class="font-bold text-slate-700 mb-2 text-sm">装备</h3>
        <div class="grid grid-cols-3 gap-1.5">
          <div v-for="slot in EQUIP_SLOTS" :key="slot.key"
               class="border border-slate-200 rounded px-2 py-1.5 text-center text-xs">
            <div class="text-base mb-0.5">{{ slot.icon }}</div>
            <div class="text-slate-400 text-[10px] mb-0.5">{{ slot.label }}</div>
            <div class="font-medium truncate"
                 :class="equipment[slot.key] ? 'text-slate-700' : 'text-slate-300 italic'">
              {{ equipment[slot.key] ?? '（空）' }}
            </div>
          </div>
        </div>
      </section>

      <!-- ── e) Inventory v2 (grouped by type) ── -->
      <section v-if="groupedInventory.length">
        <h3 class="font-bold text-slate-700 mb-2 text-sm">背包</h3>
        <div class="space-y-2">
          <div v-for="group in groupedInventory" :key="group.type">
            <div class="text-xs text-slate-400 font-medium mb-1">{{ group.icon }} {{ group.label }}</div>
            <ul class="space-y-1.5 pl-1">
              <li v-for="item in group.items" :key="item.name" class="text-xs">
                <div class="flex items-start gap-1">
                  <span class="font-medium text-slate-700 flex-1">{{ item.name }}</span>
                  <span v-if="item.qty > 1" class="text-slate-400 shrink-0">×{{ item.qty }}</span>
                </div>
                <div v-if="item.effects.length" class="flex flex-wrap gap-1 mt-0.5">
                  <el-tooltip
                    v-for="(eff, i) in item.effects"
                    :key="i"
                    :content="item.description || eff.type"
                    placement="top"
                  >
                    <span class="inline-block px-1 py-0.5 bg-slate-100 text-slate-600 rounded text-[10px] cursor-help">
                      {{ effectChipLabel(eff) }}
                    </span>
                  </el-tooltip>
                </div>
              </li>
            </ul>
          </div>
        </div>
      </section>

      <!-- Fallback: legacy plain-string inventory -->
      <section v-else-if="inventory.length || !groupedInventory.length">
        <h3 class="font-bold text-slate-700 mb-2 text-sm">背包</h3>
        <ul class="space-y-1 text-sm">
          <li v-for="item in inventory" :key="item">· {{ item }}</li>
          <li v-if="!inventory.length" class="text-slate-400 italic">空</li>
        </ul>
      </section>

      <!-- ── f) Recent Resolutions ── -->
      <section v-if="recentResolutions && recentResolutions.length">
        <h3 class="font-bold text-slate-700 mb-2 text-sm">近期检定</h3>
        <ul class="space-y-1">
          <li v-for="(r, i) in recentResolutions.slice().reverse()" :key="i"
              class="text-xs text-slate-600 bg-slate-50 px-2 py-1 rounded leading-snug">
            <span class="text-slate-400 mr-1">T{{ r.turn }}</span>{{ formatResolution(r) }}
          </li>
        </ul>
      </section>

      <!-- ── PC Mood ── -->
      <section v-if="pcMood && Object.keys(pcMood).length">
        <h3 class="font-bold text-slate-700 mb-2 text-sm">心情</h3>
        <div class="flex flex-wrap gap-1.5">
          <span
            v-for="(v, k) in pcMood"
            :key="k"
            class="inline-flex items-center gap-1 px-2 py-0.5 bg-violet-50 text-violet-700 rounded text-xs"
          >
            {{ k }}<span class="font-mono opacity-60">{{ v }}</span>
          </span>
        </div>
      </section>

      <!-- ── Plot Threads ── -->
      <section v-if="threads.length">
        <h3 class="font-bold text-slate-700 mb-2 text-sm">剧情线</h3>
        <ul class="space-y-1 text-sm">
          <li v-for="(t, i) in (threadsExpanded ? threads : threads.slice(0, 5))" :key="i">
            <span class="text-amber-600 mr-1">{{ '★'.repeat(t.importance) }}</span>
            <span class="text-xs text-slate-500 mr-1">[{{ t.type }}]</span>
            {{ t.description }}
          </li>
        </ul>
        <button
          v-if="threads.length > 5"
          type="button"
          class="text-xs text-slate-400 hover:text-amber-600 mt-2"
          @click="threadsExpanded = !threadsExpanded"
        >
          {{ threadsExpanded ? '收起' : `展开 (+${threads.length - 5})` }}
        </button>
      </section>

      <!-- ── Goals ── -->
      <section v-if="goals && goals.length">
        <h3 class="font-bold text-slate-700 mb-2 text-sm">🎯 我的目标</h3>
        <ul class="space-y-2 text-sm">
          <li v-for="g in goals.filter(x => x.status === 'active')" :key="g.id"
              class="flex items-start gap-2">
            <span class="text-amber-500 text-xs pt-0.5 shrink-0">
              {{ g.priority === 'high' ? '★★★' : g.priority === 'low' ? '★' : '★★' }}
            </span>
            <span class="flex-1">{{ g.description }}</span>
            <button type="button" class="text-xs text-slate-400 hover:text-emerald-500"
                    title="标记完成"
                    @click="emit('goal-status', g.id, 'completed')">✓</button>
          </li>
        </ul>
        <details v-if="goals.some(g => g.status !== 'active')" class="mt-2">
          <summary class="text-xs text-slate-400 cursor-pointer">
            已完成 / 已放弃 ({{ goals.filter(g => g.status !== 'active').length }})
          </summary>
          <ul class="mt-1 space-y-1 text-xs text-slate-500 pl-4">
            <li v-for="g in goals.filter(x => x.status !== 'active')" :key="g.id"
                class="flex items-start gap-2">
              <span class="line-through opacity-60 flex-1">{{ g.description }}</span>
              <span class="text-slate-400">{{ g.status === 'completed' ? '✓' : '✕' }}</span>
            </li>
          </ul>
        </details>
      </section>

      <!-- ── NPC Relations ── -->
      <section>
        <h3 class="font-bold text-slate-700 mb-2 text-sm">NPC 关系</h3>
        <ul class="space-y-1 text-sm">
          <li
            v-for="n in npcs"
            :key="n.name"
            class="flex justify-between items-center gap-2"
            :class="{ 'opacity-50': n.met === false }"
          >
            <button
              type="button"
              class="text-left hover:underline hover:text-amber-700 truncate flex items-center gap-1.5"
              @click="emit('select-npc', n.name)"
              :title="n.met === false ? `${n.name}（未登场）` : `查看 ${n.name} 的详情`"
            >
              <span
                class="inline-flex items-center justify-center w-5 h-5 rounded-full text-white text-xs font-bold shrink-0 select-none"
                :style="{ backgroundColor: n.met === false ? '#cbd5e1' : npcAvatarColor(n.name) }"
              >{{ n.name[0] }}</span>
              <span v-if="n.pinned" class="text-amber-500" title="已置顶">📌</span>
              <span>{{ n.name }}</span>
            </button>
            <div class="flex items-center gap-1 shrink-0">
              <template v-if="n.met === false">
                <span class="text-xs italic text-slate-400">未登场</span>
              </template>
              <template v-else>
                <span
                  v-if="topEmotion(n.emotion)"
                  class="text-xs px-1 py-0.5 bg-violet-50 text-violet-600 rounded"
                  :title="Object.entries(n.emotion ?? {}).map(([k,v]) => `${k}:${v}`).join(' ')"
                >{{ topEmotion(n.emotion) }}</span>
                <span class="font-mono text-slate-500">{{ n.favor >= 0 ? '+' : '' }}{{ n.favor }}</span>
              </template>
            </div>
          </li>
          <li v-if="!npcs.length" class="text-slate-400 italic">尚无 NPC</li>
        </ul>
      </section>

    </div>
  </aside>
</template>
