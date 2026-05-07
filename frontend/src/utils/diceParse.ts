import type { DiceCategory, DiceOutcome, DiceEvent, DiceReaction } from '@/api/types'

const SCENE_RE = /<scene>([\s\S]*?)<\/scene>/i
const REACTION_RE = /<reaction\s+([^>]*?)>([\s\S]*?)<\/reaction>/gi
const SPEAKER_ATTR_RE = /speaker="([^"]*)"/i
const MOOD_ATTR_RE = /mood="([^"]*)"/i

export function parseDiceEvent(ev: { type: string; payload: Record<string, any>; content?: string }): DiceEvent {
  const p = ev.payload || {}
  const content = ev.content || ''

  const sceneMatch = SCENE_RE.exec(content)
  const sceneText = sceneMatch ? sceneMatch[1].trim() : ''

  const reactions: DiceReaction[] = []
  REACTION_RE.lastIndex = 0
  let rm: RegExpExecArray | null
  while ((rm = REACTION_RE.exec(content)) !== null) {
    const attrs = rm[1]
    const text = rm[2].trim()
    const sp = SPEAKER_ATTR_RE.exec(attrs)
    const md = MOOD_ATTR_RE.exec(attrs)
    reactions.push({
      speaker: sp ? sp[1] : '',
      mood: md ? md[1] : '',
      text,
    })
  }

  // Legacy fallback: no <scene> or <reaction> → use plain content as description
  let description = ''
  if (!sceneText && reactions.length === 0) {
    description = content.replace(/<[^>]+>/g, '').trim()
  }

  // Numbers from payload (string → number, default 0)
  const num = (k: string) => {
    const v = p[k]
    if (v == null || v === '') return 0
    const n = parseInt(String(v).replace(/^\+/, ''), 10)
    return Number.isFinite(n) ? n : 0
  }

  return {
    category: (p.category as DiceCategory) || 'generic',
    outcome: (p.outcome as DiceOutcome) || 'success',
    dc: num('dc'),
    pc_roll: num('pc_roll'),
    modifier: num('mod') || num('modifier'),
    scene_text: sceneText,
    reactions,
    description,
  }
}
