<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import {
  archiveWorld,
  cancelOperation,
  cloneRun,
  composeWorld,
  createRun,
  createWorldVersion,
  exportCharacterCard,
  exportRun,
  exportWorld,
  getDiagnostics,
  exportLorebook,
  getFogHarborTemplate,
  getPurgeManifest,
  getRun,
  getWorld,
  generateAIWorldDraft,
  importSillyTavern,
  importSillyTavernPng,
  importWorld,
  listWorlds,
  purgeWorld,
  rollbackTurn,
  restoreWorld,
  setApiBase,
  streamChoice,
  streamTurn,
  validateAIWorldDraft,
  type AIWorldDraft,
  type ComposedRun,
  type ImportedContent,
  type ModelProfile,
  type RunSnapshot,
  type Turn,
  type PurgeManifest,
  type WorldDetail,
  type WorldSummary,
} from './local_host_port'
import { startHost } from './host'
import OperationStatus from './components/OperationStatus.vue'
import ModelProfileEditor from './components/ModelProfileEditor.vue'
import ModelProfileList from './components/ModelProfileList.vue'
import PlayScene from './components/PlayScene.vue'
import WorldRunLauncher from './components/WorldRunLauncher.vue'
import { useModelProfiles } from './composables/useModelProfiles'
import { isOperationStageCancellable } from './composables/operationStages'
import { consumePendingRunOperation, markPendingRunOperation } from './composables/usePendingRunRecovery'
import { shouldResetRetriableAction } from './composables/useRunBoundary'
import { forgetActiveRun, readActiveRun, rememberActiveRun } from './composables/useActiveRunPersistence'
import { useOperationStatus } from './composables/useOperationStatus'
import { attachImportedContent, mergeImportedContent } from './portableContent'

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
type WorkspaceStep = 'compose' | 'ai-compose' | 'ai-review' | 'confirm' | 'play' | 'worlds' | 'settings'
type SettingsSection = 'host' | 'models' | 'appearance'
type RetriableTurn =
  | { kind: 'choice'; choice: { id: string; label: string } }
  | { kind: 'turn'; input: string; destination: string }
type DraftReview = {
  worldName: string
  heroName: string
  heroOrigin: string
  locations: string[]
  characters: Array<{ name: string; role: string; description: string }>
  lore: Array<{ title: string; body: string }>
}

const worldName = ref('雾港')
const heroName = ref('米拉')
const experience = ref<'fog_harbor' | 'trpg'>('fog_harbor')
const harborName = ref('雾港码头')
const lighthouseName = ref('旧灯塔')
const step = ref<WorkspaceStep>('compose')
const run = ref<RunSnapshot | null>(null)
const composed = ref<ComposedRun | null>(null)
const playerInput = ref('')
const destination = ref('lighthouse')
const streamingNarrative = ref('')
const busy = ref(false)
const notice = ref('')
const activeTurnRequestId = ref<string | null>(null)
const activeDraftRequestId = ref<string | null>(null)
const lastTurnAction = ref<RetriableTurn | null>(null)
const importJson = ref('')
const importedContent = ref<ImportedContent | null>(null)
const createdContent = ref<{ lorebook: { entries: Array<Record<string, unknown>> }; character_cards: Array<Record<string, unknown>> } | null>(null)
const hostStatus = ref<'starting' | 'ready' | 'error'>('starting')
const hostError = ref('')
const worlds = ref<WorldSummary[]>([])
const selectedWorld = ref<WorldDetail | null>(null)
const newRunOpen = ref(false)
const newRunHeroName = ref('旅行者')
const newRunModelProfileId = ref('')
const purgeManifest = ref<PurgeManifest | null>(null)
const purgeName = ref('')
const lorebookDraft = ref<LorebookEntry[] | null>(null)
const hostReady = computed(() => hostStatus.value === 'ready')
const themeKey = 'dzmm-theme'
const legacyThemeKey = 'dzmm-next-theme'
const theme = ref<Theme>('fog')
const {
  profiles: modelProfiles,
  probeResults: modelProbeResults,
  probingProfileId: probingModelProfileId,
  editorOpen: modelSetupOpen,
  editingProfileId: editingModelProfileId,
  draft: modelProfileDraft,
  validationErrors: modelProfileErrors,
  refresh: refreshModelProfiles,
  beginAdd: startAddingModelProfile,
  beginEdit: editModelProfile,
  selectProvider: selectModelProvider,
  save: persistModelProfile,
  makeDefault: persistDefaultModelProfile,
  remove: persistModelProfileRemoval,
  probe: probeSavedProfile,
} = useModelProfiles()
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
const aiDraftReview = ref<DraftReview | null>(null)
const aiLastValidDraft = ref<{ definition: string; hero: string } | null>(null)
const settingsSection = ref<SettingsSection>('host')
const portableFileInput = ref<HTMLInputElement | null>(null)
let activeStreamController: AbortController | null = null
const storageBoundaryNotice = '本机独立保存世界与旅程；旧版 DZMM 存档不会自动迁移或覆盖。需要带入内容时，请主动导入世界包或旅程快照。'

const draftRulePreview = computed(() => {
  const story = aiDraft.value?.world_definition?.story as { chapters?: Array<{ title?: string; choices?: Array<{ label?: string }> }>; relationships?: unknown[]; routes?: unknown[]; endings?: unknown[] } | undefined
  return {
    chapters: story?.chapters ?? [],
    relationships: story?.relationships?.length ?? 0,
    routes: story?.routes?.length ?? 0,
    endings: story?.endings?.length ?? 0,
  }
})
const exportableCharacterCards = computed(() =>
  (createdContent.value?.character_cards ?? []).filter((card) =>
    typeof card.id === 'string' && (card.format === 'native' || (typeof card.source_payload === 'object' && card.source_payload !== null)),
  ),
)

function requestId(prefix: string) {
  return `${prefix}-${crypto.randomUUID()}`
}

function abortActiveStream() {
  activeStreamController?.abort()
  activeStreamController = null
}

function beginStream() {
  abortActiveStream()
  activeStreamController = new AbortController()
  return activeStreamController
}

function syncDestination(snapshot: RunSnapshot) {
  const locations = snapshot.presentation.locations
  const current = snapshot.state.location_id
  if (destination.value in locations) return
  destination.value = current in locations ? current : Object.keys(locations)[0] ?? 'lighthouse'
}

