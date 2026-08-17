<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import QRCode from 'qrcode'

import {
  archiveWorld,
  approvePairingRequest,
  chooseTurn,
  composeWorld,
  createModelProfile,
  createWorldVersion,
  createTurn,
  exportCharacterCard,
  getDiagnostics,
  exportLorebook,
  getFogHarborTemplate,
  getMobileHandoff,
  getPurgeManifest,
  getRun,
  getWorld,
  generateAIWorldDraft,
  importSillyTavern,
  importSillyTavernPng,
  listWorlds,
  listMobileDevices,
  listModelProfiles,
  listPendingPairings,
  purgeWorld,
  rollbackTurn,
  revokeMobileDevice,
  restoreWorld,
  setApiBase,
  validateAIWorldDraft,
  type AIWorldDraft,
  type ComposedRun,
  type ImportedContent,
  type MobileDevice,
  type MobileHandoff,
  type ModelProfile,
  type PendingPairing,
  type RunSnapshot,
  type Turn,
  type PurgeManifest,
  type WorldDetail,
  type WorldSummary,
} from './api'
import { canControlLanGameplay, setLanGameplay, startHost } from './host'

type LorebookEntry = {
  id: string
  title: string
  body: string
  activation: 'always' | 'keyword'
  keywords?: string[]
  priority: number
  source?: Record<string, unknown>
}

type Theme = 'fog' | 'paper' | 'amber'

const worldName = ref('雾港')
const heroName = ref('米拉')
const experience = ref<'fog_harbor' | 'trpg'>('fog_harbor')
const harborName = ref('雾港码头')
const lighthouseName = ref('旧灯塔')
const step = ref<'compose' | 'ai-compose' | 'ai-review' | 'confirm' | 'play' | 'worlds'>('compose')
const run = ref<RunSnapshot | null>(null)
const composed = ref<ComposedRun | null>(null)
const playerInput = ref('')
const destination = ref('lighthouse')
const busy = ref(false)
const notice = ref('')
const activeRunKey = 'dzmm-next-active-run'
const importJson = ref('')
const importedContent = ref<ImportedContent | null>(null)
const createdContent = ref<{ lorebook: { entries: Array<Record<string, unknown>> }; character_cards: Array<Record<string, unknown>> } | null>(null)
const hostStatus = ref<'starting' | 'ready' | 'error'>('starting')
const hostError = ref('')
const worlds = ref<WorldSummary[]>([])
const selectedWorld = ref<WorldDetail | null>(null)
const purgeManifest = ref<PurgeManifest | null>(null)
const purgeName = ref('')
const lorebookDraft = ref<LorebookEntry[] | null>(null)
const hostReady = computed(() => hostStatus.value === 'ready')
const lanGameplayEnabled = ref(false)
const lanGameplayAvailable = canControlLanGameplay()
const pairingPanelOpen = ref(false)
const pendingPairings = ref<PendingPairing[]>([])
const mobileDevices = ref<MobileDevice[]>([])
const mobileHandoff = ref<MobileHandoff | null>(null)
const mobilePairingQr = ref('')
const themeKey = 'dzmm-next-theme'
const theme = ref<Theme>('fog')
const modelProfiles = ref<ModelProfile[]>([])
const aiModelProfileId = ref('')
const aiRuleset = ref<'story_adventure' | 'relationship_drama' | 'hybrid'>('hybrid')
const aiGenre = ref('潮汐悬疑恋爱冒险')
const aiTone = ref('温柔、危险')
const aiCoreConflict = ref('失踪的航图正在重开不该开启的潮门。')
const aiHeroPreference = ref('一位会做艰难选择的年轻领航员')
const aiCharacterPreferences = ref('学者，守夜人')
const aiDraft = ref<AIWorldDraft | null>(null)
const aiDraftDefinitionJson = ref('')
const aiDraftHeroJson = ref('')
const aiComposeRequestId = ref('')
const aiDraftNeedsValidation = ref(false)
const modelSetupOpen = ref(false)
const modelProfileDraft = ref<Omit<ModelProfile, 'id'>>({
  name: '本地 Huihui 14B',
  provider_type: 'lm_studio',
  base_url: 'http://192.168.31.169:1234/v1',
  model_name: 'huihui-ai_qwen3-14b-abliterated',
})

const locationLabel = computed(() => run.value?.presentation.locations[run.value.state.location_id] ?? harborName.value)
const activeChapter = computed(() => run.value?.state.chapter)
const activeChapterTitle = computed(() => activeChapter.value ? run.value?.presentation.chapters[activeChapter.value.id] : '')
const activeRunId = computed(() => run.value?.run_id ?? '')
const relationshipEntries = computed(() => Object.entries(run.value?.state.relationships ?? {}))
const endingLabel = computed(() => {
  const ending = run.value?.state.ending
  if (!ending) return ''
  return { good: '好结局', normal: '普通结局', bad: '坏结局', hidden: '隐藏结局' }[ending.kind]
})
function relationshipName(relationshipId: string) {
  return run.value?.presentation.relationships[relationshipId] ?? relationshipId
}

function routeName(routeId: string) {
  return run.value?.presentation.routes[routeId] ?? routeId
}

function relationshipDimensionName(dimension: string) {
  return { affection: '好感', trust: '信任' }[dimension] ?? dimension
}
const exportableCharacterCards = computed(() =>
  (createdContent.value?.character_cards ?? []).filter((card) =>
    typeof card.id === 'string' && (card.format === 'native' || (typeof card.source_payload === 'object' && card.source_payload !== null)),
  ),
)

