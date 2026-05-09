import { reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { sessionsApi, type PCGoalItem } from '@/api/sessions'

export const MAX_DICE = 8

export function useGameState() {
  const stats = reactive<Record<string, number>>({})
  const inventory = ref<string[]>([])
  const npcs = ref<{ name: string; favor: number; state: string; pinned?: boolean; current_location?: string | null; met?: boolean; emotion?: Record<string, number> }[]>([])
  const dice = ref<{ skill: string; target: string; result: string; success?: string; fail?: string }[]>([])
  const threads = ref<{ type: string; description: string; importance: number }[]>([])
  const pcMood = ref<Record<string, number>>({})
  const goals = ref<PCGoalItem[]>([])

  function applyStateChange(content: string) {
    try {
      const obj = JSON.parse(content)
      for (const [k, v] of Object.entries(obj)) {
        if (k === 'inventory_add' && Array.isArray(v)) {
          inventory.value.push(...(v as string[]))
        } else if (k === 'inventory_remove' && Array.isArray(v)) {
          for (const item of v as string[]) {
            const idx = inventory.value.indexOf(item)
            if (idx >= 0) inventory.value.splice(idx, 1)
          }
        } else if (typeof v === 'number') {
          stats[k] = (stats[k] ?? 0) + v
        }
      }
    } catch {
      /* ignore malformed */
    }
  }

  function applyNpcUpdate(content: string) {
    try {
      const obj = JSON.parse(content)
      if (!obj.name) return
      const existing = npcs.value.find((n) => n.name === obj.name)
      if (existing) {
        if (typeof obj.favor_delta === 'number') existing.favor += obj.favor_delta
        if (obj.state) existing.state = obj.state
      } else {
        npcs.value.push({
          name: obj.name,
          favor: obj.favor_delta ?? 0,
          state: obj.state ?? '未知',
        })
      }
    } catch {
      /* ignore */
    }
  }

  function applyPcMood(content: string) {
    try {
      const obj = JSON.parse(content)
      if (!obj || typeof obj !== 'object') return
      const next = { ...pcMood.value }
      for (const [k, v] of Object.entries(obj)) {
        if (typeof v !== 'number') continue
        const cur = next[k] ?? 0
        next[k] = Math.max(0, Math.min(100, cur + v))
      }
      pcMood.value = next
    } catch {
      /* ignore */
    }
  }

  async function refreshGoals(sessionId: number) {
    try {
      goals.value = await sessionsApi.goals(sessionId)
    } catch {
      /* ignore */
    }
  }

  async function updateGoal(
    sessionId: number,
    goalId: number,
    status: 'active' | 'completed' | 'abandoned',
  ) {
    try {
      await sessionsApi.updateGoalStatus(sessionId, goalId, status)
      await refreshGoals(sessionId)
    } catch (e: any) {
      ElMessage.error(e.message ?? '更新失败')
    }
  }

  function pushDice(d: { skill: string; target: string; result: string; success?: string; fail?: string }) {
    dice.value.unshift(d)
    if (dice.value.length > MAX_DICE) dice.value.length = MAX_DICE
  }

  return {
    stats,
    inventory,
    npcs,
    dice,
    threads,
    pcMood,
    goals,
    applyStateChange,
    applyNpcUpdate,
    applyPcMood,
    refreshGoals,
    updateGoal,
    pushDice,
  }
}
