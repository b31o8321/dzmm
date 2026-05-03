import { ref } from 'vue'
import { useAppStore } from '@/stores/app'
import { backendOrigin } from '@/api/client'

export interface TtsVoiceMap {
  narrator: string
  pc: string
  [npcName: string]: string
}

interface Segment {
  speaker: string
  text: string
}

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

// Voice strings for edge mode can optionally encode rate+pitch:
// "zh-CN-XiaomoNeural" or "zh-CN-XiaomoNeural|-10%|-3Hz"
function parseEdgeVoice(v: string): { voice: string; rate: string; pitch: string } {
  const parts = v.split('|')
  return { voice: parts[0], rate: parts[1] ?? '+0%', pitch: parts[2] ?? '+0Hz' }
}

let _audioCtx: AudioContext | null = null
function getAudioCtx(): AudioContext {
  if (!_audioCtx || _audioCtx.state === 'closed') _audioCtx = new AudioContext()
  return _audioCtx
}

const _speaking = ref(false)
let _aborted = false
let _abortCtrl: AbortController | null = null
let _activeSource: AudioBufferSourceNode | null = null

async function _getVoices(): Promise<SpeechSynthesisVoice[]> {
  if (typeof window === 'undefined' || !window.speechSynthesis) return []
  const voices = window.speechSynthesis.getVoices()
  if (voices.length) return voices
  return new Promise((resolve) => {
    window.speechSynthesis.addEventListener('voiceschanged', () => resolve(window.speechSynthesis.getVoices()), { once: true })
  })
}

async function _playAudioBytes(audioData: ArrayBuffer): Promise<void> {
  const ctx = getAudioCtx()
  if (ctx.state === 'suspended') await ctx.resume()
  const decoded = await ctx.decodeAudioData(audioData)
  const source = ctx.createBufferSource()
  source.buffer = decoded
  source.connect(ctx.destination)
  _activeSource = source
  await new Promise<void>((resolve) => {
    source.onended = () => resolve()
    source.start()
  })
  _activeSource = null
}

