<script setup lang="ts">
import type { ModelProfile, ModelProbeResult } from '../local_host_port'

defineProps<{
  profiles: ModelProfile[]
  busy: boolean
  probingProfileId: string | null
  probeResults: Record<string, ModelProbeResult>
}>()

const emit = defineEmits<{
  probe: [profile: ModelProfile]
  edit: [profile: ModelProfile]
  makeDefault: [profile: ModelProfile]
  remove: [profile: ModelProfile]
}>()

function displayModelName(name: string) {
  try {
    return decodeURIComponent(name)
  } catch {
    return name
  }
}
</script>

<template>
  <div v-if="profiles.length" class="model-profile-list">
    <article v-for="profile in profiles" :key="profile.id">
      <div class="model-profile-title">
        <b>{{ displayModelName(profile.name) }}</b>
        <span v-if="profile.is_default" class="default-badge">默认</span>
      </div>
      <small>{{ profile.provider_type }} · {{ profile.model_name }}</small>
      <code>{{ profile.base_url }}</code>
      <div class="model-profile-actions">
        <button class="minor-action" type="button" :disabled="busy" @click="emit('probe', profile)">
          {{ probingProfileId === profile.id ? '测试中…' : '测试连接' }}
        </button>
        <button class="minor-action" type="button" :disabled="busy" @click="emit('edit', profile)">编辑</button>
        <button v-if="!profile.is_default" class="minor-action" type="button" :disabled="busy" @click="emit('makeDefault', profile)">设为默认</button>
        <button class="minor-action danger-text" type="button" :disabled="busy" @click="emit('remove', profile)">删除</button>
        <span v-if="probeResults[profile.id]" role="status" aria-live="polite" :class="{ failed: !probeResults[profile.id].success }">
          {{ probeResults[profile.id].success ? '可用' : '未通过' }} · {{ probeResults[profile.id].detail }}
        </span>
      </div>
    </article>
  </div>
  <p v-else class="empty">还没有模型档案。添加一个后，AI 创作时才可以选择它。</p>
</template>