const { visibleOperation, begin: beginOperation, advance: advanceOperation, end: endOperation } = useOperationStatus()

async function cancelActiveTurn() {
  const requestId = activeTurnRequestId.value ?? activeDraftRequestId.value
  if (!requestId) return
  const cancellingDraft = activeDraftRequestId.value === requestId
  let result: Awaited<ReturnType<typeof cancelOperation>>
  try {
    result = await cancelOperation(requestId)
  } catch (error) {
    if (!cancellingDraft) {
      notice.value = error instanceof Error ? `取消未送达：${error.message}。当前旅程仍在处理中。` : '取消未送达；当前旅程仍在处理中。'
      advanceOperation('generating', '取消请求未送达；请继续等待或重试。')
      return
    }
    abortActiveStream()
    activeDraftRequestId.value = null
    busy.value = false
    notice.value = '已停止等待本次起草；没有创建世界、旅程或存档。'
    endOperation('cancelled', '起草请求未送达，但晚到结果已被丢弃；没有创建世界或旅程。')
    return
  }
  if (!result.accepted) {
    if (cancellingDraft) {
      abortActiveStream()
      activeDraftRequestId.value = null
      busy.value = false
      notice.value = '已停止等待本次起草；没有创建世界、旅程或存档。'
      endOperation('cancelled', '起草已进入收尾；晚到结果不会创建世界或旅程。')
      return
    }
    advanceOperation(
      'applying',
      '叙事已进入状态写入阶段，当前操作不能再取消。',
    )
    return
  }
  activeTurnRequestId.value = null
  activeDraftRequestId.value = null
  abortActiveStream()
  if (!cancellingDraft) markPendingRunOperation(false)
  busy.value = false
  notice.value = cancellingDraft
    ? '已取消本次起草；没有创建世界、旅程或存档。'
    : '已取消本次行动；原旅程没有改变，可以重新选择。'
  endOperation(
    'cancelled',
    cancellingDraft ? '本次起草已取消；没有创建世界或旅程。' : '本次行动已取消；原旅程没有改变。',
  )
}

async function retryLastTurn() {
  const action = lastTurnAction.value
  if (!action || busy.value) return
  if (action.kind === 'choice') {
    await chooseStory(action.choice)
    return
  }
  playerInput.value = action.input
  destination.value = action.destination
  await sendTurn()
}

function applyTheme(nextTheme: Theme) {
  theme.value = nextTheme
  document.documentElement.dataset.theme = nextTheme
  localStorage.setItem(themeKey, nextTheme)
  localStorage.removeItem(legacyThemeKey)
}

function restoreTheme() {
  const storedTheme = localStorage.getItem(themeKey) ?? localStorage.getItem(legacyThemeKey)
  if (storedTheme === 'fog' || storedTheme === 'paper' || storedTheme === 'amber') {
    applyTheme(storedTheme)
  } else {
    applyTheme('fog')
  }
}

async function openWorldCenter(worldId?: string) {
  abortActiveStream()
  busy.value = true
  notice.value = ''
  purgeManifest.value = null
  purgeName.value = ''
  lorebookDraft.value = null
  try {
    ;[worlds.value, modelProfiles.value] = await Promise.all([listWorlds(), refreshModelProfiles()])
    const preferredModel = modelProfiles.value.find((profile) => profile.is_default)
    if (!newRunModelProfileId.value && preferredModel) {
      newRunModelProfileId.value = preferredModel.id
    }
    const nextId = worldId ?? selectedWorld.value?.id ?? worlds.value[0]?.id
    selectedWorld.value = nextId ? await getWorld(nextId) : null
    step.value = 'worlds'
  } catch (error) {
    notice.value = error instanceof Error ? error.message : '无法读取世界中心'
  } finally {
    busy.value = false
  }
}

async function openSettings(section: SettingsSection = 'host') {
  abortActiveStream()
  settingsSection.value = section
  notice.value = ''
  if (section !== 'models') {
    step.value = 'settings'
    return
  }
  busy.value = true
  try {
    await refreshModelProfiles()
    step.value = 'settings'
  } catch (error) {
    notice.value = error instanceof Error ? error.message : '无法读取本地模型档案'
  } finally {
    busy.value = false
  }
}

async function selectSettingsSection(section: SettingsSection) {
  if (section === 'models' && !modelProfiles.value.length) {
    await openSettings(section)
    return
  }
  settingsSection.value = section
}

function toggleDraftModelSetup() {
  if (modelSetupOpen.value) {
    modelSetupOpen.value = false
    return
  }
  startAddingModelProfile()
}

async function selectWorld(worldId: string) {
  abortActiveStream()
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
  abortActiveStream()
  notice.value = ''
  purgeManifest.value = null
  purgeName.value = ''
  lorebookDraft.value = null
  composed.value = null
  run.value = null
  step.value = 'compose'
}

async function startCreatingAIWorld() {
  abortActiveStream()
  notice.value = ''
  composed.value = null
  run.value = null
  aiDraft.value = null
  aiDraftDefinitionJson.value = ''
  aiDraftHeroJson.value = ''
  aiComposeRequestId.value = ''
  aiDraftNeedsValidation.value = false
  aiDraftReview.value = null
  aiLastValidDraft.value = null
  busy.value = true
  try {
    await refreshModelProfiles()
    const preferred = modelProfiles.value.find((profile) => profile.is_default) ?? modelProfiles.value[0]
    if (!aiModelProfileId.value && preferred) aiModelProfileId.value = preferred.id
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
    const profile = await persistModelProfile()
    if (profile) aiModelProfileId.value = profile.id
  } catch (error) {
    notice.value = error instanceof Error ? error.message : '无法保存模型档案'
  } finally {
    busy.value = false
  }
}

async function makeDefaultModelProfile(profile: ModelProfile) {
  busy.value = true
  notice.value = ''
  try {
    await persistDefaultModelProfile(profile)
    aiModelProfileId.value = profile.id
    newRunModelProfileId.value = profile.id
  } catch (error) {
    notice.value = error instanceof Error ? error.message : '无法设置默认模型'
  } finally {
    busy.value = false
  }
}

