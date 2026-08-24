import type { ImportedContent } from './local_host_port'

type Asset = Record<string, unknown>

function duplicateAssetIds(existing: Asset[], incoming: Asset[]) {
  return incoming
    .map((item) => item.id)
    .filter((id): id is string => typeof id === 'string' && existing.some((item) => item.id === id))
}

export function mergeImportedContent(
  current: ImportedContent | null,
  incoming: ImportedContent,
): ImportedContent {
  if (!current) return incoming
  const duplicateLore = duplicateAssetIds(current.lorebook.entries, incoming.lorebook.entries)
  const duplicateCards = duplicateAssetIds(current.character_cards, incoming.character_cards)
  if (duplicateLore.length || duplicateCards.length) {
    const descriptions = [
      duplicateLore.length ? `世界书：${duplicateLore.join('、')}` : '',
      duplicateCards.length ? `角色卡：${duplicateCards.join('、')}` : '',
    ].filter(Boolean)
    throw new Error(`导入内容与已选内容 ID 冲突（${descriptions.join('；')}），请移除重复卡或条目。`)
  }
  return {
    suggested_hero: current.suggested_hero ?? incoming.suggested_hero,
    lorebook: { entries: [...current.lorebook.entries, ...incoming.lorebook.entries] },
    character_cards: [...current.character_cards, ...incoming.character_cards],
    report: {
      source_format: 'multiple_sillytavern_sources',
      supported_fields: [...new Set([...current.report.supported_fields, ...incoming.report.supported_fields])],
      preserved_fields: [...new Set([...current.report.preserved_fields, ...incoming.report.preserved_fields])],
      ignored_fields: [...new Set([...current.report.ignored_fields, ...incoming.report.ignored_fields])],
      warnings: [...current.report.warnings, ...incoming.report.warnings],
    },
  }
}

export function attachImportedContent(
  definition: Record<string, unknown>,
  importedContent: ImportedContent | null,
): Record<string, unknown> {
  if (!importedContent) return definition
  const lorebook = definition.lorebook as { entries: Asset[] }
  const characterCards = definition.character_cards as Asset[]
  const incomingLore = importedContent.lorebook.entries
  const incomingCards = importedContent.character_cards
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
