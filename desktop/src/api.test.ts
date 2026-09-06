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
    const controller = new AbortController()

    await streamTurn('run-1', { request_id: 'turn-1' }, (event) => {
      events.push(`${event.event}:${String(event.data.text ?? event.data.revision)}`)
    }, controller.signal)

    expect(events).toEqual(['turn_started:2', 'narrative_delta:潮雾', 'turn_completed:3'])
    expect(fetchMock).toHaveBeenCalledWith(
      'http://127.0.0.1:8765/api/v2/runs/run-1/turns:stream',
      expect.objectContaining({ method: 'POST', signal: expect.any(AbortSignal) }),
    )
    setApiBase('/api/v2')
    vi.unstubAllGlobals()
  })

  it('passes an AbortSignal through so a stale run can stop reading the stream', async () => {
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(new TextEncoder().encode('event: turn_started\ndata: {"revision":1}\n\n'))
        controller.close()
      },
    })
    const fetchMock = vi.fn().mockResolvedValue(new Response(body, { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)
    const controller = new AbortController()

    await streamTurn('run-2', { request_id: 'turn-2' }, () => {}, controller.signal)

    expect(fetchMock.mock.calls[0]?.[1]).toEqual(expect.objectContaining({ signal: controller.signal }))
    setApiBase('/api/v2')
    vi.unstubAllGlobals()
  })
})