export function useTTS() {
  const appStore = useAppStore()

  function stop() {
    _aborted = true
    _abortCtrl?.abort()
    _activeSource?.stop()
    _activeSource = null
    _speaking.value = false
    if (typeof window !== 'undefined' && window.speechSynthesis) window.speechSynthesis.cancel()
  }

  async function previewVoice(text: string, voice: string): Promise<void> {
    if (!text.trim()) return
    stop()
    _aborted = false
    _abortCtrl = new AbortController()
    _speaking.value = true
    try {
      if (appStore.ttsMode === 'edge') {
        const { voice: v, rate, pitch } = parseEdgeVoice(voice || appStore.ttsGmVoice || 'zh-CN-XiaoxiaoNeural')
        const resp = await fetch(`${backendOrigin}/tts/builtin`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ text, voice: v, rate, pitch }),
          signal: _abortCtrl.signal,
        })
        if (resp.ok && resp.status !== 204) {
          const buf = await resp.arrayBuffer()
          if (!_aborted) await _playAudioBytes(buf)
        }
      } else if (appStore.ttsMode === 'kokoro') {
        const resp = await fetch(`${backendOrigin}/tts/kokoro/synthesize`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ text, voice: voice || appStore.ttsGmVoice || 'zf_xiaobei' }),
          signal: _abortCtrl.signal,
        })
        if (resp.ok && resp.status !== 204) {
          const buf = await resp.arrayBuffer()
          if (!_aborted) await _playAudioBytes(buf)
        }
      } else if (appStore.ttsMode === 'webspeech') {
        if (typeof window !== 'undefined' && window.speechSynthesis) {
          const voices = await _getVoices()
          if (_aborted) return
          const utterance = new SpeechSynthesisUtterance(text)
          const found = voices.find((v) => v.name === voice || v.voiceURI === voice) ?? null
          if (found) utterance.voice = found
          utterance.lang = found?.lang ?? 'zh-CN'
          await new Promise<void>((resolve) => {
            utterance.onend = () => resolve()
            utterance.onerror = () => resolve()
            window.speechSynthesis.speak(utterance)
          })
        }
      } else {
        // local proxy mode
        const resp = await fetch(`${backendOrigin}/tts`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ model_config_id: appStore.ttsModelConfigId, text, voice }),
          signal: _abortCtrl.signal,
        })
        if (resp.ok) {
          const buf = await resp.arrayBuffer()
          if (!_aborted) await _playAudioBytes(buf)
        }
      }
    } catch { /* ignore abort / network errors */ } finally {
      _speaking.value = false
    }
  }

  async function _speakWebSpeech(segments: Segment[], voiceMap: TtsVoiceMap): Promise<void> {
    if (typeof window === 'undefined' || !window.speechSynthesis) return
    const voices = await _getVoices()
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
    for (const seg of segments) {
      if (_aborted) break
      const voice = voiceMap[seg.speaker] ?? voiceMap['narrator'] ?? 'default'
      try {
        const resp = await fetch(`${backendOrigin}/tts`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ model_config_id: appStore.ttsModelConfigId, text: seg.text, voice }),
          signal: _abortCtrl?.signal,
        })
        if (!resp.ok) continue
        const buf = await resp.arrayBuffer()
        if (_aborted) break
        await _playAudioBytes(buf)
      } catch { /* skip segment */ }
    }
  }

  async function _speakEdge(segments: Segment[], voiceMap: TtsVoiceMap): Promise<void> {
    for (const seg of segments) {
      if (_aborted) break
      const rawVoice = voiceMap[seg.speaker] ?? voiceMap['narrator'] ?? 'zh-CN-XiaoxiaoNeural'
      const { voice, rate, pitch } = parseEdgeVoice(rawVoice)
      try {
        const resp = await fetch(`${backendOrigin}/tts/builtin`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ text: seg.text, voice, rate, pitch }),
          signal: _abortCtrl?.signal,
        })
        if (!resp.ok || resp.status === 204) continue
        const buf = await resp.arrayBuffer()
        if (_aborted) break
        await _playAudioBytes(buf)
      } catch { /* skip segment */ }
    }
  }

  async function _speakKokoro(segments: Segment[], voiceMap: TtsVoiceMap): Promise<void> {
    for (const seg of segments) {
      if (_aborted) break
      const voice = voiceMap[seg.speaker] ?? voiceMap['narrator'] ?? 'zf_xiaobei'
      try {
        const resp = await fetch(`${backendOrigin}/tts/kokoro/synthesize`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ text: seg.text, voice }),
          signal: _abortCtrl?.signal,
        })
        if (!resp.ok || resp.status === 204) continue
        const buf = await resp.arrayBuffer()
        if (_aborted) break
        await _playAudioBytes(buf)
      } catch { /* skip segment */ }
    }
  }

  async function playTurn(rawContent: string | undefined, voiceMap: TtsVoiceMap): Promise<void> {
    if (!appStore.ttsEnabled || !rawContent) return
    if (appStore.muted) return

    stop()
    _aborted = false
    _abortCtrl = new AbortController()
    _speaking.value = true

    const segments = parseSegments(rawContent)
    if (!segments.length) {
      _speaking.value = false
      return
    }

    try {
      if (appStore.ttsMode === 'webspeech') {
        await _speakWebSpeech(segments, voiceMap)
      } else if (appStore.ttsMode === 'edge') {
        await _speakEdge(segments, voiceMap)
      } else if (appStore.ttsMode === 'kokoro') {
        await _speakKokoro(segments, voiceMap)
      } else {
        await _speakLocal(segments, voiceMap)
      }
    } finally {
      _speaking.value = false
    }
  }

  return { playTurn, stop, speaking: _speaking, previewVoice }
}
