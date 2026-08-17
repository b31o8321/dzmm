<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import {
  chooseTurn,
  composeWorld,
  createTurn,
  getFogHarborTemplate,
  getRun,
  importSillyTavern,
  importSillyTavernPng,
  rollbackTurn,
  setApiBase,
  type ComposedRun,
  type ImportedContent,
  type RunSnapshot,
  type Turn,
} from './api'
import { startHost } from './host'

const worldName = ref('雾港')
const heroName = ref('米拉')
const experience = ref<'fog_harbor' | 'trpg'>('fog_harbor')
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
const importJson = ref('')
const importedContent = ref<ImportedContent | null>(null)
const hostStatus = ref<'starting' | 'ready' | 'error'>('starting')
const hostError = ref('')
const hostReady = computed(() => hostStatus.value === 'ready')

const locationLabel = computed(() =>
  run.value?.state.location_id === 'lighthouse' ? lighthouseName.value : harborName.value,
)
const activeChapter = computed(() => run.value?.state.chapter)
const relationshipEntries = computed(() => Object.entries(run.value?.state.relationships ?? {}))
const endingLabel = computed(() => {
  const ending = run.value?.state.ending
  if (!ending) return ''
  return { good: '好结局', normal: '普通结局', bad: '坏结局', hidden: '隐藏结局' }[ending.kind]
})

function requestId(prefix: string) {
  return `${prefix}-${crypto.randomUUID()}`
}

async function createWorld() {
  busy.value = true
  notice.value = ''
  try {
    const template = experience.value === 'fog_harbor' ? await getFogHarborTemplate() : null
    const worldDefinition = template
      ? { ...template.world_definition, name: worldName.value }
      : {
          schema_version: 2,
          name: worldName.value,
          lorebook: importedContent.value?.lorebook ?? { entries: [] },
          character_cards: importedContent.value?.character_cards ?? [],
          locations: [
            { id: 'harbor', name: harborName.value },
            { id: 'lighthouse', name: lighthouseName.value },
          ],
          factions: [],
          npcs: [],
          events: [],
          resources: [],
          ruleset: { id: 'trpg', enabled_capabilities: ['trpg', 'resources'] },
          story: {
            chapters: [],
            flags: [],
            relationship_events: [],
            routes: [],
            endings: [],
          },
        }
    composed.value = await composeWorld({
      request_id: requestId('compose'),
      world_definition: worldDefinition,
      hero: template ? { ...template.hero, name: heroName.value } : { name: heroName.value, profile: {} },
    })
    step.value = 'confirm'
  } catch (error) {
    notice.value = error instanceof Error ? error.message : '无法创建世界'
  } finally {
    busy.value = false
  }
}

async function chooseStory(choice: { id: string; label: string }) {
  if (!run.value) return
  busy.value = true
  notice.value = ''
  try {
    await chooseTurn(run.value.run_id, {
      request_id: requestId('choice'),
      expected_revision: run.value.state.revision,
      player_input: choice.label,
      choice_id: choice.id,
    })
    await recoverRun(run.value.run_id)
  } catch (error) {
    notice.value = error instanceof Error ? error.message : '这个选择没有生效'
  } finally {
    busy.value = false
  }
}

async function applySillyTavernImport() {
  notice.value = ''
  try {
    const content = JSON.parse(importJson.value) as object
    importedContent.value = await importSillyTavern(content)
    if (importedContent.value.suggested_hero?.name) {
      heroName.value = importedContent.value.suggested_hero.name
    }
  } catch (error) {
    notice.value = error instanceof Error ? error.message : '无法解析导入内容'
  }
}

async function applySillyTavernPng(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0]
  if (!file) return
  notice.value = ''
  try {
    const encoded = await readFileAsBase64(file)
    importedContent.value = await importSillyTavernPng(encoded)
    if (importedContent.value.suggested_hero?.name) {
      heroName.value = importedContent.value.suggested_hero.name
    }
  } catch (error) {
    notice.value = error instanceof Error ? error.message : '无法解析角色卡 PNG'
  }
}

function readFileAsBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onerror = () => reject(new Error('无法读取角色卡文件'))
    reader.onload = () => {
      const result = reader.result
      if (typeof result !== 'string') {
        reject(new Error('无法读取角色卡文件'))
        return
      }
      const encoded = result.split(',', 2)[1]
      if (!encoded) {
        reject(new Error('角色卡文件为空'))
        return
      }
      resolve(encoded)
    }
    reader.readAsDataURL(file)
  })
}

