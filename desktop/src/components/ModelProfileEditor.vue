<script setup lang="ts">
import type { ModelProfileInput } from '../local_host_port'
import type { ModelProfileFieldErrors } from '../composables/useModelProfiles'

const props = withDefaults(defineProps<{
  legend: string
  submitLabel: string
  namePrefix: string
  errors: ModelProfileFieldErrors
  busy: boolean
  showCancel?: boolean
  hasSavedCredential?: boolean
}>(), {
  showCancel: false,
  hasSavedCredential: false,
})

const name = defineModel<string>('name', { required: true })
const providerType = defineModel<ModelProfileInput['provider_type']>('providerType', { required: true })
const baseUrl = defineModel<string>('baseUrl', { required: true })
const modelName = defineModel<string>('modelName', { required: true })
const apiKey = defineModel<string>('apiKey', { required: true })

const emit = defineEmits<{
  save: []
  cancel: []
  providerChange: [provider: ModelProfileInput['provider_type']]
}>()

function changeProvider(event: Event) {
  const provider = (event.target as HTMLSelectElement).value as ModelProfileInput['provider_type']
  providerType.value = provider
  emit('providerChange', provider)
}
</script>

<template>
  <fieldset class="model-profile-editor">
    <legend>{{ legend }}</legend>
    <label>名称<input v-model.trim="name" :name="`${props.namePrefix}-name`" autocomplete="off" required maxlength="120" :aria-invalid="Boolean(errors.name)" /><small v-if="errors.name" class="field-error" role="alert">{{ errors.name }}</small></label>
    <label>协议<select :value="providerType" :name="`${props.namePrefix}-provider`" @change="changeProvider"><option value="lm_studio">LM Studio / OpenAI</option><option value="openai_compat">OpenAI-compatible</option><option value="ollama">Ollama</option></select></label>
    <label>Base URL<input v-model.trim="baseUrl" :name="`${props.namePrefix}-base-url`" type="url" inputmode="url" autocomplete="off" spellcheck="false" required :aria-invalid="Boolean(errors.base_url)" /><small v-if="errors.base_url" class="field-error" role="alert">{{ errors.base_url }}</small></label>
    <label>模型名<input v-model.trim="modelName" :name="`${props.namePrefix}-model-name`" autocomplete="off" spellcheck="false" required :aria-invalid="Boolean(errors.model_name)" /><small v-if="errors.model_name" class="field-error" role="alert">{{ errors.model_name }}</small></label>
    <label>API Key（可选）<input v-model.trim="apiKey" :name="`${props.namePrefix}-api-key`" type="password" autocomplete="new-password" spellcheck="false" :placeholder="hasSavedCredential ? '留空则保留已保存凭据' : '仅需要鉴权的服务填写'" /><small v-if="hasSavedCredential">凭据已保存在系统安全存储中，不会写入存档或导出包。</small></label>
    <div class="model-profile-actions"><button type="button" :disabled="busy" @click="$emit('save')">{{ submitLabel }}</button><button v-if="showCancel" class="minor-action" type="button" :disabled="busy" @click="$emit('cancel')">取消</button></div>
  </fieldset>
</template>
