import { describe, expect, it } from 'vitest'

import type { ImportedContent } from './local_host_port'
import { attachImportedContent, mergeImportedContent } from './portableContent'

const content = (id: string, name = '岚'): ImportedContent => ({
  suggested_hero: null,
  lorebook: { entries: [{ id, title: '潮汐', body: '雾港的潮水。', activation: 'always', priority: 1 }] },
  character_cards: [{ id: `card-${id}`, name, format: 'native' }],
  report: { source_format: 'sillytavern_v3', supported_fields: ['name'], preserved_fields: ['name'], ignored_fields: [], warnings: [] },
})

describe('portable content composition', () => {
  it('merges independent imports without losing the suggested report', () => {
    const merged = mergeImportedContent(content('one'), content('two', '沈砚'))

    expect(merged.lorebook.entries).toHaveLength(2)
    expect(merged.character_cards.map((card) => card.name)).toEqual(['岚', '沈砚'])
    expect(merged.report.source_format).toBe('multiple_sillytavern_sources')
  })

  it('rejects duplicate assets and template collisions before world creation', () => {
    expect(() => mergeImportedContent(content('one'), content('one'))).toThrow('ID 冲突')
    expect(() => attachImportedContent({
      lorebook: { entries: [{ id: 'template', title: '内置', body: '内容' }] },
      character_cards: [{ id: 'template-card', name: '岚' }],
    }, content('new'))).toThrow('覆盖世界模板')
  })
})