function requestId(prefix: string) {
  return `${prefix}-${crypto.randomUUID()}`
}

function applyTheme(nextTheme: Theme) {
  theme.value = nextTheme
  document.documentElement.dataset.theme = nextTheme
  localStorage.setItem(themeKey, nextTheme)
}

function restoreTheme() {
  const storedTheme = localStorage.getItem(themeKey)
  if (storedTheme === 'fog' || storedTheme === 'paper' || storedTheme === 'amber') {
    applyTheme(storedTheme)
  } else {
    applyTheme('fog')
  }
}

async function openWorldCenter(worldId?: string) {
  busy.value = true
  notice.value = ''
  purgeManifest.value = null
  purgeName.value = ''
  lorebookDraft.value = null
  try {
    worlds.value = await listWorlds()
    const nextId = worldId ?? selectedWorld.value?.id ?? worlds.value[0]?.id
    selectedWorld.value = nextId ? await getWorld(nextId) : null
    step.value = 'worlds'
  } catch (error) {
    notice.value = error instanceof Error ? error.message : '无法读取世界中心'
  } finally {
    busy.value = false
  }
}

async function selectWorld(worldId: string) {
  busy.value = true
  notice.value = ''
  purgeManifest.value = null
  purgeName.value = ''
  lorebookDraft.value = null
  try {
    selectedWorld.value = await getWorld(worldId)
  } catch (error) {
    notice.value = error instanceof Error ? error.message : '无法读取这个世界'
  } finally {
    busy.value = false
  }
}

function startCreatingWorld() {
  notice.value = ''
  purgeManifest.value = null
  purgeName.value = ''
  lorebookDraft.value = null
  composed.value = null
  run.value = null
  step.value = 'compose'
}

async function startCreatingAIWorld() {
  notice.value = ''
  composed.value = null
  run.value = null
  aiDraft.value = null
  aiDraftDefinitionJson.value = ''
  aiDraftHeroJson.value = ''
  aiComposeRequestId.value = ''
  aiDraftNeedsValidation.value = false
  busy.value = true
  try {
    modelProfiles.value = await listModelProfiles()
    if (!aiModelProfileId.value && modelProfiles.value[0]) aiModelProfileId.value = modelProfiles.value[0].id
    step.value = 'ai-compose'
  } catch (error) {
    notice.value = error instanceof Error ? error.message : '无法读取本地模型档案'
  } finally {
    busy.value = false
  }
}

async function saveModelProfile() {
  busy.value = true
  notice.value = ''
  try {
    const profile = await createModelProfile(modelProfileDraft.value)
    modelProfiles.value = await listModelProfiles()
    aiModelProfileId.value = profile.id
    modelSetupOpen.value = false
  } catch (error) {
    notice.value = error instanceof Error ? error.message : '无法保存模型档案'
  } finally {
    busy.value = false
  }
}

function draftIssueText(draft: AIWorldDraft) {
  return draft.issues.map((issue) => `${issue.path || '草案'}：${issue.message}`).join('；')
}

async function generateDraft() {
  if (!aiModelProfileId.value) {
    notice.value = '请先选择或保存一个本地模型档案。'
    return
  }
  busy.value = true
  notice.value = ''
  try {
    const draft = await generateAIWorldDraft({
      model_profile_id: aiModelProfileId.value,
      ruleset: aiRuleset.value,
      genre: aiGenre.value,
      tone: aiTone.value,
      core_conflict: aiCoreConflict.value,
      hero_preference: aiHeroPreference.value,
      character_preferences: aiCharacterPreferences.value.split('，').flatMap((value) => value.split(',')).map((value) => value.trim()).filter(Boolean),
    })
    aiDraft.value = draft
    if (!draft.valid || !draft.world_definition || !draft.hero) {
      notice.value = `模型草案未通过校验：${draftIssueText(draft)}`
      return
    }
    aiDraftDefinitionJson.value = JSON.stringify(draft.world_definition, null, 2)
    aiDraftHeroJson.value = JSON.stringify(draft.hero, null, 2)
    aiDraftNeedsValidation.value = false
    aiComposeRequestId.value = requestId('ai-compose')
    worldName.value = String(draft.world_definition.name ?? '未命名世界')
    heroName.value = draft.hero.name
    step.value = 'ai-review'
  } catch (error) {
    notice.value = error instanceof Error ? `生成未创建世界：${error.message}` : '模型生成失败，未创建世界。'
  } finally {
    busy.value = false
  }
}

async function validateDraftEdits() {
  busy.value = true
  notice.value = ''
  try {
    const draft = await validateAIWorldDraft({
      world_definition: JSON.parse(aiDraftDefinitionJson.value) as Record<string, unknown>,
      hero: JSON.parse(aiDraftHeroJson.value) as Record<string, unknown>,
    })
    aiDraft.value = draft
    if (!draft.valid || !draft.world_definition || !draft.hero) {
      notice.value = `编辑后的草案未通过校验：${draftIssueText(draft)}`
      return
    }
    aiDraftDefinitionJson.value = JSON.stringify(draft.world_definition, null, 2)
    aiDraftHeroJson.value = JSON.stringify(draft.hero, null, 2)
    aiDraftNeedsValidation.value = false
    worldName.value = String(draft.world_definition.name ?? worldName.value)
    heroName.value = draft.hero.name
    notice.value = '草案已通过 schema v3 与叙事规则校验；仍需明确确认才会创建世界。'
  } catch (error) {
    notice.value = error instanceof Error ? `编辑内容不是有效 JSON：${error.message}` : '编辑内容不是有效 JSON。'
  } finally {
    busy.value = false
  }
}

