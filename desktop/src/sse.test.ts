import { describe, expect, it } from 'vitest'

import { consumeSseStream, parseSseBlock } from './sse'

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

  it('consumes CRLF and a final block without a trailing blank line', async () => {
    const encoder = new TextEncoder()
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(encoder.encode('event: turn_started\r\ndata: {"revision":1}\r\n\r\n'))
        controller.enqueue(encoder.encode('event: turn_completed\r\ndata: {"revision":2}'))
        controller.close()
      },
    })
    const events: string[] = []

    await consumeSseStream(body, (event) => events.push(`${event.event}:${String(event.data.revision)}`))

    expect(events).toEqual(['turn_started:1', 'turn_completed:2'])
  })
})