async function enterRun() {
  if (!composed.value) return
  localStorage.setItem(activeRunKey, composed.value.run_id)
  await recoverRun(composed.value.run_id)
}

async function recoverRun(runId: string, options: { silentIfMissing?: boolean } = {}) {
  busy.value = true
  notice.value = ''
  try {
    run.value = await getRun(runId)
    step.value = 'play'
  } catch (error) {
    localStorage.removeItem(activeRunKey)
    if (options.silentIfMissing && error instanceof Error && error.message === 'run not found') {
      return
    }
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

async function bootHost() {
  hostStatus.value = 'starting'
  hostError.value = ''
  try {
    const hostApiBase = await startHost()
    if (hostApiBase) setApiBase(hostApiBase)
    hostStatus.value = 'ready'
  } catch (error) {
    hostStatus.value = 'error'
    hostError.value = error instanceof Error ? error.message : 'Mac Host 无法启动'
    return
  }
  const activeRun = localStorage.getItem(activeRunKey)
  if (activeRun) void recoverRun(activeRun, { silentIfMissing: true })
}

onMounted(() => void bootHost())
</script>

<template>
  <main class="shell">
    <header class="masthead">
      <a class="brand" href="#" @click.prevent="step = 'compose'">DZMM <span>Next</span></a>
      <p>本地世界账本 · API v2</p>
      <div class="host-dot" :class="hostStatus"><i></i> Mac Host {{ hostStatus === 'ready' ? '已就绪' : hostStatus === 'starting' ? '启动中' : '不可用' }}</div>
    </header>

    <section class="route-strip" aria-label="跑团路径">
      <span :class="{ active: step === 'compose' }">世界</span><b>—</b>
      <span :class="{ active: step === 'confirm' }">确认</span><b>—</b>
      <span :class="{ active: step === 'play' }">游玩</span>
    </section>

    <p v-if="notice" class="notice" role="alert">{{ notice }}</p>
    <p v-if="hostError" class="notice" role="alert">
      {{ hostError }} <button class="minor-action" type="button" @click="bootHost">重试 Host</button>
    </p>

    <section v-if="step === 'compose'" class="scene compose-scene">
      <div class="scene-copy">
        <p class="eyebrow">新建世界</p>
        <h1>先钉住地平线，<br />再迈出第一步。</h1>
        <p>确认一次，世界、版本、角色和第一局会一起生成。中途失败不会留下半成品。</p>
      </div>
      <form class="ledger-card" @submit.prevent="createWorld">
        <fieldset class="experience-picker">
          <legend>这次想怎样玩？</legend>
          <label :class="{ selected: experience === 'fog_harbor' }">
            <input v-model="experience" type="radio" value="fog_harbor" />
            <span><b>雾港 · 剧情与关系</b><small>三章、两条角色路线与多结局</small></span>
          </label>
          <label :class="{ selected: experience === 'trpg' }">
            <input v-model="experience" type="radio" value="trpg" />
            <span><b>自定义 TRPG</b><small>地点、行动与 Python 裁决</small></span>
          </label>
        </fieldset>
        <label>世界名称<input v-model.trim="worldName" required maxlength="120" /></label>
        <label>主角名称<input v-model.trim="heroName" required maxlength="120" /></label>
        <div v-if="experience === 'trpg'" class="location-pair">
          <label>起点<input v-model.trim="harborName" required /></label>
          <label>远点<input v-model.trim="lighthouseName" required /></label>
        </div>
        <details v-if="experience === 'trpg'" class="import-panel">
          <summary>导入 SillyTavern 内容（可选）</summary>
          <p>支持 V3 角色卡 JSON/PNG 与 World Info JSON，作为世界书和角色卡资产保存进这个世界。</p>
          <textarea v-model="importJson" placeholder="粘贴 SillyTavern JSON…" rows="5"></textarea>
          <div class="import-actions">
            <button type="button" class="minor-action" @click="applySillyTavernImport">解析 JSON 并应用</button>
            <label class="file-import">导入角色卡 PNG<input type="file" accept="image/png,.png" @change="applySillyTavernPng" /></label>
          </div>
          <p v-if="importedContent" class="import-result">
            已导入 {{ importedContent.lorebook.entries.length }} 条世界书条目、{{ importedContent.character_cards.length }} 张角色卡 · {{ importedContent.report.source_format }}
          </p>
        </details>
        <button :disabled="busy || !hostReady">{{ busy ? '正在装订世界…' : hostReady ? '确认并创建世界' : '等待 Mac Host…' }}</button>
      </form>
    </section>

    <section v-else-if="step === 'confirm' && composed" class="scene confirmation">
      <p class="eyebrow">世界已装订</p>
      <h1>{{ worldName }}</h1>
      <p>版本 1 已固定。{{ heroName }} 从 {{ experience === 'fog_harbor' ? '雾港码头' : harborName }} 出发；之后的状态只属于这一次 Run。</p>
      <dl>
        <div><dt>World version</dt><dd>{{ composed.world_version_id.slice(0, 8) }}</dd></div>
        <div><dt>Run</dt><dd>{{ composed.run_id.slice(0, 8) }}</dd></div>
      </dl>
      <button :disabled="busy || !hostReady" @click="enterRun">进入第一回合</button>
    </section>

    <section v-else-if="run" class="scene play-scene">
      <aside class="run-state">
        <p class="eyebrow">{{ activeChapter ? '当前章节' : '当前坐标' }}</p>
        <p v-if="activeChapter" class="chapter-mark">{{ activeChapter.id.toUpperCase() }}</p>
        <h2 v-if="activeChapter">{{ activeChapter.id === 'ch1' ? '潮雾抵港' : activeChapter.id === 'ch2' ? '沉船的证词' : '潮门之夜' }}</h2>
        <h2>{{ locationLabel }}</h2>
        <dl>
          <div><dt>角色</dt><dd>{{ run.state.hero.name }}</dd></div>
          <div><dt>状态版本</dt><dd>{{ run.state.revision }}</dd></div>
          <div v-if="run.state.route"><dt>路线</dt><dd>{{ run.state.route.id === 'lan-route' ? '岚' : run.state.route.id === 'shen-route' ? '沈砚' : '中立' }}</dd></div>
          <div><dt>物品</dt><dd>{{ run.state.inventory.length ? run.state.inventory.map(i => `${i.id} ×${i.quantity}`).join('，') : '无' }}</dd></div>
        </dl>
        <section v-if="relationshipEntries.length" class="relationship-ledger" aria-label="关系状态">
          <p class="eyebrow">关系账本</p>
          <article v-for="[characterId, relationship] in relationshipEntries" :key="characterId">
            <b>{{ characterId === 'lan' ? '岚' : '沈砚' }}</b>
            <span v-for="[dimension, value] in Object.entries(relationship.dimensions)" :key="dimension">{{ dimension === 'affection' ? '好感' : '信任' }} {{ value }}</span>
            <small v-for="event in Object.values(relationship.applied_events)" :key="event.reason_key">{{ event.reason_key }}</small>
          </article>
        </section>
      </aside>
      <div class="chronicle" aria-live="polite">
        <section v-if="run.state.ending" class="ending-card" :class="run.state.ending.kind">
          <p class="eyebrow">{{ endingLabel }}</p>
          <h2>{{ run.state.ending.id === 'bell-beyond-fog' ? '雾钟越过灰潮' : run.state.ending.id === 'lan-dawn' ? '灯塔之后是破晓' : run.state.ending.id === 'shen-low-tide' ? '潮退时仍有人等你' : run.state.ending.id === 'neutral-harbor' ? '雾港没有忘记你' : '潮水带走了名字' }}</h2>
          <p>结局已由世界规则锁定。你可以回看记录，或回滚到此前的选择之后。</p>
        </section>
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
      <section v-if="run.available_choices.length" class="choice-deck" aria-label="当前可选行动">
        <p class="eyebrow">此刻可做的选择</p>
        <button v-for="choice in run.available_choices" :key="choice.id" type="button" :disabled="busy || !hostReady" @click="chooseStory(choice)">{{ choice.label }}</button>
      </section>
      <form v-else-if="!run.state.ending" class="turn-form" @submit.prevent="sendTurn">
        <label>行动<input v-model="playerInput" placeholder="我检查码头的灯火…" required maxlength="4000" /></label>
        <label>目的地<select v-model="destination"><option value="harbor">{{ harborName }}</option><option value="lighthouse">{{ lighthouseName }}</option></select></label>
        <button :disabled="busy || !hostReady || !playerInput.trim()">{{ busy ? '正在结算回合…' : '执行回合' }}</button>
      </form>
    </section>
  </main>
</template>
