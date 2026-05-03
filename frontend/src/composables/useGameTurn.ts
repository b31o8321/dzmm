import { reactive, ref, type Ref } from 'vue'

export type SceneMood = 'neutral' | 'tense' | 'horror' | 'romantic' | 'mysterious'

const _MOOD_WORDS: Record<SceneMood, string[]> = {
  tense:      ['紧张','警戒','危险','战斗','追','逃','血','刀','剑','杀','威胁','慌','急','激烈','冲突','搏斗'],
  horror:     ['恐惧','恐怖','鬼','尸','黑暗','阴森','诡异','寒意','颤','惊悚','骇人','阴冷','异动'],
  romantic:   ['温柔','温暖','心跳','甜','红晕','羞','靠近','触碰','柔软','爱意','情意','脸红','心软'],
  mysterious: ['神秘','迷雾','秘密','预言','暗影','谜','命运','异象','古老','玄','未知','离奇'],
  neutral:    [],
}

export function detectSceneMood(narrative: string): SceneMood {
  const scores: Record<string, number> = { tense: 0, horror: 0, romantic: 0, mysterious: 0 }
  for (const [mood, words] of Object.entries(_MOOD_WORDS)) {
    if (mood === 'neutral') continue
    for (const w of words) if (narrative.includes(w)) scores[mood]++
  }
  const sorted = Object.entries(scores).sort((a, b) => b[1] - a[1])
  return sorted[0][1] >= 2 ? (sorted[0][0] as SceneMood) : 'neutral'
}
import { ElMessage } from 'element-plus'
import { streamTurn } from '@/composables/useTurnStream'
import { sessionsApi, type MessageEvent } from '@/api/sessions'
import { useAudio } from '@/composables/useAudio'

export interface Turn {
  action: string
  narrative: string
  choices: string[]
  events: MessageEvent[]
  turn: number
  rawContent?: string
}

// Narrative-content sanitisation helpers. Lifted out of GameView so the
// streaming finalizer (in this composable) and the history rehydration code
// (still in GameView) share the same regex-based recovery logic.
const ANY_KNOWN_CHILD_RE =
  /<(?:choices|state_change|npc_update|plot_event|dice)\b[^>]*>[\s\S]*?(?:<\/(?:choices|state_change|npc_update|plot_event|dice)>|$)/g
const CHOICES_RE = /<choices\b[^>]*>([\s\S]*?)<\/choices>/g

export function cleanNarrative(raw: string): string {
  return raw
    .replace(ANY_KNOWN_CHILD_RE, '')
    .replace(/<think\b[^>]*>[\s\S]*?<\/think>/gi, '')
    .replace(/<\/?\w+\b[^>]*>/g, '')
    .trim()
}

export function extractChoices(content: string): string[] {
  const out: string[] = []
  let m: RegExpExecArray | null
  CHOICES_RE.lastIndex = 0
  while ((m = CHOICES_RE.exec(content))) {
    for (const line of m[1].split('\n')) {
      const trimmed = line.trim().replace(/^[-*•・·]\s*/, '')
      if (trimmed) out.push(trimmed)
    }
  }
  return out
}

export interface GameStateBindings {
  applyStateChange: (content: string) => void
  applyNpcUpdate: (content: string) => void
  applyPcMood: (content: string) => void
  pushDice: (d: { skill: string; target: string; result: string; success?: string; fail?: string }) => void
  threads: Ref<{ type: string; description: string; importance: number }[]>
}

export interface UseGameTurnHooks {
  /** Called after a streaming chunk lands so the host can scroll the log. */
  onScroll?: () => void
  /** Called inside onDone, after turn finalisation. */
  onTurnDone?: () => void
  /** Called when the backend signals that an NPC wants to take initiative. */
  onNpcInitiative?: (npcName: string) => void
}