async function removeModelProfile(profile: ModelProfile) {
  if (!window.confirm(`删除模型档案“${profile.name}”？此操作不会删除模型文件。`)) return
  busy.value = true
  notice.value = ''
  try {
    const fallback = await persistModelProfileRemoval(profile)
    if (aiModelProfileId.value === profile.id) aiModelProfileId.value = fallback?.id ?? ''
    if (newRunModelProfileId.value === profile.id) newRunModelProfileId.value = fallback?.id ?? ''
  } catch (error) {
    notice.value = error instanceof Error ? error.message : '无法删除模型档案'
  } finally {
    busy.value = false
  }
}

async function probeSavedModelProfile(profile: ModelProfile) {
  busy.value = true
  notice.value = ''
  beginOperation('正在连接本地模型…', 'connecting')
  const draftController = beginStream()
  try {
    advanceOperation('generating', '正在等待模型返回测试结果；已耗时会持续显示。')
    const result = await probeSavedProfile(profile)
    endOperation(
      result.success ? 'completed' : 'failed',
      result.success ? '模型连接测试完成。' : '模型未通过测试；还没有开始游玩。',
    )
  } catch (error) {
    notice.value = error instanceof Error ? error.message : '无法完成模型探测'
    endOperation('failed', '模型测试失败；请检查配置后重试。')
  } finally {
    busy.value = false
  }
}

function draftIssueText(draft: AIWorldDraft) {
  return draft.issues.map((issue) => `${issue.path || '草案'}：${issue.message}`).join('；')
}

function draftIssueHelp(path: string) {
  if (path === '高级 JSON') return ['高级 JSON', '修正 JSON 语法，或恢复上一份通过本机规则校验的草案。']
  if (path === 'world_definition' || path.startsWith('schema_version')) return ['世界定义', '恢复上一份有效草案，或检查高级 JSON 的版本字段。']
  if (path.startsWith('hero.name')) return ['主角名称', '填写 1 到 120 个字符的主角名称。']
  if (path.startsWith('hero.profile')) return ['主角背景', '补充主角背景；保存前会由本机规则一起校验。']
  if (path.startsWith('name')) return ['世界名称', '填写 1 到 120 个字符的世界名称。']
  if (path.startsWith('locations')) return ['地点', '保留至少两个有名称的地点。']
  if (path.startsWith('character_cards')) return ['角色卡', '每张角色卡需要有效 ID、名称和安全映射内容。']
  if (path.startsWith('lorebook')) return ['世界书', '每条世界书内容需要标题、正文和有效触发方式。']
  if (path.startsWith('story')) return ['剧情规则', '章节、关系、路线和结局由本机规则验证；请恢复有效草案或在高级编辑中修正。']
  return [path || '草案', '检查该字段后重新验证。']
}

function parseDraftReview(definition: Record<string, any>, hero: Record<string, any>): DraftReview {
  const cards = Array.isArray(definition.character_cards) ? definition.character_cards : []
  const lore = Array.isArray(definition.lorebook?.entries) ? definition.lorebook.entries : []
  const locations = Array.isArray(definition.locations) ? definition.locations : []
  return {
    worldName: typeof definition.name === 'string' ? definition.name : '',
    heroName: typeof hero.name === 'string' ? hero.name : '',
    heroOrigin: typeof hero.profile?.origin === 'string' ? hero.profile.origin : '',
    locations: locations.slice(0, 2).map((location: Record<string, unknown>) => typeof location.name === 'string' ? location.name : ''),
    characters: cards.slice(0, 2).map((card: Record<string, any>) => ({
      name: typeof card.name === 'string' ? card.name : '',
      role: typeof card.mapped?.personality === 'string' ? card.mapped.personality : '',
      description: typeof card.mapped?.description === 'string' ? card.mapped.description : '',
    })),
    lore: lore.map((entry: Record<string, unknown>) => ({
      title: typeof entry.title === 'string' ? entry.title : '',
      body: typeof entry.body === 'string' ? entry.body : '',
    })),
  }
}

function rememberValidDraft(definition: Record<string, unknown>, hero: Record<string, unknown>) {
  const nextDefinition = JSON.stringify(definition, null, 2)
  const nextHero = JSON.stringify(hero, null, 2)
  aiDraftDefinitionJson.value = nextDefinition
  aiDraftHeroJson.value = nextHero
  aiDraftReview.value = parseDraftReview(definition, hero)
  aiLastValidDraft.value = { definition: nextDefinition, hero: nextHero }
}

function replaceDraftText(value: unknown, replacements: Array<[string, string]>): unknown {
  if (typeof value === 'string') {
    return replacements.reduce((next, [before, after]) => before && before !== after ? next.replaceAll(before, after) : next, value)
  }
  if (Array.isArray(value)) return value.map((item) => replaceDraftText(item, replacements))
  if (value && typeof value === 'object') {
    return Object.fromEntries(Object.entries(value as Record<string, unknown>).map(([key, item]) => [key, replaceDraftText(item, replacements)]))
  }
  return value
}

function syncStructuredDraftEdits() {
  const review = aiDraftReview.value
  if (!review) return
  try {
    const definition = JSON.parse(aiDraftDefinitionJson.value) as Record<string, any>
    const hero = JSON.parse(aiDraftHeroJson.value) as Record<string, any>
    const oldLocations = Array.isArray(definition.locations) ? definition.locations.slice(0, 2).map((item: Record<string, unknown>) => String(item.name ?? '')) : []
    const oldCharacters = Array.isArray(definition.character_cards) ? definition.character_cards.slice(0, 2).map((item: Record<string, unknown>) => String(item.name ?? '')) : []
    const replacements: Array<[string, string]> = [[String(definition.name ?? ''), review.worldName], ...oldLocations.map((name, index) => [name, review.locations[index] ?? ''] as [string, string]), ...oldCharacters.map((name, index) => [name, review.characters[index]?.name ?? ''] as [string, string])]
    const replaced = replaceDraftText(definition, replacements) as Record<string, any>
    replaced.name = review.worldName
    ;(replaced.locations ?? []).slice(0, 2).forEach((location: Record<string, unknown>, index: number) => { location.name = review.locations[index] ?? '' })
    ;(replaced.character_cards ?? []).slice(0, 2).forEach((card: Record<string, any>, index: number) => {
      const character = review.characters[index]
      if (!character) return
      card.name = character.name
      card.mapped = { ...(card.mapped ?? {}), personality: character.role, description: character.description }
    })
    ;(replaced.lorebook?.entries ?? []).forEach((entry: Record<string, unknown>, index: number) => {
      const lore = review.lore[index]
      if (!lore) return
      entry.title = lore.title
      entry.body = lore.body
    })
    hero.name = review.heroName
    hero.profile = { ...(hero.profile ?? {}), origin: review.heroOrigin }
    aiDraftDefinitionJson.value = JSON.stringify(replaced, null, 2)
    aiDraftHeroJson.value = JSON.stringify(hero, null, 2)
    markDraftEditsDirty()
  } catch (error) {
    notice.value = error instanceof Error ? `无法同步结构化编辑：${error.message}` : '无法同步结构化编辑。'
  }
}

