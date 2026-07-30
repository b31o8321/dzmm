import { afterEach, describe, expect, it, vi } from 'vitest'

import { streamTurn, TurnStreamError } from '@/composables/useTurnStream'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function sseResponse(body: string): Response {
  return new Response(body, {
    status: 200,
    headers: { 'Content-Type': 'text/event-stream' },
  })
}

function brokenSseResponse(body: string): Response {
  const bytes = new TextEncoder().encode(body)
  let sent = false
  const stream = new ReadableStream<Uint8Array>({
    pull(controller) {
      if (!sent) {
        sent = true
        controller.enqueue(bytes)
      } else {
        controller.error(new TypeError('socket closed'))
      }
    },
  })
  return new Response(stream, {
    status: 200,
    headers: { 'Content-Type': 'text/event-stream' },
  })
}

describe('reconnectable turn stream', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('resumes with Last-Event-ID and does not duplicate narrative', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse({ run_id: 'run-1', status: 'running' }, 202))
      .mockResolvedValueOnce(brokenSseResponse(
        'id: 1\nevent: narrative\ndata: {"text":"门后"}\n\n',
      ))
      .mockResolvedValueOnce(jsonResponse({ status: 'running' }))
      .mockResolvedValueOnce(sseResponse(
        'id: 2\nevent: done\ndata: {"assistant_msg_id":9}\n\n',
      ))
    vi.stubGlobal('fetch', fetchMock)
    const onNarrative = vi.fn()
    const onDone = vi.fn()

    await streamTurn(7, 'request-7', '检查门后', { onNarrative, onDone })

    expect(onNarrative).toHaveBeenCalledTimes(1)
    expect(onNarrative).toHaveBeenCalledWith('门后')
    expect(onDone).toHaveBeenCalledWith({ assistant_msg_id: 9 })
    expect(fetchMock.mock.calls[3][1].headers['Last-Event-ID']).toBe('1')
  })

  it('surfaces event_gap as a stable machine-readable error', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse({ run_id: 'run-gap', status: 'running' }, 202))
      .mockResolvedValueOnce(jsonResponse({
        code: 'event_gap',
        message: '事件已过期',
      }, 409))
      .mockResolvedValueOnce(jsonResponse({ status: 'completed' }))
    vi.stubGlobal('fetch', fetchMock)

    await expect(streamTurn(3, 'request-gap', '继续', {})).rejects.toMatchObject({
      name: 'TurnStreamError',
      code: 'event_gap',
      message: '事件已过期',
      runId: 'run-gap',
    } satisfies Partial<TurnStreamError>)
  })

  it('retries a lost create response with the same request id', async () => {
    const fetchMock = vi.fn()
      .mockRejectedValueOnce(new TypeError('network reset'))
      .mockResolvedValueOnce(jsonResponse({ run_id: 'run-recovered', status: 'running' }, 202))
      .mockResolvedValueOnce(sseResponse(
        'id: 1\nevent: done\ndata: {"assistant_msg_id":5}\n\n',
      ))
    vi.stubGlobal('fetch', fetchMock)

    await streamTurn(5, 'stable-request-id', '前进', {})

    const firstBody = JSON.parse(fetchMock.mock.calls[0][1].body)
    const secondBody = JSON.parse(fetchMock.mock.calls[1][1].body)
    expect(firstBody.request_id).toBe('stable-request-id')
    expect(secondBody.request_id).toBe('stable-request-id')
  })
})
