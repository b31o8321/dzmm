import { describe, expect, it } from 'vitest'

import { parseSseBlock } from './sse'

describe('SSE event parser', () => {
  it('parses the event name and JSON payload without exposing transport fields', () => {
    expect(parseSseBlock('id: 2\nevent: narrative_delta\ndata: {"text":"潮雾"}\n')).toEqual({
      event: 'narrative_delta',
      data: { text: '潮雾' },
    })
  })

  it('ignores empty or malformed payloads', () => {
    expect(parseSseBlock('event: narrative_delta\n\n')).toBeNull()
    expect(parseSseBlock('event: narrative_delta\ndata: [1]\n')).toBeNull()
    expect(parseSseBlock('event: narrative_delta\ndata: not-json\n')).toBeNull()
  })
})
