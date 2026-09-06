<script setup lang="ts">
import type { ModelProfile, WorldDetail } from '../local_host_port'

defineProps<{
  world: WorldDetail
  modelProfiles: ModelProfile[]
  busy: boolean
}>()

const open = defineModel<boolean>('open', { required: true })
const heroName = defineModel<string>('heroName', { required: true })
const modelProfileId = defineModel<string>('modelProfileId', { required: true })

const emit = defineEmits<{
  continue: [runId: string]
  start: []
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
  <p class="eyebrow">{{ world.status === 'active' ? '可游玩' : '已归档' }}</p>
  <h2>{{ world.name }}</h2>
  <p>当前内容版本 v{{ world.latest_version_number }}。已有旅程保留创建时的世界内容，新的编辑不会改写它们。</p>
  <div class="world-primary-actions">
    <button v-if="world.latest_run_id" class="minor-action" type="button" :disabled="busy || world.status !== 'active'" @click="emit('continue', world.latest_run_id)">{{ world.status === 'active' ? '继续最近旅程' : '世界已归档' }}</button>
    <button v-if="world.status === 'active'" type="button" :disabled="busy" @click="open = !open">{{ open ? '收起' : '开始新旅程' }}</button>
  </div>
  <form v-if="open && world.status === 'active'" class="new-run-form" @submit.prevent="emit('start')">
    <p class="eyebrow">新的独立旅程</p>
    <label>主角名称<input v-model.trim="heroName" name="hero-name" autocomplete="off" required maxlength="120" /></label>
    <label>叙事模型<select v-model="modelProfileId" name="model-profile"><option value="">暂不使用模型</option><option v-for="profile in modelProfiles" :key="profile.id" :value="profile.id">{{ displayModelName(profile.name) }} · {{ profile.model_name }}</option></select></label>
    <p>使用当前世界内容创建全新存档，不会覆盖已有旅程。</p>
    <button type="submit" :disabled="busy || !heroName.trim()">{{ busy ? '正在准备开场…' : '进入开场' }}</button>
  </form>
  <section v-if="world.runs.length" class="world-run-list" aria-label="已有旅程">
    <p class="eyebrow">已有旅程</p>
    <button v-for="existingRun in world.runs" :key="existingRun.id" type="button" class="minor-action" :disabled="busy || world.status !== 'active'" @click="emit('continue', existingRun.id)"><b>{{ existingRun.hero_name }}</b><small>{{ existingRun.status === 'completed' ? '旅程已完成' : '旅程进行中' }}</small><span>{{ world.status === 'active' ? '继续' : '世界已归档' }}</span></button>
  </section>
</template>