function markDraftEditsDirty() {
  aiDraftNeedsValidation.value = true
}

function cancelDraft() {
  aiDraft.value = null
  aiDraftDefinitionJson.value = ''
  aiDraftHeroJson.value = ''
  aiComposeRequestId.value = ''
  aiDraftNeedsValidation.value = false
  notice.value = '已丢弃未确认草案；没有创建任何世界或存档。'
  step.value = 'worlds'
}

async function composeAIWorldDraft() {
  const draft = aiDraft.value
  if (
    !draft?.valid ||
    !draft.world_definition ||
    !draft.hero ||
    !aiComposeRequestId.value ||
    aiDraftNeedsValidation.value
  ) {
    notice.value = '请先验证通过草案，再确认创建。'
    return
  }
  busy.value = true
  notice.value = ''
  try {
    composed.value = await composeWorld({
      request_id: aiComposeRequestId.value,
      model_profile_id: aiModelProfileId.value,
      world_definition: draft.world_definition,
      hero: draft.hero,
    })
    worldName.value = String(draft.world_definition.name ?? worldName.value)
    heroName.value = draft.hero.name
    const locations = draft.world_definition.locations
    if (Array.isArray(locations)) {
      const harbor = locations.find((location) => location && typeof location === 'object' && (location as { id?: unknown }).id === 'harbor') as { name?: unknown } | undefined
      const lighthouse = locations.find((location) => location && typeof location === 'object' && (location as { id?: unknown }).id === 'lighthouse') as { name?: unknown } | undefined
      if (typeof harbor?.name === 'string') harborName.value = harbor.name
      if (typeof lighthouse?.name === 'string') lighthouseName.value = lighthouse.name
    }
    createdContent.value = {
      lorebook: draft.world_definition.lorebook as { entries: Array<Record<string, unknown>> },
      character_cards: draft.world_definition.character_cards as Array<Record<string, unknown>>,
    }
    step.value = 'confirm'
  } catch (error) {
    notice.value = error instanceof Error ? error.message : '无法确认创建世界'
  } finally {
    busy.value = false
  }
}

async function archiveSelectedWorld() {
  if (!selectedWorld.value) return
  busy.value = true
  notice.value = ''
  try {
    await archiveWorld(selectedWorld.value.id)
    await openWorldCenter(selectedWorld.value.id)
  } catch (error) {
    notice.value = error instanceof Error ? error.message : '无法归档世界'
  } finally {
    busy.value = false
  }
}

async function restoreSelectedWorld() {
  if (!selectedWorld.value) return
  busy.value = true
  notice.value = ''
  try {
    await restoreWorld(selectedWorld.value.id)
    await openWorldCenter(selectedWorld.value.id)
  } catch (error) {
    notice.value = error instanceof Error ? error.message : '无法恢复世界'
  } finally {
    busy.value = false
  }
}

async function openPurgeConfirmation() {
  if (!selectedWorld.value) return
  busy.value = true
  notice.value = ''
  try {
    purgeManifest.value = await getPurgeManifest(selectedWorld.value.id)
    purgeName.value = ''
  } catch (error) {
    notice.value = error instanceof Error ? error.message : '无法生成删除清单'
  } finally {
    busy.value = false
  }
}

async function permanentlyPurgeSelectedWorld() {
  if (!selectedWorld.value || !purgeManifest.value) return
  busy.value = true
  notice.value = ''
  try {
    await purgeWorld(selectedWorld.value.id, {
      confirmation_token: purgeManifest.value.confirmation_token,
      world_name: purgeName.value,
    })
    selectedWorld.value = null
    purgeManifest.value = null
    purgeName.value = ''
    await openWorldCenter()
  } catch (error) {
    notice.value = error instanceof Error ? error.message : '无法永久删除世界'
  } finally {
    busy.value = false
  }
}

function beginLorebookEdit() {
  if (!selectedWorld.value) return
  const lorebook = selectedWorld.value.definition.lorebook as { entries: LorebookEntry[] }
  lorebookDraft.value = JSON.parse(JSON.stringify(lorebook.entries)) as LorebookEntry[]
  notice.value = ''
}

function addLorebookEntry() {
  lorebookDraft.value?.push({
    id: `custom-${crypto.randomUUID().slice(0, 8)}`,
    title: '',
    body: '',
    activation: 'keyword',
    keywords: [],
    priority: 50,
  })
}

function removeLorebookEntry(index: number) {
  lorebookDraft.value?.splice(index, 1)
}

async function saveLorebookVersion() {
  if (!selectedWorld.value || !lorebookDraft.value) return
  busy.value = true
  notice.value = ''
  try {
    const definition = JSON.parse(JSON.stringify(selectedWorld.value.definition)) as Record<string, unknown>
    definition.lorebook = { entries: lorebookDraft.value }
    selectedWorld.value = await createWorldVersion(selectedWorld.value.id, {
      base_world_version_id: selectedWorld.value.latest_world_version_id,
      definition,
    })
    worlds.value = await listWorlds()
    lorebookDraft.value = null
  } catch (error) {
    notice.value = error instanceof Error ? error.message : '无法保存新的世界版本'
  } finally {
    busy.value = false
  }
}

