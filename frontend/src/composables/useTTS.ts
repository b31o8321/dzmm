import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useAppStore } from '@/stores/app'
import { backendOrigin } from '@/api/client'

export interface TtsVoiceMap {
  narrator: string
  pc: string
  [npcName: string]: string
}

export interface TtsSpeakerFilter {
  narratorEnabled: boolean
  pcEnabled: boolean
  npcEnabled: boolean
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
// "zh-CN-XiaoxiaoNeural" or "zh-CN-XiaoxiaoNeural|-10%|-3Hz"
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
        if (!resp.ok) {
          ElMessage.error(`Edge TTS 合成失败 (${resp.status})`)
        } else if (resp.status !== 204) {
          const buf = await resp.arrayBuffer()
          if (!_aborted) await _playAudioBytes(buf)
        }
      } else if (appStore.ttsMode === 'cosyvoice') {
        const resp = await fetch(`${backendOrigin}/tts/cosyvoice/proxy`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ text, voice: voice || appStore.ttsGmVoice || '中文女' }),
          signal: _abortCtrl.signal,
        })
        if (!resp.ok) {
          const detail = await resp.json().catch(() => null)
          const msg = detail?.detail ?? resp.statusText
          ElMessage.error(resp.status === 503 ? `CosyVoice 未启动，请在设置页点「启动」` : `CosyVoice 合成失败 (${resp.status}): ${msg}`)
        } else if (resp.status !== 204) {
          const buf = await resp.arrayBuffer()
          if (!_aborted) await _playAudioBytes(buf)
        }
      } else {
        // local: prefer direct URL if set, fall back to model config
        const directUrl = appStore.ttsDirectUrl?.trim()
        if (directUrl) {
          const resp = await fetch(`${backendOrigin}/tts/direct`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url: directUrl, text, voice: voice || appStore.ttsGmVoice || 'default' }),
            signal: _abortCtrl.signal,
          })
          if (!resp.ok) {
            ElMessage.error(`TTS 合成失败 (${resp.status})`)
          } else if (resp.status !== 204) {
            const buf = await resp.arrayBuffer()
            if (!_aborted) await _playAudioBytes(buf)
          }
        } else {
          const resp = await fetch(`${backendOrigin}/tts`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ model_config_id: appStore.ttsModelConfigId, text, voice }),
            signal: _abortCtrl.signal,
          })
          if (!resp.ok) {
            ElMessage.error(`TTS 合成失败 (${resp.status})`)
          } else if (resp.ok) {
            const buf = await resp.arrayBuffer()
            if (!_aborted) await _playAudioBytes(buf)
          }
        }
      }
    } catch { /* ignore abort / network errors */ } finally {
      _speaking.value = false
    }
  }

  async function _speakLocal(segments: Segment[], voiceMap: TtsVoiceMap): Promise<void> {
    const directUrl = appStore.ttsDirectUrl?.trim()
    for (const seg of segments) {
      if (_aborted) break
      const voice = voiceMap[seg.speaker] ?? voiceMap['narrator'] ?? 'default'
      try {
        const [endpoint, body] = directUrl
          ? [`${backendOrigin}/tts/direct`, { url: directUrl, text: seg.text, voice }]
          : [`${backendOrigin}/tts`, { model_config_id: appStore.ttsModelConfigId, text: seg.text, voice }]
        const resp = await fetch(endpoint, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
          signal: _abortCtrl?.signal,
        })
        if (!resp.ok || resp.status === 204) continue
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

  async function _speakCosyVoice(segments: Segment[], voiceMap: TtsVoiceMap): Promise<void> {
    for (const seg of segments) {
      if (_aborted) break
      const voice = voiceMap[seg.speaker] ?? voiceMap['narrator'] ?? '中文女'
      try {
        const resp = await fetch(`${backendOrigin}/tts/cosyvoice/proxy`, {
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

  async function playTurn(rawContent: string | undefined, voiceMap: TtsVoiceMap, filter?: TtsSpeakerFilter): Promise<void> {
    if (!appStore.ttsEnabled || !rawContent) return
    if (appStore.muted) return

    stop()
    _aborted = false
    _abortCtrl = new AbortController()
    _speaking.value = true

    let segments = parseSegments(rawContent)
    if (filter) {
      segments = segments.filter((seg) => {
        if (seg.speaker === 'narrator') return filter.narratorEnabled
        if (seg.speaker === 'pc') return filter.pcEnabled
        return filter.npcEnabled
      })
    }
    if (!segments.length) {
      _speaking.value = false
      return
    }

    try {
      if (appStore.ttsMode === 'edge') {
        await _speakEdge(segments, voiceMap)
      } else if (appStore.ttsMode === 'cosyvoice') {
        await _speakCosyVoice(segments, voiceMap)
      } else {
        await _speakLocal(segments, voiceMap)
      }
    } finally {
      _speaking.value = false
    }
  }

  return { playTurn, stop, speaking: _speaking, previewVoice }
}
