import { ref, onUnmounted } from 'vue'

interface AudioRef {
  value: HTMLAudioElement | null
}

function crossfade(target: HTMLAudioElement | null, current: AudioRef, vol: number, duration = 2000) {
  const oldEl = current.value
  if (oldEl) {
    const startVol = oldEl.volume
    const t0 = performance.now()
    const fadeOut = () => {
      const k = Math.min(1, (performance.now() - t0) / duration)
      oldEl.volume = startVol * (1 - k)
      if (k < 1) requestAnimationFrame(fadeOut)
      else {
        oldEl.pause()
        oldEl.src = ''
      }
    }
    requestAnimationFrame(fadeOut)
  }
  current.value = target
  if (target) {
    target.volume = 0
    target.loop = true
    target.play().catch(() => {})
    const t0 = performance.now()
    const fadeIn = () => {
      const k = Math.min(1, (performance.now() - t0) / duration)
      target.volume = vol * k
      if (k < 1) requestAnimationFrame(fadeIn)
    }
    requestAnimationFrame(fadeIn)
  }
}

export function useAmbientAudio() {
  const bgm = ref<HTMLAudioElement | null>(null)
  const ambient = ref<HTMLAudioElement | null>(null)
  const bgmVolume = ref(0.4)
  const ambientVolume = ref(0.3)

  function setBgm(url: string | null) {
    if (!url) {
      crossfade(null, bgm, 0)
      return
    }
    if (bgm.value && bgm.value.src.endsWith(url)) return
    crossfade(new Audio(url), bgm, bgmVolume.value)
  }

  function setAmbient(url: string | null) {
    if (!url) {
      crossfade(null, ambient, 0)
      return
    }
    if (ambient.value && ambient.value.src.endsWith(url)) return
    crossfade(new Audio(url), ambient, ambientVolume.value)
  }

  onUnmounted(() => {
    bgm.value?.pause()
    ambient.value?.pause()
  })

  return { setBgm, setAmbient, bgmVolume, ambientVolume }
}