function duplicateAssetIds(existing: Array<Record<string, unknown>>, incoming: Array<Record<string, unknown>>) {
  return incoming
    .map((item) => item.id)
    .filter((id): id is string => typeof id === 'string' && existing.some((item) => item.id === id))
}

function addImportedContent(next: ImportedContent) {
  const current = importedContent.value
  if (!current) {
    importedContent.value = next
    return
  }
  const duplicateLore = duplicateAssetIds(current.lorebook.entries, next.lorebook.entries)
  const duplicateCards = duplicateAssetIds(current.character_cards, next.character_cards)
  if (duplicateLore.length || duplicateCards.length) {
    const descriptions = [
      duplicateLore.length ? `世界书：${duplicateLore.join('、')}` : '',
      duplicateCards.length ? `角色卡：${duplicateCards.join('、')}` : '',
    ].filter(Boolean)
    throw new Error(`导入内容与已选内容 ID 冲突（${descriptions.join('；')}），请移除重复卡或条目。`)
  }
  importedContent.value = {
    suggested_hero: current.suggested_hero ?? next.suggested_hero,
    lorebook: { entries: [...current.lorebook.entries, ...next.lorebook.entries] },
    character_cards: [...current.character_cards, ...next.character_cards],
    report: {
      source_format: 'multiple_sillytavern_sources',
      supported_fields: [...new Set([...current.report.supported_fields, ...next.report.supported_fields])],
      preserved_fields: [...new Set([...current.report.preserved_fields, ...next.report.preserved_fields])],
      ignored_fields: [...new Set([...current.report.ignored_fields, ...next.report.ignored_fields])],
      warnings: [...current.report.warnings, ...next.report.warnings],
    },
  }
}

function attachImportedContent(definition: Record<string, unknown>) {
  if (!importedContent.value) return definition
  const lorebook = definition.lorebook as { entries: Array<Record<string, unknown>> }
  const characterCards = definition.character_cards as Array<Record<string, unknown>>
  const incomingLore = importedContent.value.lorebook.entries
  const incomingCards = importedContent.value.character_cards
  const duplicateLore = duplicateAssetIds(lorebook.entries, incomingLore)
  const duplicateCards = duplicateAssetIds(characterCards, incomingCards)
  const duplicateCardNames = incomingCards
    .map((card) => card.name)
    .filter((name): name is string => typeof name === 'string' && characterCards.some((card) => card.name === name))
  if (duplicateLore.length || duplicateCards.length || duplicateCardNames.length) {
    const descriptions = [
      duplicateLore.length ? `世界书：${duplicateLore.join('、')}` : '',
      duplicateCards.length ? `角色卡：${duplicateCards.join('、')}` : '',
      duplicateCardNames.length ? `与世界模板同名的角色卡：${duplicateCardNames.join('、')}` : '',
    ].filter(Boolean)
    throw new Error(`导入内容不能直接覆盖世界模板（${descriptions.join('；')}）。同名卡不会自动改写关系规则，请更换内容后再创建。`)
  }
  return {
    ...definition,
    lorebook: { ...lorebook, entries: [...lorebook.entries, ...incomingLore] },
    character_cards: [...characterCards, ...incomingCards],
  }
}

function downloadJson(filename: string, payload: Record<string, unknown>) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' }))
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  link.click()
  window.setTimeout(() => URL.revokeObjectURL(url), 0)
}

async function downloadLorebook() {
  if (!composed.value) return
  busy.value = true
  notice.value = ''
  try {
    downloadJson(`${worldName.value}-world-info.json`, await exportLorebook(composed.value.world_version_id))
  } catch (error) {
    notice.value = error instanceof Error ? error.message : '无法导出世界书'
  } finally {
    busy.value = false
  }
}

async function downloadCharacterCard(card: Record<string, unknown>) {
  if (!composed.value || typeof card.id !== 'string') return
  busy.value = true
  notice.value = ''
  try {
    downloadJson(`${card.id}.json`, await exportCharacterCard(composed.value.world_version_id, card.id))
  } catch (error) {
    notice.value = error instanceof Error ? error.message : '无法导出角色卡'
  } finally {
    busy.value = false
  }
}

async function downloadDiagnostics() {
  busy.value = true
  notice.value = ''
  try {
    downloadJson('dzmm-next-diagnostics.json', await getDiagnostics())
  } catch (error) {
    notice.value = error instanceof Error ? error.message : '无法导出诊断信息'
  } finally {
    busy.value = false
  }
}

