import { describe, expect, it, vi } from 'vitest'

import { setApiBase, streamTurn } from './api'

describe('streamTurn', () => {
  it('delivers narrative deltas across chunk boundaries before completion', async () => {
    const encoder = new TextEncoder()
    const chunks = [
      'id: 1\nevent: turn_started\ndata: {"revision":2}\n\n',
      'id: 2\nevent: narrative_delta\ndata: {"text":"潮',
      '雾"}\n\nid: 3\nevent: turn_completed\ndata: {"revision":3}\n\n',
    ]
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        for (const chunk of chunks) controller.enqueue(encoder.encode(chunk))
        controller.close()
      },
    })
    const fetchMock = vi.fn().mockResolvedValue(new Response(body, { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)
    setApiBase('http://127.0.0.1:8765/api/v2')
    const events: string[] = []

    await streamTurn('run-1', { request_id: 'turn-1' }, (event) => {
      events.push(`${event.event}:${String(event.data.text ?? event.data.revision)}`)
    })

    expect(events).toEqual(['turn_started:2', 'narrative_delta:潮雾', 'turn_completed:3'])
    expect(fetchMock).toHaveBeenCalledWith(
      'http://127.0.0.1:8765/api/v2/runs/run-1/turns:stream',
      expect.objectContaining({ method: 'POST' }),
    )
    setApiBase('/api/v2')
    vi.unstubAllGlobals()
  })
})
