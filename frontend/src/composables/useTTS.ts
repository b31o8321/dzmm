import { ref } from 'vue'
import { useAppStore } from '@/stores/app'

export interface TtsVoiceMap {
  narrator: string   // GM narration voice
  pc: string         // PC action voice
  [npcName: string]: string  // per-NPC voice
}

interface Segment {
  speaker: string  // 'narrator' | 'pc' | npc name
  text: string
}

// Segment extraction from rawContent
// rawContent format: <narrative>...</narrative><say speaker="X">...</say><pc_action>...</pc_action>
const NARRATIVE_RE = /<narrative>([\s\S]*?)<\/narrative>/g
const SAY_RE = /<say\s+speaker="([^"]+)">([\s\S]*?)<\/say>/g
const PC_ACTION_RE = /<pc_action>([\s\S]*?)<\/pc_action>/g

function parseSegments(rawContent: string): Segment[] {
  const all: { index: number; segment: Segment }[] = []

  let m: RegExpExecArray | null

  NARRATIVE_RE.lastIndex = 0
  while ((m = NARRATIVE_RE.exec(rawContent))) {
    const text = m[1].trim()
    if (text) all.push({ index: m.index, segment: { speaker: 'narrator', text } })
  }

  SAY_RE.lastIndex = 0
  while ((m = SAY_RE.exec(rawContent))) {
    const text = m[2].trim()
    if (text) all.push({ index: m.index, segment: { speaker: m[1], text } })
  }

  PC_ACTION_RE.lastIndex = 0
  while ((m = PC_ACTION_RE.exec(rawContent))) {
    const text = m[1].trim()
    if (text) all.push({ index: m.index, segment: { speaker: 'pc', text } })
  }

  all.sort((a, b) => a.index - b.index)
  return all.map((x) => x.segment)
}

// Module-level AudioContext (reused across calls to avoid recreation)
let _audioCtx: AudioContext | null = null
function getAudioCtx(): AudioContext {
  if (!_audioCtx || _audioCtx.state === 'closed') {
    _audioCtx = new AudioContext()
  }
  return _audioCtx
}

const _speaking = ref(false)
let _aborted = false

export function useTTS() {
  const appStore = useAppStore()

  function stop() {
    _aborted = true
    _speaking.value = false
    if (typeof window !== 'undefined' && window.speechSynthesis) {
      window.speechSynthesis.cancel()
    }
  }

  async function _speakWebSpeech(segments: Segment[], voiceMap: TtsVoiceMap): Promise<void> {
    if (typeof window === 'undefined' || !window.speechSynthesis) return
    const voices = window.speechSynthesis.getVoices()

    function findVoice(name: string): SpeechSynthesisVoice | null {
      if (!name) return null
      return voices.find((v) => v.name === name || v.voiceURI === name) ?? null
    }

    for (const seg of segments) {
      if (_aborted) break
      const voiceName = voiceMap[seg.speaker] ?? voiceMap['narrator'] ?? ''
      const utterance = new SpeechSynthesisUtterance(seg.text)
      const voice = findVoice(voiceName)
      if (voice) utterance.voice = voice
      utterance.lang = voice?.lang ?? 'zh-CN'

      await new Promise<void>((resolve) => {
        utterance.onend = () => resolve()
        utterance.onerror = () => resolve()
        window.speechSynthesis.speak(utterance)
      })
    }
  }

  async function _speakLocal(segments: Segment[], voiceMap: TtsVoiceMap): Promise<void> {
    const ctx = getAudioCtx()
    if (ctx.state === 'suspended') await ctx.resume()

    for (const seg of segments) {
      if (_aborted) break
      const voice = voiceMap[seg.speaker] ?? voiceMap['narrator'] ?? 'default'
      try {
        const resp = await fetch('/api/tts', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            model_config_id: appStore.ttsModelConfigId,
            text: seg.text,
            voice,
          }),
        })
        if (!resp.ok) continue
        const buf = await resp.arrayBuffer()
        if (_aborted) break
        const decoded = await ctx.decodeAudioData(buf)
        const source = ctx.createBufferSource()
        source.buffer = decoded
        source.connect(ctx.destination)
        await new Promise<void>((resolve) => {
          source.onended = () => resolve()
          source.start()
        })
      } catch {
        // skip segment on error — don't block gameplay
      }
    }
  }

  async function playTurn(rawContent: string | undefined, voiceMap: TtsVoiceMap): Promise<void> {
    if (!appStore.ttsEnabled || !rawContent) return
    if (appStore.muted) return

    stop()
    _aborted = false
    _speaking.value = true

    const segments = parseSegments(rawContent)
    if (!segments.length) {
      _speaking.value = false
      return
    }

    try {
      if (appStore.ttsMode === 'webspeech') {
        await _speakWebSpeech(segments, voiceMap)
      } else {
        await _speakLocal(segments, voiceMap)
      }
    } finally {
      _speaking.value = false
    }
  }

  return { playTurn, stop, speaking: _speaking }
}