async function createWorld() {
  busy.value = true
  notice.value = ''
  try {
    const template = experience.value === 'fog_harbor' ? await getFogHarborTemplate() : null
    const baseDefinition = template
      ? { ...template.world_definition, name: worldName.value }
      : {
          schema_version: 3,
          name: worldName.value,
          lorebook: { entries: [] },
          character_cards: [],
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
            relationships: [],
            relationship_events: [],
            routes: [],
            endings: [],
          },
        }
    const worldDefinition = attachImportedContent(baseDefinition)
    composed.value = await composeWorld({
      request_id: requestId('compose'),
      world_definition: worldDefinition,
      hero: template ? { ...template.hero, name: heroName.value } : { name: heroName.value, profile: {} },
    })
    createdContent.value = {
      lorebook: worldDefinition.lorebook as { entries: Array<Record<string, unknown>> },
      character_cards: worldDefinition.character_cards as Array<Record<string, unknown>>,
    }
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
    const parsed = await importSillyTavern(content)
    const wasEmpty = importedContent.value === null
    addImportedContent(parsed)
    if (wasEmpty && parsed.suggested_hero?.name) {
      heroName.value = parsed.suggested_hero.name
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
    const parsed = await importSillyTavernPng(encoded)
    const wasEmpty = importedContent.value === null
    addImportedContent(parsed)
    if (wasEmpty && parsed.suggested_hero?.name) {
      heroName.value = parsed.suggested_hero.name
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

async function toggleLanGameplay(event: Event) {
  const enabled = (event.target as HTMLInputElement).checked
  busy.value = true
  notice.value = ''
  try {
    const active = await setLanGameplay(enabled)
    if (active === null) throw new Error('局域网开关仅在桌面应用内可用')
    lanGameplayEnabled.value = active
  } catch (error) {
    lanGameplayEnabled.value = !enabled
    notice.value = error instanceof Error ? error.message : '无法切换局域网玩法'
  } finally {
    busy.value = false
  }
}

async function refreshMobilePairings() {
  if (!hostReady.value) return
  busy.value = true
  notice.value = ''
  try {
    const [pending, devices, handoff] = await Promise.all([listPendingPairings(), listMobileDevices(), getMobileHandoff()])
    pendingPairings.value = pending
    mobileDevices.value = devices
    mobileHandoff.value = handoff
    mobilePairingQr.value = handoff.urls.length
      ? await QRCode.toDataURL(`dzmm-next://pair?host=${encodeURIComponent(handoff.urls[0])}&host_id=${encodeURIComponent(handoff.host_id)}`, { margin: 1, width: 240 })
      : ''
  } catch (error) {
    notice.value = error instanceof Error ? error.message : '无法读取手机配对状态'
  } finally {
    busy.value = false
  }
}

async function openMobilePairings() {
  pairingPanelOpen.value = !pairingPanelOpen.value
  if (pairingPanelOpen.value) await refreshMobilePairings()
}

async function approveMobilePairing(requestId: string) {
  busy.value = true
  notice.value = ''
  try {
    await approvePairingRequest(requestId)
    notice.value = '已批准该手机；请在手机端完成配对确认。'
    const [pending, devices] = await Promise.all([listPendingPairings(), listMobileDevices()])
    pendingPairings.value = pending
    mobileDevices.value = devices
  } catch (error) {
    notice.value = error instanceof Error ? error.message : '无法批准手机配对'
  } finally {
    busy.value = false
  }
}

async function revokePairedMobile(deviceId: string) {
  busy.value = true
  notice.value = ''
  try {
    await revokeMobileDevice(deviceId)
    mobileDevices.value = await listMobileDevices()
    notice.value = '已撤销该手机的 gameplay 访问权限。'
  } catch (error) {
    notice.value = error instanceof Error ? error.message : '无法撤销手机配对'
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
    hostError.value = error instanceof Error ? error.message : '桌面 Host 无法启动'
    return
  }
  const activeRun = localStorage.getItem(activeRunKey)
  if (activeRun) {
    void recoverRun(activeRun, { silentIfMissing: true })
  } else {
    void openWorldCenter()
  }
}

onMounted(() => {
  restoreTheme()
  void bootHost()
})
</script>

<template>
  <main class="shell">
    <header class="masthead">
      <a class="brand" href="#" @click.prevent="() => void openWorldCenter()">DZMM <span>Next</span></a>
      <p>本地世界账本 · API v2</p>
      <div class="masthead-actions">
        <button class="minor-action" type="button" :disabled="busy || !hostReady" @click="downloadDiagnostics">导出诊断</button>
        <label class="theme-control">主题
          <select :value="theme" aria-label="界面主题" @change="applyTheme(($event.target as HTMLSelectElement).value as Theme)">
            <option value="fog">雾夜</option>
            <option value="paper">纸页</option>
            <option value="amber">琥珀</option>
          </select>
        </label>
        <div class="host-dot" :class="hostStatus"><i></i> 桌面 Host {{ hostStatus === 'ready' ? '已就绪' : hostStatus === 'starting' ? '启动中' : '不可用' }}</div>
      </div>
    </header>

    <section class="route-strip" aria-label="跑团路径">
      <span :class="{ active: step === 'worlds' || step === 'compose' || step === 'ai-compose' }">世界</span><b>—</b>
      <span :class="{ active: step === 'ai-review' || step === 'confirm' }">确认</span><b>—</b>
      <span :class="{ active: step === 'play' }">游玩</span>
    </section>

    <p v-if="notice" class="notice" role="alert">{{ notice }}</p>
    <p v-if="hostError" class="notice" role="alert">
      {{ hostError }} <button class="minor-action" type="button" @click="bootHost">重试 Host</button>
    </p>
    <label class="lan-control" :class="{ unavailable: !lanGameplayAvailable }">
      <input :checked="lanGameplayEnabled" type="checkbox" :disabled="busy || !hostReady || !lanGameplayAvailable" @change="toggleLanGameplay" />
      <span>局域网玩法</span><small>{{ lanGameplayEnabled ? '已开启：仅已配对手机可访问 gameplay API' : '关闭：仅本机 Host' }}</small>
    </label>
    <section v-if="lanGameplayEnabled" class="mobile-pairing" aria-label="手机配对">
      <div>
        <p class="eyebrow">Mobile gameplay</p>
        <p>手机发起请求后，在此批准；配对仅授予当前 Run 的 gameplay 权限。</p>
      </div>
      <button class="minor-action" type="button" :disabled="busy || !hostReady" @click="openMobilePairings">
        {{ pairingPanelOpen ? '收起手机配对' : '管理手机配对' }}
      </button>
      <div v-if="pairingPanelOpen" class="mobile-pairing-list">
        <section v-if="mobilePairingQr" class="mobile-pairing-qr" aria-label="手机配对二维码">
          <img :src="mobilePairingQr" alt="使用 DZMM Android App 扫描此配对二维码" />
          <p>打开 Android App 的“扫描桌面配对码”后扫码；二维码不含 token，仍需在此批准。</p>
        </section>
        <p v-else-if="mobileHandoff && !mobileHandoff.urls.length" class="empty">未找到可用的局域网地址，请检查网络后刷新。</p>
        <p v-if="!pendingPairings.length && !mobileDevices.length" class="empty">暂无手机请求。请先在手机 App 发起配对。</p>
        <article v-for="pairing in pendingPairings" :key="pairing.request_id">
          <div><b>{{ pairing.device_name }}</b><small>等待本机批准 · {{ new Date(pairing.expires_at).toLocaleTimeString() }} 前有效</small></div>
          <button type="button" :disabled="busy" @click="approveMobilePairing(pairing.request_id)">批准</button>
        </article>
        <article v-for="device in mobileDevices" :key="device.id">
          <div><b>{{ device.name }}</b><small>已配对 · {{ device.capabilities.join('、') }}</small></div>
          <button class="danger-action" type="button" :disabled="busy" @click="revokePairedMobile(device.id)">撤销</button>
        </article>
        <button class="minor-action" type="button" :disabled="busy" @click="refreshMobilePairings">刷新配对状态</button>
      </div>
    </section>

    <section v-if="step === 'worlds'" class="scene world-center">
      <div class="world-center-heading">
        <div><p class="eyebrow">World Center</p><h1>世界是唯一根，<br />版本才会前进。</h1></div>
        <div class="world-create-actions"><button class="minor-action" type="button" :disabled="busy || !hostReady" @click="startCreatingWorld">手动新建</button><button type="button" :disabled="busy || !hostReady" @click="startCreatingAIWorld">AI 创作世界</button></div>
      </div>
      <div v-if="!worlds.length" class="world-center-empty">
        <h2>还没有世界</h2><p>从一个世界书、角色卡或雾港模板开始；确认后才会生成第一局。</p>
        <div class="world-create-actions"><button class="minor-action" type="button" :disabled="busy || !hostReady" @click="startCreatingWorld">手动新建</button><button type="button" :disabled="busy || !hostReady" @click="startCreatingAIWorld">让 AI 起草世界</button></div>
      </div>
      <div v-else class="world-center-grid">
        <nav class="world-list" aria-label="世界列表">
          <button v-for="world in worlds" :key="world.id" type="button" :class="{ selected: selectedWorld?.id === world.id }" :disabled="busy" @click="selectWorld(world.id)">
            <b>{{ world.name }}</b><small>{{ world.status === 'active' ? '可游玩' : '已归档' }} · v{{ world.latest_version_number }} · {{ world.run_count }} 局</small>
          </button>
        </nav>
        <aside v-if="selectedWorld" class="world-detail" aria-label="世界详情">
          <p class="eyebrow">{{ selectedWorld.status === 'active' ? '可游玩' : '已归档' }}</p>
          <h2>{{ selectedWorld.name }}</h2>
          <p>当前版本 v{{ selectedWorld.latest_version_number }}。已有 Run 固定在各自创建时的版本，不会被新的作者编辑改写。</p>
          <dl>
            <div><dt>WorldVersion</dt><dd>{{ selectedWorld.world_version_count }}</dd></div>
            <div><dt>Run</dt><dd>{{ selectedWorld.run_count }}</dd></div>
            <div><dt>世界书</dt><dd>{{ selectedWorld.lorebook_entry_count }} 条</dd></div>
            <div><dt>角色卡</dt><dd>{{ selectedWorld.character_card_count }} 张</dd></div>
          </dl>
          <div class="world-actions">
            <button v-if="selectedWorld.status === 'active'" class="minor-action" type="button" :disabled="busy" @click="beginLorebookEdit">编辑世界书</button>
            <button v-if="selectedWorld.status === 'active'" class="minor-action" type="button" :disabled="busy" @click="archiveSelectedWorld">归档世界</button>
            <button v-else class="minor-action" type="button" :disabled="busy" @click="restoreSelectedWorld">恢复世界</button>
            <button class="danger-action" type="button" :disabled="busy" @click="openPurgeConfirmation">永久删除…</button>
          </div>
          <form v-if="lorebookDraft" class="lorebook-editor" @submit.prevent="saveLorebookVersion">
            <div class="lorebook-editor-heading">
              <div><p class="eyebrow">编辑世界书</p><p>保存会创建新的 WorldVersion；正在游玩的 Run 继续固定在旧版本。</p></div>
              <button class="minor-action" type="button" :disabled="busy" @click="addLorebookEntry">添加条目</button>
            </div>
            <p v-if="!lorebookDraft.length" class="empty">还没有条目。添加一条受控的上下文知识，或直接保存空世界书。</p>
            <article v-for="(entry, index) in lorebookDraft" :key="String(entry.id)" class="lorebook-entry-editor">
              <label>标题<input v-model.trim="entry.title" required /></label>
              <label>内容<textarea v-model="entry.body" required rows="3"></textarea></label>
              <div class="lorebook-entry-controls">
                <label>触发<select v-model="entry.activation"><option value="always">常驻</option><option value="keyword">关键词</option></select></label>
                <label>优先级<input v-model.number="entry.priority" type="number" min="0" max="100" required /></label>
                <button class="danger-action" type="button" :disabled="busy" @click="removeLorebookEntry(index)">移除</button>
              </div>
              <label v-if="entry.activation === 'keyword'">关键词（逗号分隔）<input :value="Array.isArray(entry.keywords) ? entry.keywords.join(', ') : ''" @input="entry.keywords = ($event.target as HTMLInputElement).value.split(',').map(word => word.trim()).filter(Boolean)" /></label>
            </article>
            <div class="world-actions"><button class="minor-action" type="button" :disabled="busy" @click="lorebookDraft = null">取消</button><button type="submit" :disabled="busy">保存为 v{{ selectedWorld.latest_version_number + 1 }}</button></div>
          </form>
          <form v-if="purgeManifest" class="purge-confirmation" @submit.prevent="permanentlyPurgeSelectedWorld">
            <p>将永久删除 {{ purgeManifest.tables.world_versions }} 个版本、{{ purgeManifest.tables.runs }} 局和 {{ purgeManifest.tables.turns }} 条回合。输入 <b>{{ purgeManifest.world_name }}</b> 确认。</p>
            <label>世界名称<input v-model="purgeName" required :placeholder="purgeManifest.world_name" /></label>
            <button class="danger-action" type="submit" :disabled="busy || purgeName !== purgeManifest.world_name">永久删除这个世界</button>
          </form>
        </aside>
      </div>
    </section>

    <section v-else-if="step === 'ai-compose'" class="scene compose-scene ai-compose-scene">
      <div class="scene-copy">
        <p class="eyebrow">AI World Draft</p>
        <h1>先让灵感成形，<br />再由你签字。</h1>
        <p>模型只返回未持久化的创作素材；Python 会投影为受限的 schema v3 草案。确认前，不会创建世界、Run 或任何状态。</p>
      </div>
      <form class="ledger-card" @submit.prevent="generateDraft">
        <div class="model-draft-heading"><label>本地模型档案<select v-model="aiModelProfileId" required><option value="" disabled>选择已配置模型</option><option v-for="profile in modelProfiles" :key="profile.id" :value="profile.id">{{ profile.name }} · {{ profile.model_name }}</option></select></label><button class="minor-action" type="button" :disabled="busy" @click="modelSetupOpen = !modelSetupOpen">{{ modelSetupOpen ? '收起配置' : '配置本地模型' }}</button></div>
        <fieldset v-if="modelSetupOpen" class="model-profile-editor">
          <legend>新建模型档案</legend>
          <label>名称<input v-model.trim="modelProfileDraft.name" required maxlength="120" /></label>
          <label>协议<select v-model="modelProfileDraft.provider_type"><option value="lm_studio">LM Studio / OpenAI</option><option value="openai_compat">OpenAI-compatible</option><option value="ollama">Ollama</option></select></label>
          <label>Base URL<input v-model.trim="modelProfileDraft.base_url" required /></label>
          <label>模型名<input v-model.trim="modelProfileDraft.model_name" required /></label>
          <button class="minor-action" type="button" :disabled="busy" @click="saveModelProfile">保存并选择</button>
        </fieldset>
        <fieldset class="experience-picker"><legend>要创作哪种体验？</legend><label :class="{ selected: aiRuleset === 'story_adventure' }"><input v-model="aiRuleset" type="radio" value="story_adventure" /><span><b>剧情冒险</b><small>章节、选择、路线与结局</small></span></label><label :class="{ selected: aiRuleset === 'relationship_drama' }"><input v-model="aiRuleset" type="radio" value="relationship_drama" /><span><b>关系叙事</b><small>好感、信任、角色路线与结局</small></span></label><label :class="{ selected: aiRuleset === 'hybrid' }"><input v-model="aiRuleset" type="radio" value="hybrid" /><span><b>混合世界</b><small>剧情、关系与 TRPG 能力并存</small></span></label></fieldset>
        <label>题材<input v-model.trim="aiGenre" required maxlength="240" /></label>
        <label>基调<input v-model.trim="aiTone" required maxlength="240" /></label>
        <label>核心冲突<textarea v-model.trim="aiCoreConflict" required rows="3" maxlength="600"></textarea></label>
        <label>主角偏好<textarea v-model.trim="aiHeroPreference" required rows="2" maxlength="400"></textarea></label>
        <label>角色偏好（可选，逗号分隔）<input v-model.trim="aiCharacterPreferences" maxlength="400" /></label>
        <button :disabled="busy || !hostReady || !aiModelProfileId">{{ busy ? '正在起草…' : '生成待审阅草案' }}</button>
      </form>
    </section>

    <section v-else-if="step === 'ai-review' && aiDraft" class="scene ai-review-scene">
      <div class="scene-copy"><p class="eyebrow">Review before commit</p><h1>世界仍未存在。<br />由你决定是否落笔。</h1><p>{{ aiDraft.summary }}</p><p v-if="aiDraft.repairs.length" class="repair-note">确定性格式修复：{{ aiDraft.repairs.join('；') }}</p></div>
      <form class="ledger-card ai-review-card" @submit.prevent="composeAIWorldDraft">
        <p class="draft-safe-note">模型没有创建任何 World、Run 或状态。编辑后必须重新校验；确认只会调用现有的原子 compose。</p>
        <label>WorldDefinition（schema v3）<textarea v-model="aiDraftDefinitionJson" rows="18" spellcheck="false" aria-label="可编辑的 WorldDefinition 草案" @input="markDraftEditsDirty"></textarea></label>
        <label>主角草案<textarea v-model="aiDraftHeroJson" rows="5" spellcheck="false" aria-label="可编辑的主角草案" @input="markDraftEditsDirty"></textarea></label>
        <ul v-if="aiDraft.issues.length" class="draft-issues"><li v-for="issue in aiDraft.issues" :key="`${issue.path}-${issue.message}`">{{ issue.path }}：{{ issue.message }}</li></ul>
        <div class="world-actions"><button class="minor-action" type="button" :disabled="busy" @click="validateDraftEdits">验证编辑</button><button class="minor-action" type="button" :disabled="busy" @click="cancelDraft">取消并丢弃</button><button type="submit" :disabled="busy || !aiDraft.valid || aiDraftNeedsValidation">确认并创建世界</button></div>
      </form>
    </section>

    <section v-else-if="step === 'compose'" class="scene compose-scene">
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
        <details class="import-panel">
          <summary>导入 SillyTavern 内容（可选）</summary>
          <p>支持 V3 角色卡 JSON/PNG 与 World Info JSON。无论选择哪种玩法，它们都会作为世界书和角色卡资产固定在新 WorldVersion 中。</p>
          <textarea v-model="importJson" placeholder="粘贴 SillyTavern JSON…" rows="5"></textarea>
          <div class="import-actions">
            <button type="button" class="minor-action" @click="applySillyTavernImport">解析 JSON 并应用</button>
            <label class="file-import">导入角色卡 PNG<input type="file" accept="image/png,.png" @change="applySillyTavernPng" /></label>
          </div>
          <p v-if="importedContent" class="import-result">
            已导入 {{ importedContent.lorebook.entries.length }} 条世界书条目、{{ importedContent.character_cards.length }} 张角色卡 · {{ importedContent.report.source_format }}
          </p>
        </details>
        <button :disabled="busy || !hostReady">{{ busy ? '正在装订世界…' : hostReady ? '确认并创建世界' : '等待桌面 Host…' }}</button>
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
      <section v-if="createdContent" class="content-assets" aria-label="世界内容资产">
        <p class="eyebrow">内容资产</p>
        <div>
          <span>世界书 / World Info</span>
          <small>{{ createdContent.lorebook.entries.length }} 条条目</small>
          <button class="minor-action" type="button" :disabled="busy" @click="downloadLorebook">导出世界书</button>
        </div>
        <div>
          <span>角色卡 / Character Card</span>
          <small v-if="createdContent.character_cards.length" class="card-list">
            <span v-for="card in createdContent.character_cards" :key="String(card.id)">{{ card.name }} · {{ card.format === 'sillytavern_v3' ? 'SillyTavern V3' : '原生' }}</span>
          </small>
          <small v-else>无</small>
          <button v-for="card in exportableCharacterCards" :key="String(card.id)" class="minor-action" type="button" :disabled="busy" @click="downloadCharacterCard(card)">导出 {{ card.name }} 角色卡</button>
        </div>
      </section>
      <button :disabled="busy || !hostReady" @click="enterRun">进入第一回合</button>
    </section>

    <section v-else-if="run" class="scene play-scene">
      <aside class="run-state">
        <p class="eyebrow">{{ activeChapter ? '当前章节' : '当前坐标' }}</p>
        <p v-if="activeChapter" class="chapter-mark">{{ activeChapter.id.toUpperCase() }}</p>
        <h2 v-if="activeChapter">{{ activeChapterTitle }}</h2>
        <h2>{{ locationLabel }}</h2>
        <dl>
          <div><dt>角色</dt><dd>{{ run.state.hero.name }}</dd></div>
          <div><dt>状态版本</dt><dd>{{ run.state.revision }}</dd></div>
          <div v-if="run.state.route"><dt>路线</dt><dd>{{ routeName(run.state.route.id) }}</dd></div>
          <div><dt>物品</dt><dd>{{ run.state.inventory.length ? run.state.inventory.map(i => `${i.id} ×${i.quantity}`).join('，') : '无' }}</dd></div>
        </dl>
        <section v-if="relationshipEntries.length" class="relationship-ledger" aria-label="关系状态">
          <p class="eyebrow">关系账本</p>
          <article v-for="[characterId, relationship] in relationshipEntries" :key="characterId">
            <b>{{ relationshipName(characterId) }}</b>
            <span v-for="[dimension, value] in Object.entries(relationship.dimensions)" :key="dimension">{{ relationshipDimensionName(dimension) }} {{ value }}</span>
            <small v-for="event in Object.values(relationship.applied_events)" :key="event.reason_key">{{ event.reason_key }}</small>
          </article>
        </section>
      </aside>
      <div class="chronicle" aria-live="polite">
        <section v-if="run.state.ending" class="ending-card" :class="run.state.ending.kind">
          <p class="eyebrow">{{ endingLabel }}</p>
          <h2>{{ run.state.ending.narrative_key }}</h2>
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
      <section v-if="lanGameplayEnabled && activeRunId" class="mobile-run-handoff" aria-label="手机继续此局">
        <p class="eyebrow">手机继续此局</p>
        <p>配对后在 Android App 输入这个 Run ID。手机只能提交当前可选行动，不能修改世界或规则。</p>
        <code>{{ activeRunId }}</code>
      </section>
    </section>
  </main>
</template>
