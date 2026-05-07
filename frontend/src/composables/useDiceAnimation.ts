import { ref, onMounted } from 'vue'

interface Stage {
  rolling: boolean
  resultShown: boolean
  sceneShown: boolean
  reactionsShown: number
}

export function useDiceAnimation(numReactions: number, autoPlay = true) {
  const stage = ref<Stage>({
    rolling: false,
    resultShown: false,
    sceneShown: false,
    reactionsShown: 0,
  })
  const timers: number[] = []

  function play(onResultShown?: () => void) {
    timers.forEach((id) => clearTimeout(id))
    timers.length = 0
    stage.value = {
      rolling: true,
      resultShown: false,
      sceneShown: false,
      reactionsShown: 0,
    }
    timers.push(window.setTimeout(() => {
      stage.value.rolling = false
      stage.value.resultShown = true
      onResultShown?.()
    }, 800))
    timers.push(window.setTimeout(() => {
      stage.value.sceneShown = true
    }, 1100))
    for (let i = 0; i < numReactions; i++) {
      timers.push(window.setTimeout(() => {
        stage.value.reactionsShown = i + 1
      }, 1500 + i * 600))
    }
  }

  onMounted(() => {
    if (autoPlay) play()
  })

  return { stage, play }
}
