<script setup lang="ts">
import { onMounted, onUnmounted } from 'vue'
import { ElMessage } from 'element-plus'
import BootGate from '@/components/BootGate.vue'
import { useDebugStore } from '@/stores/debug'

const debug = useDebugStore()

function onKey(e: KeyboardEvent) {
  // Don't capture while the user is typing in an input — Arrow keys move
  // the caret in textareas etc.
  const t = e.target as HTMLElement | null
  if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) {
    return
  }
  if (!e.key.startsWith('Arrow')) return
  const triggered = debug.feedKey(e.key)
  if (triggered) {
    ElMessage({
      type: debug.enabled ? 'success' : 'info',
      message: debug.enabled ? '🐛 调试模式已开启' : '调试模式已关闭',
      duration: 2500,
    })
  }
}

onMounted(() => window.addEventListener('keydown', onKey))
onUnmounted(() => window.removeEventListener('keydown', onKey))
</script>

<template>
  <BootGate>
    <router-view />
  </BootGate>
</template>