export function useGameTurn(
  sessionId: number,
  gs: GameStateBindings,
  hooks: UseGameTurnHooks = {},
) {
  const turns = ref<Turn[]>([])
  const currentTurn = ref<Turn | null>(null)
  const turnCount = ref(0)
  const tokensIn = ref(0)
  const tokensOut = ref(0)
  const sending = ref(false)
  const sceneMood = ref<SceneMood>('neutral')
  const audio = useAudio()

  async function sendAction(userAction: string) {
    if (!userAction || sending.value) return
    sending.value = true

    // IMPORTANT: wrap in `reactive()` so subsequent `turn.narrative += text`
    // mutations go through the Vue reactivity proxy (not just the raw object
    // reference). Without this, streaming text updates the underlying object
    // but Vue doesn't notice because the local `turn` var bypasses the proxy
    // — leading to blank narrative until a refresh re-reads from the DB.
    const turn: Turn = reactive({
      action: userAction,
      narrative: '',
      choices: [],
      events: [],
      turn: turnCount.value + 1,
    })
    currentTurn.value = turn
    const sayBuffer: string[] = []
    // Clear previous turn's choices — they're stale once the user sends.
    for (const t of turns.value) t.choices = []
    turns.value.push(turn)
    hooks.onScroll?.()

    try {
      await streamTurn(sessionId, userAction, {
        onNarrative: (text) => {
          turn.narrative += text
          hooks.onScroll?.()
        },
        onTag: (name, attrs, content) => {
          // Build a running rawContent so parseParts() can reconstruct speaker
          // bubbles after the turn finishes (and on the live frame for non-
          // streaming say/pc_action tags).
          if (name === 'say') {
            const speakerAttr = attrs.speaker ? ` speaker="${attrs.speaker}"` : ''
            sayBuffer.push(`<say${speakerAttr}>${content}</say>`)
          } else if (name === 'pc_action') {
            sayBuffer.push(`<pc_action>${content}</pc_action>`)
          }
          // Record any structured tag (besides `narrative`/`say`/`pc_action`/`choices`)
          // as an event so it shows up in the per-message events dialog.
          const skipForEvents = new Set(['narrative', 'narriative', 'say', 'pc_action', 'choices'])
          if (!skipForEvents.has(name)) {
            let payload: Record<string, any> = { ...attrs }
            const trimmed = content.trim()
            if (trimmed) {
              try {
                const parsed = JSON.parse(trimmed)
                if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
                  payload = { ...payload, ...parsed }
                } else {
                  payload = { ...payload, value: parsed }
                }
              } catch {
                payload = { ...payload, content: trimmed }
              }
            }
            turn.events.push({ type: name, payload, content: trimmed || undefined })
          }
          if (name === 'state_change') {
            try {
              const obj = JSON.parse(content)
              let totalDelta = 0
              for (const [, v] of Object.entries(obj)) {
                if (typeof v === 'number') totalDelta += v
              }
              if (totalDelta < 0) audio.playSfx('state_down')
              else if (totalDelta > 0) audio.playSfx('state_up')
            } catch { /* ignore */ }
            gs.applyStateChange(content)
          }
          else if (name === 'npc_update') gs.applyNpcUpdate(content)
          else if (name === 'pc_mood') gs.applyPcMood(content)
          else if (name === 'choices') {
            const opts: string[] = []
            for (const line of content.split('\n')) {
              const trimmed = line.trim().replace(/^[-*•・·]\s*/, '')
              if (trimmed) opts.push(trimmed)
            }
            turn.choices = opts
          }
          else if (name === 'dice') {
            audio.playSfx('dice')
            gs.pushDice({
              skill: attrs.skill ?? '判定',
              target: attrs.target ?? '?',
              result: content.trim() || '?',
              success: attrs.success || undefined,
              fail: attrs.fail || undefined,
            })
          }
          else if (name === 'plot_event') {
            let importance = 2
            const parsed = parseInt(attrs.importance ?? '2', 10)
            if (!isNaN(parsed)) importance = Math.max(1, Math.min(3, parsed))
            // Drop importance=1 trivia — they belong in narrative, not the sidebar.
            if (importance >= 2) {
              gs.threads.value.push({
                type: attrs.type ?? 'major_event',
                description: content.trim(),
                importance,
              })
            }
          }
          else if (name === 'narrative_revised') {
            // Optional polish pass: replace the streaming narrative placeholder.
            const polished = content.trim()
            if (polished) turn.narrative = polished
          }
          else if (name === 'npc_initiative') {
            hooks.onNpcInitiative?.(attrs.npc ?? '')
          }
        },
        onError: (msg) => {
          // v0.2.1 P0.5: backend parser.finish() (added in v0.1.9) already
          // recovers unclosed tags, so the toast for "Unclosed tag <X>" is
          // pure noise to the player. Swallow it to console; surface anything
          // else as a non-blocking warning rather than red error.
          if (/unclosed/i.test(msg)) {
            console.debug('[parser]', msg)
            return
          }
          ElMessage.warning(msg)
        },
        onDone: () => {
          turnCount.value += 1
          // GM may have forgotten </narrative> and embedded choices into the
          // streamed narrative buffer; recover them here.
          if (!turn.choices.length) {
            const leaked = extractChoices(turn.narrative)
            if (leaked.length) turn.choices = leaked
          }
          turn.narrative = cleanNarrative(turn.narrative)
          // Flush buffered say/pc_action tags (collected during streaming so
          // dialogue bubbles don't appear before narrative finishes).
          if (sayBuffer.length) {
            turn.rawContent = (turn.rawContent ?? '') + sayBuffer.join('')
          }
          sceneMood.value = detectSceneMood(turn.narrative)
          // Synthesize a rawContent that parseParts can chew on. We always
          // prepend the cleaned narrative (wrapped) so backwards-compat is
          // preserved when GM didn't emit any speaker tags at all.
          if (turn.narrative) {
            turn.rawContent =
              `<narrative>${turn.narrative}</narrative>` + (turn.rawContent ?? '')
          }
          refreshTokens()  // fire-and-forget
          hooks.onTurnDone?.()
        },
      })
    } catch (e: any) {
      ElMessage.error(e.message ?? '请求失败')
      turn.narrative += `\n\n[出错：${e.message ?? '未知错误'}]`
    } finally {
      sending.value = false
      currentTurn.value = null
    }
  }

  async function refreshTokens() {
    try {
      const msgs = await sessionsApi.messages(sessionId)
      let ti = 0, to = 0
      for (const m of msgs) {
        if (m.role === 'assistant') {
          ti += m.tokens_in
          to += m.tokens_out
        }
      }
      tokensIn.value = ti
      tokensOut.value = to
    } catch { /* ignore */ }
  }

  return {
    turns,
    currentTurn,
    turnCount,
    tokensIn,
    tokensOut,
    sending,
    sceneMood,
    sendAction,
    refreshTokens,
  }
}
