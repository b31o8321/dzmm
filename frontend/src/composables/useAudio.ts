import { useAppStore } from '@/stores/app'

const BGM_BY_STYLE: Record<string, string> = {
  realistic: '/bgm/silence.mp3',
  dark: '/bgm/silence.mp3',
  horror: '/bgm/silence.mp3',
  healing: '/bgm/silence.mp3',
  comedy: '/bgm/silence.mp3',
}

const SFX = {
  dice: '/sfx/silence.mp3',
  state_up: '/sfx/silence.mp3',
  state_down: '/sfx/silence.mp3',
} as const
type SfxName = keyof typeof SFX

let bgmEl: HTMLAudioElement | null = null
const sfxPool = new Map<SfxName, HTMLAudioElement>()

function ensureSfx(name: SfxName): HTMLAudioElement {
  let el = sfxPool.get(name)
  if (!el) {
    el = new Audio(SFX[name])
    el.volume = 0.4
    el.preload = 'auto'
    sfxPool.set(name, el)
  }
  return el
}

export function useAudio() {
  const appStore = useAppStore()

  function playBgm(style: string) {
    const src = BGM_BY_STYLE[style] ?? BGM_BY_STYLE.realistic
    if (bgmEl && bgmEl.src.endsWith(src)) return  // already playing this track
    stopBgm()
    bgmEl = new Audio(src)
    bgmEl.loop = true
    bgmEl.volume = appStore.muted ? 0 : 0.15
    bgmEl.play().catch(() => { /* user gesture not yet given; will retry on next interaction */ })
  }

  function stopBgm() {
    if (bgmEl) {
      bgmEl.pause()
      bgmEl.src = ''
      bgmEl = null
    }
  }

  function playSfx(name: SfxName) {
    if (appStore.muted) return
    try {
      const el = ensureSfx(name)
      el.currentTime = 0
      el.play().catch(() => { /* user gesture missing — silently skip */ })
    } catch {
      /* ignore */
    }
  }

  function setMuted(m: boolean) {
    appStore.muted = m
    try { localStorage.setItem('dzmm.muted', m ? '1' : '0') } catch { /* ignore */ }
    if (bgmEl) bgmEl.volume = m ? 0 : 0.15
  }

  return { playBgm, stopBgm, playSfx, setMuted }
}