function restoreLastValidDraft() {
  const snapshot = aiLastValidDraft.value
  if (!snapshot) return
  try {
    const definition = JSON.parse(snapshot.definition) as Record<string, unknown>
    const hero = JSON.parse(snapshot.hero) as { name: string; profile: Record<string, unknown> }
    aiDraftDefinitionJson.value = snapshot.definition
    aiDraftHeroJson.value = snapshot.hero
    aiDraftReview.value = parseDraftReview(definition, hero)
    aiDraft.value = {
      valid: true,
      summary: aiDraft.value?.summary ?? null,
      world_definition: definition,
      hero,
      repairs: aiDraft.value?.repairs ?? [],
      issues: [],
    }
    aiDraftNeedsValidation.value = false
    aiComposeRequestId.value = requestId('ai-compose')
    notice.value = '已恢复上一份通过本机规则校验的草案；仍由你决定是否确认创建。'
  } catch {
    notice.value = '无法恢复上一份有效草案。请重新生成。'
  }
}

async function generateDraft() {
  if (!aiModelProfileId.value) {
    notice.value = '请先选择或保存一个本地模型档案。'
    return
  }
  busy.value = true
  notice.value = ''
  const draftRequestId = requestId('ai-draft')
  activeDraftRequestId.value = draftRequestId
  beginOperation('正在连接本地模型…', 'connecting')
  const draftController = beginStream()
  try {
    advanceOperation('generating', '模型正在起草世界；已耗时会持续显示。')
    const draft = await generateAIWorldDraft({
      model_profile_id: aiModelProfileId.value,
      ruleset: aiRuleset.value,
      genre: aiGenre.value,
      tone: aiTone.value,
      core_conflict: aiCoreConflict.value,
      request_id: draftRequestId,
      hero_preference: aiHeroPreference.value,
      character_preferences: aiCharacterPreferences.value.split('，').flatMap((value) => value.split(',')).map((value) => value.trim()).filter(Boolean),
    }, draftController.signal)
    if (activeDraftRequestId.value !== draftRequestId) return
    aiDraft.value = draft
    if (!draft.valid || !draft.world_definition || !draft.hero) {
      notice.value = `模型草案未通过校验：${draftIssueText(draft)}`
      endOperation('failed', '草案未通过校验；没有创建世界或旅程。')
      return
    }
    rememberValidDraft(draft.world_definition, draft.hero)
    aiDraftNeedsValidation.value = false
    aiComposeRequestId.value = requestId('ai-compose')
    worldName.value = String(draft.world_definition.name ?? '未命名世界')
    heroName.value = draft.hero.name
    step.value = 'ai-review'
    endOperation('completed', '草案已生成，等待你审阅。')
  } catch (error) {
    if (activeDraftRequestId.value !== draftRequestId) return
    notice.value = error instanceof Error ? `生成未创建世界：${error.message}` : '模型生成失败，未创建世界。'
    endOperation('failed', '生成失败；没有创建世界或旅程。')
  } finally {
    if (activeDraftRequestId.value === draftRequestId) {
      activeDraftRequestId.value = null
      busy.value = false
    }
    if (activeStreamController === draftController) activeStreamController = null
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
    rememberValidDraft(draft.world_definition, draft.hero)
    aiDraftNeedsValidation.value = false
    worldName.value = String(draft.world_definition.name ?? worldName.value)
    heroName.value = draft.hero.name
    notice.value = '草案已通过世界结构与叙事规则校验；仍需明确确认才会创建世界。'
  } catch (error) {
    aiDraft.value = {
      valid: false,
      summary: aiDraft.value?.summary ?? null,
      world_definition: null,
      hero: null,
      repairs: aiDraft.value?.repairs ?? [],
      issues: [{ path: '高级 JSON', message: error instanceof Error ? error.message : '内容不是有效 JSON' }],
    }
    aiDraftNeedsValidation.value = false
    notice.value = '高级 JSON 无法解析；可恢复上一份有效草案，或修正后重新验证。'
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
  aiDraftReview.value = null
  aiLastValidDraft.value = null
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
    newRunOpen.value = false
  } catch (error) {
    notice.value = error instanceof Error ? error.message : '无法保存新的世界版本'
  } finally {
    busy.value = false
  }
}

async function continueRun(runId: string) {
  rememberActiveRun(runId)
  await recoverRun(runId)
}

async function startNewRun() {
  if (!selectedWorld.value || !newRunHeroName.value.trim()) return
  busy.value = true
  notice.value = ''
  try {
    const result = await createRun(selectedWorld.value.id, {
      request_id: requestId('run'),
      world_version_id: selectedWorld.value.latest_world_version_id,
      hero: { name: newRunHeroName.value.trim(), profile: {} },
      model_profile_id: newRunModelProfileId.value || null,
    })
    composed.value = result
    rememberActiveRun(result.run_id)
    await recoverRun(result.run_id)
  } catch (error) {
    notice.value = error instanceof Error ? error.message : '无法开始新的旅程'
  } finally {
    busy.value = false
  }
}

async function beginNewRunFromCurrentWorld() {
  const worldId = run.value?.world_id
  if (!worldId) return
  await openWorldCenter(worldId)
  const preferred = modelProfiles.value.find((profile) => profile.is_default)
  newRunModelProfileId.value = preferred?.id ?? ''
  newRunHeroName.value = '旅行者'
  newRunOpen.value = true
}

