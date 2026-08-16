<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import {
  composeWorld,
  createTurn,
  getRun,
  rollbackTurn,
  type ComposedRun,
  type RunSnapshot,
  type Turn,
} from './api'

const worldName = ref('雾港')
const heroName = ref('米拉')
const harborName = ref('雾港码头')
const lighthouseName = ref('旧灯塔')
const step = ref<'compose' | 'confirm' | 'play'>('compose')
const run = ref<RunSnapshot | null>(null)
const composed = ref<ComposedRun | null>(null)
const playerInput = ref('')
const destination = ref('lighthouse')
const busy = ref(false)
const notice = ref('')
const activeRunKey = 'dzmm-next-active-run'

const locationLabel = computed(() =>
  run.value?.state.location_id === 'lighthouse' ? lighthouseName.value : harborName.value,
)

function requestId(prefix: string) {
  return `${prefix}-${crypto.randomUUID()}`
}

async function createWorld() {
  busy.value = true
  notice.value = ''
  try {
    composed.value = await composeWorld({
      request_id: requestId('compose'),
      world_definition: {
        schema_version: 1,
        name: worldName.value,
        lore: [],
        locations: [
          { id: 'harbor', name: harborName.value },
          { id: 'lighthouse', name: lighthouseName.value },
        ],
        factions: [],
        npcs: [],
        events: [],
        ruleset: { id: 'core' },
      },
      hero: { name: heroName.value, profile: {} },
    })
    step.value = 'confirm'
  } catch (error) {
    notice.value = error instanceof Error ? error.message : '无法创建世界'
  } finally {
    busy.value = false
  }
}

async function enterRun() {
  if (!composed.value) return
  localStorage.setItem(activeRunKey, composed.value.run_id)
  await recoverRun(composed.value.run_id)
}

async function recoverRun(runId: string) {
  busy.value = true
  notice.value = ''
  try {
    run.value = await getRun(runId)
    step.value = 'play'
  } catch (error) {
    localStorage.removeItem(activeRunKey)
    notice.value = error instanceof Error ? error.message : '无法恢复上次跑团'
  } finally {
    busy.value = false
  }
}

async function sendTurn() {
  if (!run.value || !playerInput.value.trim()) return
  busy.value = true
  notice.value = ''
  try {
    await createTurn(run.value.run_id, {
      request_id: requestId('turn'),
      expected_revision: run.value.state.revision,
      player_input: playerInput.value,
      commands: [
        { type: 'move', payload: { location_id: destination.value } },
        { type: 'narrate', payload: {} },
      ],
    })
    playerInput.value = ''
    await recoverRun(run.value.run_id)
  } catch (error) {
    notice.value = error instanceof Error ? error.message : '回合没有完成'
  } finally {
    busy.value = false
  }
}

async function rollback(turn: Turn) {
  if (!run.value || turn.kind !== 'turn') return
  busy.value = true
  notice.value = ''
  try {
    await rollbackTurn(run.value.run_id, {
      request_id: requestId('rollback'),
      expected_revision: run.value.state.revision,
      target_turn_id: turn.id,
    })
    await recoverRun(run.value.run_id)
  } catch (error) {
    notice.value = error instanceof Error ? error.message : '无法恢复该回合'
  } finally {
    busy.value = false
  }
}

onMounted(() => {
  const activeRun = localStorage.getItem(activeRunKey)
  if (activeRun) void recoverRun(activeRun)
})
</script>

<template>
  <main class="shell">
    <header class="masthead">
      <a class="brand" href="#" @click.prevent="step = 'compose'">DZMM <span>Next</span></a>
      <p>本地世界账本 · API v2</p>
      <div class="host-dot"><i></i> Mac Host</div>
    </header>

    <section class="route-strip" aria-label="跑团路径">
      <span :class="{ active: step === 'compose' }">世界</span><b>—</b>
      <span :class="{ active: step === 'confirm' }">确认</span><b>—</b>
      <span :class="{ active: step === 'play' }">跑团</span>
    </section>

    <p v-if="notice" class="notice" role="alert">{{ notice }}</p>

    <section v-if="step === 'compose'" class="scene compose-scene">
      <div class="scene-copy">
        <p class="eyebrow">新建世界</p>
        <h1>先钉住地平线，<br />再迈出第一步。</h1>
        <p>确认一次，世界、版本、角色和第一局会一起生成。中途失败不会留下半成品。</p>
      </div>
      <form class="ledger-card" @submit.prevent="createWorld">
        <label>世界名称<input v-model.trim="worldName" required maxlength="120" /></label>
        <label>主角名称<input v-model.trim="heroName" required maxlength="120" /></label>
        <div class="location-pair">
          <label>起点<input v-model.trim="harborName" required /></label>
          <label>远点<input v-model.trim="lighthouseName" required /></label>
        </div>
        <button :disabled="busy">{{ busy ? '正在装订世界…' : '确认并创建世界' }}</button>
      </form>
    </section>

    <section v-else-if="step === 'confirm' && composed" class="scene confirmation">
      <p class="eyebrow">世界已装订</p>
      <h1>{{ worldName }}</h1>
      <p>版本 1 已固定。{{ heroName }} 从 {{ harborName }} 出发；之后的状态只属于这一次 Run。</p>
      <dl>
        <div><dt>World version</dt><dd>{{ composed.world_version_id.slice(0, 8) }}</dd></div>
        <div><dt>Run</dt><dd>{{ composed.run_id.slice(0, 8) }}</dd></div>
      </dl>
      <button :disabled="busy" @click="enterRun">进入第一回合</button>
    </section>

    <section v-else-if="run" class="scene play-scene">
      <aside class="run-state">
        <p class="eyebrow">当前坐标</p>
        <h2>{{ locationLabel }}</h2>
        <dl>
          <div><dt>角色</dt><dd>{{ run.state.hero.name }}</dd></div>
          <div><dt>状态版本</dt><dd>{{ run.state.revision }}</dd></div>
          <div><dt>物品</dt><dd>{{ run.state.inventory.length ? run.state.inventory.map(i => `${i.id} ×${i.quantity}`).join('，') : '无' }}</dd></div>
        </dl>
      </aside>
      <div class="chronicle" aria-live="polite">
        <p class="eyebrow">回合记录</p>
        <article v-for="turn in run.turns" :key="turn.id">
          <small>回合 {{ turn.sequence }} · 状态 {{ turn.before_revision }} → {{ turn.after_revision }}</small>
          <p class="player">{{ turn.player_input }}</p>
          <p>{{ turn.narrative }}</p>
          <button v-if="turn.kind === 'turn'" class="rollback" :disabled="busy" @click="rollback(turn)">恢复到此回合后</button>
          <p v-else class="rollback-note">已恢复至回合 {{ turn.rollback_target_id?.slice(0, 8) }}</p>
        </article>
        <p v-if="!run.turns" class="empty">世界已准备好。写下第一步，Python 会先验证它，再让叙事继续。</p>
      </div>
      <form class="turn-form" @submit.prevent="sendTurn">
        <label>行动<input v-model="playerInput" placeholder="我检查码头的灯火…" required maxlength="4000" /></label>
        <label>目的地<select v-model="destination"><option value="harbor">{{ harborName }}</option><option value="lighthouse">{{ lighthouseName }}</option></select></label>
        <button :disabled="busy || !playerInput.trim()">{{ busy ? '正在结算回合…' : '执行回合' }}</button>
      </form>
    </section>
  </main>
</template>
