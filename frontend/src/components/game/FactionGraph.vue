<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'
import { factionsApi, type Faction } from '@/api/factions'

const props = defineProps<{ sessionId: number; visible: boolean }>()
const factions = ref<Faction[]>([])
const loading = ref(false)

async function load() {
  loading.value = true
  try {
    factions.value = await factionsApi.list(props.sessionId)
  } finally {
    loading.value = false
  }
}

watch(() => props.visible, (v) => { if (v) load() })
onMounted(() => { if (props.visible) load() })
</script>

<template>
  <div class="space-y-2 max-h-96 overflow-auto">
    <div v-if="loading" class="text-slate-500 text-sm">加载中…</div>
    <div v-else-if="!factions.length" class="text-slate-400 text-sm italic">
      暂无势力出现
    </div>
    <template v-else>
      <div
        v-for="f in factions" :key="f.id"
        class="border rounded p-2 text-sm"
        :class="
          f.pc_reputation >= 30 ? 'bg-green-50 border-green-200' :
          f.pc_reputation <= -30 ? 'bg-red-50 border-red-200' :
          'bg-slate-50 border-slate-200'
        "
      >
        <div class="flex items-center justify-between font-bold">
          <span>{{ f.name }}</span>
          <span class="text-xs">
            口碑 {{ f.pc_reputation > 0 ? '+' : '' }}{{ f.pc_reputation }}
          </span>
        </div>
        <div v-if="f.ideology" class="text-slate-600 text-xs italic mt-0.5">
          {{ f.ideology }}
        </div>
        <div v-if="f.description" class="text-slate-500 text-xs mt-1 leading-snug">
          {{ f.description }}
        </div>
        <div v-if="f.hostile_to.length" class="text-xs text-red-600 mt-1">
          ⚔ 敌对：{{ f.hostile_to.join('、') }}
        </div>
        <div v-if="f.allied_to.length" class="text-xs text-green-600">
          🤝 盟友：{{ f.allied_to.join('、') }}
        </div>
      </div>
    </template>
  </div>
</template>