function returnToCurrentWorld() {
  const worldId = run.value?.world_id
  if (worldId) void openWorldCenter(worldId)
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

async function downloadPortableWorld() {
  if (!selectedWorld.value) return
  busy.value = true
  notice.value = ''
  try {
    downloadJson(`${selectedWorld.value.name}-portable-world.json`, await exportWorld(selectedWorld.value.id))
    notice.value = '世界包已导出；导入另一台设备会创建独立的新世界与首次旅程。'
  } catch (error) {
    notice.value = error instanceof Error ? error.message : '无法导出世界包'
  } finally {
    busy.value = false
  }
}

async function downloadPortableRun() {
  if (!run.value) return
  busy.value = true
  notice.value = ''
  try {
    downloadJson(`run-${run.value.run_id}-portable.json`, await exportRun(run.value.run_id))
    notice.value = '旅程快照已导出；导入后会创建独立旅程，不会自动同步。'
  } catch (error) {
    notice.value = error instanceof Error ? error.message : '无法导出旅程快照'
  } finally {
    busy.value = false
  }
}

function choosePortableBundle() {
  portableFileInput.value?.click()
}

async function importPortableBundle(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  busy.value = true
  notice.value = ''
  try {
    const bundle = JSON.parse(await file.text()) as Record<string, unknown>
    if (bundle.kind === 'run') {
      const result = await cloneRun({ request_id: requestId('run-clone'), bundle })
      composed.value = result
      run.value = await getRun(result.run_id)
      rememberActiveRun(result.run_id)
      step.value = 'play'
      notice.value = '旅程已复制到本机；原设备上的旅程不受影响。'
    } else {
      const result = await importWorld({ request_id: requestId('world-import'), bundle })
      composed.value = result
      run.value = await getRun(result.run_id)
      rememberActiveRun(result.run_id)
      step.value = 'play'
      await openWorldCenter(result.world_id)
      notice.value = '世界包已导入本机；已经创建独立的新世界与首次旅程。'
    }
  } catch (error) {
    notice.value = error instanceof Error ? error.message : '无法导入便携包'
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
    const worldDefinition = attachImportedContent(baseDefinition, importedContent.value)
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
  lastTurnAction.value = { kind: 'choice', choice: { ...choice } }
  const turnRequestId = requestId('choice')
  activeTurnRequestId.value = turnRequestId
  markPendingRunOperation(true)
  streamingNarrative.value = ''
  busy.value = true
  notice.value = ''
  beginOperation('正在连接本地模型…', 'connecting')
  const streamController = beginStream()
  try {
    advanceOperation('generating', '正在生成后续故事；旅程尚未写入新回合。')
    let streamFailure: string | null = null
    await streamChoice(run.value.run_id, {
      request_id: turnRequestId,
      expected_revision: run.value.state.revision,
      player_input: choice.label,
      choice_id: choice.id,
    }, (event) => {
      if (activeTurnRequestId.value !== turnRequestId) return
      if (event.event === 'narrative_delta' && typeof event.data.text === 'string') {
        streamingNarrative.value += event.data.text
      }
      if (event.event === 'turn_failed') {
        streamFailure = typeof event.data.detail === 'string' ? event.data.detail : '回合生成失败'
      }
    }, streamController.signal)
    if (streamFailure) throw new Error(streamFailure)
    if (activeTurnRequestId.value !== turnRequestId) return
    advanceOperation('applying', '叙事已返回，本机规则正在确认并保存结果。')
    await recoverRun(run.value.run_id)
    if (activeTurnRequestId.value !== turnRequestId) return
    lastTurnAction.value = null
    streamingNarrative.value = ''
    endOperation('completed', '故事已继续，状态已保存。')
  } catch (error) {
    if (activeTurnRequestId.value !== turnRequestId) return
    notice.value = error instanceof Error ? error.message : '这个选择没有生效'
    endOperation('failed', '本次行动失败；请重试，原状态未改变。')
  } finally {
    if (activeTurnRequestId.value === turnRequestId) {
      markPendingRunOperation(false)
      activeTurnRequestId.value = null
      busy.value = false
    }
    if (activeStreamController === streamController) activeStreamController = null
  }
}

async function applySillyTavernImport() {
  notice.value = ''
  try {
    const content = JSON.parse(importJson.value) as object
    const parsed = await importSillyTavern(content)
    const wasEmpty = importedContent.value === null
    importedContent.value = mergeImportedContent(importedContent.value, parsed)
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
    importedContent.value = mergeImportedContent(importedContent.value, parsed)
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
  rememberActiveRun(composed.value.run_id)
  await recoverRun(composed.value.run_id)
}

async function recoverRun(runId: string, options: { silentIfMissing?: boolean; preserveNotice?: boolean } = {}) {
  busy.value = true
  if (!options.preserveNotice) notice.value = ''
  try {
    if (shouldResetRetriableAction(run.value?.run_id, runId)) {
      // A retry closure captures the old Run and must never cross a Run boundary.
      lastTurnAction.value = null
    }
    run.value = await getRun(runId)
    syncDestination(run.value)
    step.value = 'play'
  } catch (error) {
    forgetActiveRun()
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
  const submittedInput = playerInput.value.trim()
  lastTurnAction.value = {
    kind: 'turn',
    input: submittedInput,
    destination: destination.value,
  }
  const turnRequestId = requestId('turn')
  activeTurnRequestId.value = turnRequestId
  markPendingRunOperation(true)
  streamingNarrative.value = ''
  busy.value = true
  notice.value = ''
  beginOperation('正在连接本地模型…', 'connecting')
  const streamController = beginStream()
  try {
    advanceOperation('generating', '正在生成后续故事；旅程尚未写入新回合。')
    let streamFailure: string | null = null
    await streamTurn(run.value.run_id, {
      request_id: turnRequestId,
      expected_revision: run.value.state.revision,
      player_input: submittedInput,
      commands: [
        { type: 'move', payload: { location_id: destination.value } },
        { type: 'narrate', payload: {} },
      ],
    }, (event) => {
      if (activeTurnRequestId.value !== turnRequestId) return
      if (event.event === 'narrative_delta' && typeof event.data.text === 'string') {
        streamingNarrative.value += event.data.text
      }
      if (event.event === 'turn_failed') {
        streamFailure = typeof event.data.detail === 'string' ? event.data.detail : '回合生成失败'
      }
    }, streamController.signal)
    if (streamFailure) throw new Error(streamFailure)
    if (activeTurnRequestId.value !== turnRequestId) return
    playerInput.value = ''
    advanceOperation('applying', '叙事已返回，本机规则正在确认并保存结果。')
    await recoverRun(run.value.run_id)
    if (activeTurnRequestId.value !== turnRequestId) return
    lastTurnAction.value = null
    streamingNarrative.value = ''
    endOperation('completed', '故事已继续，状态已保存。')
  } catch (error) {
    if (activeTurnRequestId.value !== turnRequestId) return
    notice.value = error instanceof Error ? error.message : '回合没有完成'
    endOperation('failed', '本次行动失败；请重试，原状态未改变。')
  } finally {
    if (activeTurnRequestId.value === turnRequestId) {
      markPendingRunOperation(false)
      streamingNarrative.value = ''
      activeTurnRequestId.value = null
      busy.value = false
    }
    if (activeStreamController === streamController) activeStreamController = null
  }
}

async function rollback(turn: Turn) {
  if (!run.value || turn.kind !== 'turn') return
  busy.value = true
  notice.value = ''
  markPendingRunOperation(true)
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
    markPendingRunOperation(false)
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
    hostError.value = error instanceof Error ? error.message : '本机游戏服务无法启动'
    return
  }
  const activeRun = readActiveRun()
  const interruptedRunOperation = consumePendingRunOperation()
  if (activeRun) {
    void (async () => {
      await recoverRun(activeRun, { silentIfMissing: true, preserveNotice: interruptedRunOperation })
      if (interruptedRunOperation) {
        notice.value = '上一次旅程操作在应用关闭前没有完成；本机没有写入半个回合，你可以重新选择。'
      }
    })()
  } else {
    void (async () => {
      const profiles = await refreshModelProfiles().catch(() => [])
      if (!profiles.length) {
        notice.value = '第一次使用先配置一个本地模型；之后就可以开始世界。'
        await openSettings('models')
        startAddingModelProfile()
      } else {
        await openWorldCenter()
        if (!interruptedRunOperation) notice.value = storageBoundaryNotice
      }
      if (interruptedRunOperation) {
        notice.value = '上一次旅程操作在应用关闭前没有完成；本机没有写入半个回合，你可以重新选择。'
      }
    })()
  }
}

onMounted(() => {
  restoreTheme()
  void bootHost()
})

onUnmounted(() => {
  abortActiveStream()
  activeTurnRequestId.value = null
  activeDraftRequestId.value = null
})
</script>

<template>
  <main class="shell">
    <a class="skip-link" href="#main-content">跳到主要内容</a>
    <header class="masthead">
      <a class="brand" href="#" @click.prevent="() => void openWorldCenter()">DZMM</a>
      <p>{{ step === 'settings' ? '本地叙事工作台 · 设置与联动' : '本地叙事工作台 · 世界、规则与回合' }}</p>
      <div class="masthead-actions">
        <nav class="workspace-nav" aria-label="工作台导航">
          <button type="button" :class="{ active: step !== 'settings' }" @click="() => void openWorldCenter()">世界</button>
          <button type="button" :class="{ active: step === 'settings' }" @click="() => void openSettings()">设置</button>
        </nav>
        <div class="host-dot" :class="hostStatus"><i></i> 本机游戏服务 {{ hostStatus === 'ready' ? '已就绪' : hostStatus === 'starting' ? '准备中' : '需要恢复' }}</div>
      </div>
    </header>

    <section v-if="step !== 'settings'" class="route-strip" aria-label="跑团路径">
      <span :class="{ active: step === 'worlds' || step === 'compose' || step === 'ai-compose' }">世界</span><b>—</b>
      <span :class="{ active: step === 'ai-review' || step === 'confirm' }">确认</span><b>—</b>
      <span :class="{ active: step === 'play' }">游玩</span>
    </section>

    <div v-if="notice" class="notice" role="status" aria-live="polite"><span>{{ notice }}</span><button v-if="lastTurnAction && !busy && step === 'play'" class="minor-action" type="button" @click="retryLastTurn">重试上次行动</button></div>
    <OperationStatus
      v-if="visibleOperation"
      :operation="visibleOperation"
      :cancellable="Boolean(activeTurnRequestId || activeDraftRequestId) && isOperationStageCancellable(visibleOperation.stage)"
      :cancel-label="activeDraftRequestId ? '取消本次起草' : '取消本次行动'"
      @cancel="cancelActiveTurn"
    />
    <p v-if="hostError" class="notice" role="alert">
      {{ hostError }} <button class="minor-action" type="button" @click="bootHost">重试本机服务</button>
    </p>
    <div id="main-content" tabindex="-1">
    <section v-if="step === 'settings'" class="scene settings-workbench">
      <header class="settings-heading">
        <div><p class="eyebrow">设置</p><h1>准备好之后，<br />安心进入故事。</h1><p>在这里管理本机服务、模型和外观；游玩时不会突然打断你。</p></div>
        <button class="minor-action" type="button" :disabled="busy" @click="() => void openWorldCenter()">返回世界</button>
      </header>
      <div class="settings-layout">
        <nav class="settings-nav" aria-label="设置分类">
          <button type="button" :class="{ active: settingsSection === 'host' }" @click="() => void selectSettingsSection('host')"><b>本机服务</b><small>状态、诊断与恢复</small></button>
          <button type="button" :class="{ active: settingsSection === 'models' }" @click="() => void selectSettingsSection('models')"><b>本地模型</b><small>完整协议档案</small></button>
          <button type="button" :class="{ active: settingsSection === 'appearance' }" @click="() => void selectSettingsSection('appearance')"><b>外观</b><small>适配故事的主题</small></button>
        </nav>
        <section class="settings-panel">
          <template v-if="settingsSection === 'host'">
            <p class="eyebrow">本机服务</p><h2>本机服务已固定运行</h2>
            <p class="settings-intro">世界、旅程和模型档案都保存在这台电脑。旧版 DZMM 存档不会自动迁移或覆盖 Next 数据；需要带入内容时，请使用世界包或旅程快照。只有你主动导入或导出时，内容才会移动到其他设备。</p>
            <dl class="settings-facts"><div><dt>当前状态</dt><dd>{{ hostStatus === 'ready' ? '可以游玩' : hostStatus === 'starting' ? '正在准备' : '需要恢复' }}</dd></div><div><dt>存档位置</dt><dd>仅此设备</dd></div></dl>
            <div class="settings-actions"><button v-if="hostStatus !== 'ready'" type="button" :disabled="busy" @click="bootHost">恢复本机服务</button><button class="minor-action" type="button" :disabled="busy || !selectedWorld" @click="downloadPortableWorld">导出世界包</button><button class="minor-action" type="button" :disabled="busy || !run" @click="downloadPortableRun">导出旅程快照</button><button class="minor-action" type="button" :disabled="busy || !hostReady" @click="choosePortableBundle">导入世界 / 复制旅程</button><input ref="portableFileInput" class="visually-hidden" type="file" name="portable-bundle" aria-label="选择要导入的世界或旅程文件" accept="application/json,.json" @change="importPortableBundle" /></div>
            <details class="advanced-runtime"><summary>高级诊断信息</summary><p>本机 Python 规则服务使用 SQLite 存档，并固定监听 127.0.0.1。</p><button class="minor-action" type="button" :disabled="busy || !hostReady" @click="downloadDiagnostics">导出不含隐私内容的诊断</button></details>
          </template>
          <template v-else-if="settingsSection === 'models'">
            <p class="eyebrow">本地模型</p><h2>一个模型档案，包含完整连接方式</h2>
            <p class="settings-intro">协议、Base URL 和模型名始终一起保存，避免把 LM Studio 当作 Ollama 调用。</p>
            <ModelProfileList
              :profiles="modelProfiles"
              :busy="busy"
              :probing-profile-id="probingModelProfileId"
              :probe-results="modelProbeResults"
              @probe="probeSavedModelProfile"
              @edit="editModelProfile"
              @make-default="makeDefaultModelProfile"
              @remove="removeModelProfile"
            />
            <div class="settings-actions"><button class="minor-action" type="button" :disabled="busy" @click="() => void openSettings('models')">刷新模型档案</button><button class="minor-action" type="button" :disabled="busy" @click="startAddingModelProfile">添加模型档案</button></div>
            <ModelProfileEditor
              v-if="modelSetupOpen"
              v-model:name="modelProfileDraft.name"
              v-model:provider-type="modelProfileDraft.provider_type"
              v-model:base-url="modelProfileDraft.base_url"
              v-model:model-name="modelProfileDraft.model_name"
              v-model:api-key="modelProfileDraft.api_key"
              :has-saved-credential="Boolean(editingModelProfileId && modelProfiles.find((profile) => profile.id === editingModelProfileId)?.has_api_key)"
              class="settings-model-editor"
              name-prefix="profile"
              :legend="editingModelProfileId ? '编辑模型档案' : '新建模型档案'"
              :submit-label="editingModelProfileId ? '保存修改' : '保存模型档案'"
              :errors="modelProfileErrors"
              :busy="busy"
              show-cancel
              @save="saveModelProfile"
              @cancel="modelSetupOpen = false"
              @provider-change="selectModelProvider"
            />
          </template>
          <template v-else>
            <p class="eyebrow">外观</p><h2>让界面适合正在发生的故事</h2>
            <p class="settings-intro">主题只改变这台电脑的视觉氛围，不改变世界、角色、旅程或故事结果。</p>
            <div class="theme-grid"><button v-for="option in [{ id: 'fog', name: '雾夜', note: '深海绿与旧金色，适合夜间剧情' }, { id: 'paper', name: '纸页', note: '暖白与松绿，适合创作和阅读' }, { id: 'amber', name: '琥珀', note: '深棕与金色，适合悬疑与遗迹' }]" :key="option.id" type="button" :class="['theme-option', option.id, { selected: theme === option.id }]" @click="applyTheme(option.id as Theme)"><b>{{ option.name }}</b><small>{{ option.note }}</small><span>{{ theme === option.id ? '当前使用' : '切换主题' }}</span></button></div>
          </template>
        </section>
      </div>
    </section>

    <section v-else-if="step === 'worlds'" class="scene world-center">
      <div class="world-center-heading">
        <div><p class="eyebrow">我的世界</p><h1>回到熟悉的世界，<br />或开启新的故事。</h1></div>
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
          <WorldRunLauncher
            v-model:open="newRunOpen"
            v-model:hero-name="newRunHeroName"
            v-model:model-profile-id="newRunModelProfileId"
            :world="selectedWorld"
            :model-profiles="modelProfiles"
            :busy="busy"
            @continue="continueRun"
            @start="startNewRun"
          />
          <dl>
            <div><dt>内容版本</dt><dd>{{ selectedWorld.world_version_count }}</dd></div>
            <div><dt>旅程</dt><dd>{{ selectedWorld.run_count }}</dd></div>
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
              <div><p class="eyebrow">编辑世界书</p><p>保存会创建新的内容版本；已经开始的旅程仍保留原来的世界内容。</p></div>
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
        <p>模型只返回待审阅的创作素材；本机规则会整理成安全草案。确认前，不会创建世界、旅程或任何存档。</p>
      </div>
      <form class="ledger-card" @submit.prevent="generateDraft">
        <div class="model-draft-heading"><label>本地模型档案<select v-model="aiModelProfileId" name="ai-model-profile" required><option value="" disabled>选择已配置模型</option><option v-for="profile in modelProfiles" :key="profile.id" :value="profile.id">{{ profile.name }} · {{ profile.model_name }}</option></select></label><button class="minor-action" type="button" :disabled="busy" @click="toggleDraftModelSetup">{{ modelSetupOpen ? '收起配置' : '配置本地模型' }}</button></div>
        <ModelProfileEditor
          v-if="modelSetupOpen"
          v-model:name="modelProfileDraft.name"
          v-model:provider-type="modelProfileDraft.provider_type"
          v-model:base-url="modelProfileDraft.base_url"
          v-model:model-name="modelProfileDraft.model_name"
          v-model:api-key="modelProfileDraft.api_key"
          :has-saved-credential="Boolean(editingModelProfileId && modelProfiles.find((profile) => profile.id === editingModelProfileId)?.has_api_key)"
          name-prefix="draft-profile"
          legend="新建模型档案"
          submit-label="保存并选择"
          :errors="modelProfileErrors"
          :busy="busy"
          @save="saveModelProfile"
          @provider-change="selectModelProvider"
        />
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
        <p class="draft-safe-note">模型没有创建任何世界、旅程或存档。编辑后必须重新校验；只有最终确认才会保存。</p>
        <section v-if="aiDraftReview" class="draft-structured-review" aria-label="结构化草案审阅">
          <div class="draft-review-heading"><div><p class="eyebrow">可编辑叙事素材</p><p>修改这里的内容会同步到草案，再由本机规则校验；不会直接写入任何真实存档。</p></div><span>{{ aiDraft.valid && !aiDraftNeedsValidation ? '已通过规则校验' : '等待规则校验' }}</span></div>
          <div class="draft-field-grid"><label>世界名称<input v-model.trim="aiDraftReview.worldName" required maxlength="120" @input="syncStructuredDraftEdits" /></label><label>主角名称<input v-model.trim="aiDraftReview.heroName" required maxlength="120" @input="syncStructuredDraftEdits" /></label></div>
          <label>主角背景<textarea v-model.trim="aiDraftReview.heroOrigin" rows="2" maxlength="400" @input="syncStructuredDraftEdits"></textarea></label>
          <section class="draft-material"><p class="eyebrow">地点</p><div class="draft-field-grid"><label v-for="(_, index) in aiDraftReview.locations" :key="`location-${index}`">{{ index === 0 ? '起始地点' : '远方地点' }}<input v-model.trim="aiDraftReview.locations[index]" required @input="syncStructuredDraftEdits" /></label></div></section>
          <section class="draft-material"><p class="eyebrow">角色卡</p><article v-for="(character, index) in aiDraftReview.characters" :key="`character-${index}`"><label>名称<input v-model.trim="character.name" required @input="syncStructuredDraftEdits" /></label><label>角色定位<input v-model.trim="character.role" required @input="syncStructuredDraftEdits" /></label><label>人物描述<textarea v-model.trim="character.description" rows="2" required @input="syncStructuredDraftEdits"></textarea></label></article></section>
          <section class="draft-material"><p class="eyebrow">世界书</p><article v-for="(lore, index) in aiDraftReview.lore" :key="`lore-${index}`"><label>条目标题<input v-model.trim="lore.title" required @input="syncStructuredDraftEdits" /></label><label>条目内容<textarea v-model.trim="lore.body" rows="2" required @input="syncStructuredDraftEdits"></textarea></label></article></section>
          <section class="draft-rules-preview"><p class="eyebrow">故事规则预览（只读）</p><p>章节、选择、关系、路线和结局都由本机规则预先验证；模型或此表单不能直接修改真实存档。</p><article v-for="(chapter, index) in draftRulePreview.chapters" :key="`chapter-${index}`"><b>第 {{ index + 1 }} 章 · {{ chapter.title }}</b><small>{{ chapter.choices?.map(choice => choice.label).filter(Boolean).join(' · ') || '游玩时显示可用选择' }}</small></article><div><span>{{ draftRulePreview.relationships }} 组关系</span><span>{{ draftRulePreview.routes }} 条路线</span><span>{{ draftRulePreview.endings }} 个结局</span></div></section>
        </section>
        <details class="advanced-draft-editor"><summary>高级编辑：查看或修改 schema v3 JSON</summary><p>仅在需要完整 schema 编辑时使用。无法解析或校验失败时，可恢复上一份有效草案。</p><label>WorldDefinition<textarea v-model="aiDraftDefinitionJson" rows="14" spellcheck="false" aria-label="高级编辑 WorldDefinition 草案" @input="markDraftEditsDirty"></textarea></label><label>Hero<textarea v-model="aiDraftHeroJson" rows="4" spellcheck="false" aria-label="高级编辑主角草案" @input="markDraftEditsDirty"></textarea></label></details>
        <ul v-if="aiDraft.issues.length" class="draft-issues"><li v-for="issue in aiDraft.issues" :key="`${issue.path}-${issue.message}`"><b>{{ draftIssueHelp(issue.path)[0] }}</b><span>{{ issue.message }}</span><small>{{ draftIssueHelp(issue.path)[1] }}</small></li></ul>
        <div class="world-actions"><button class="minor-action" type="button" :disabled="busy" @click="validateDraftEdits">验证编辑</button><button v-if="aiLastValidDraft" class="minor-action" type="button" :disabled="busy" @click="restoreLastValidDraft">恢复上一份有效草案</button><button class="minor-action" type="button" :disabled="busy" @click="cancelDraft">取消并丢弃</button><button type="submit" :disabled="busy || !aiDraft.valid || aiDraftNeedsValidation">确认并创建世界</button></div>
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
            <span><b>自定义 TRPG</b><small>地点、行动与本机规则裁决</small></span>
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
          <p>支持 V3 角色卡 JSON/PNG 与 World Info JSON。无论选择哪种玩法，它们都会作为世界书和角色卡保存到新的内容版本。</p>
          <textarea v-model="importJson" placeholder="粘贴 SillyTavern JSON…" rows="5"></textarea>
          <div class="import-actions">
            <button type="button" class="minor-action" @click="applySillyTavernImport">解析 JSON 并应用</button>
            <label class="file-import">导入角色卡 PNG<input type="file" accept="image/png,.png" @change="applySillyTavernPng" /></label>
          </div>
          <p v-if="importedContent" class="import-result">
            已导入 {{ importedContent.lorebook.entries.length }} 条世界书条目、{{ importedContent.character_cards.length }} 张角色卡 · {{ importedContent.report.source_format }}
          </p>
        </details>
        <button :disabled="busy || !hostReady">{{ busy ? '正在装订世界…' : hostReady ? '确认并创建世界' : '等待本机服务…' }}</button>
      </form>
    </section>

    <section v-else-if="step === 'confirm' && composed" class="scene confirmation">
      <p class="eyebrow">世界已装订</p>
      <h1>{{ worldName }}</h1>
      <p>第一版世界内容已保存。{{ heroName }} 将从 {{ harborName }} 出发；之后的经历只属于这一次旅程。</p>
      <dl>
        <div><dt>世界内容</dt><dd>已保存</dd></div>
        <div><dt>首次旅程</dt><dd>已准备</dd></div>
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
      <button :disabled="busy || !hostReady" @click="enterRun">进入故事开场</button>
    </section>

    <PlayScene
      v-else-if="run"
      v-model:player-input="playerInput"
      v-model:destination="destination"
      :run="run"
      :busy="busy"
      :host-ready="hostReady"
      :streaming-narrative="streamingNarrative"
      :harbor-name="harborName"
      :lighthouse-name="lighthouseName"
      @choose="chooseStory"
      @rollback="rollback"
      @send="sendTurn"
      @new-run="beginNewRunFromCurrentWorld"
      @return-world="returnToCurrentWorld"
    />
    </div>
  </main>
</template>
