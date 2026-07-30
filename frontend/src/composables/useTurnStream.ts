import { backendOrigin } from '@/api/client'

export interface TurnHandlers {
  onNarrative?: (text: string) => void
  onTag?: (name: string, attrs: Record<string, string>, content: string) => void
  onError?: (message: string) => void
  onDone?: (doneData?: { assistant_msg_id?: number }) => void
}

export class TurnStreamError extends Error {
  constructor(
    public readonly code: string,
    message: string,
    public readonly runId?: string,
  ) {
    super(message)
    this.name = 'TurnStreamError'
  }
}

/**
 * Create an idempotent run, then consume its reconnectable SSE stream.
 *
 * Backend emits `event: <name>\ndata: <json>\n\n` blocks. We parse with a
 * line-buffer state machine — no library needed.
 */
export async function streamTurn(
  sessionId: number,
  requestId: string,
  action: string,
  handlers: TurnHandlers,
  signal?: AbortSignal,
): Promise<void> {
  const createUrl = `${backendOrigin}/sessions/${sessionId}/turn-runs`
  const createResp = await createOrRecoverRun(
    createUrl, requestId, action, signal,
  )
  if (!createResp.ok) {
    throw await responseError(createResp, 'turn_create_failed')
  }
  const run = await createResp.json() as { run_id: string; status: string }
  const runUrl = `${backendOrigin}/sessions/${sessionId}/turn-runs/${encodeURIComponent(run.run_id)}`
  let lastEventId = 0
  let reconnectAttempt = 0

  while (true) {
    let response: Response
    try {
      response = await fetch(`${runUrl}/events`, {
        headers: {
          Accept: 'text/event-stream',
          ...(lastEventId > 0 ? { 'Last-Event-ID': String(lastEventId) } : {}),
        },
        signal,
      })
    } catch (error) {
      if (signal?.aborted) throw error
      await reconnectDelay(reconnectAttempt++, signal)
      continue
    }
    if (!response.ok || !response.body) {
      const error = await responseError(response, 'turn_stream_failed')
      if (error.code === 'event_gap') {
        throw await settleEventGap(runUrl, run.run_id, error, signal)
      }
      if (response.status >= 400 && response.status < 500) throw error
      await reconnectDelay(reconnectAttempt++, signal)
      continue
    }

    const result = await consume(response.body, handlers, lastEventId, signal)
    lastEventId = result.lastEventId
    if (result.done) return
    if (result.error) throw result.error

    let statusResp: Response
    try {
      statusResp = await fetch(runUrl, { signal })
    } catch (error) {
      if (signal?.aborted) throw error
      await reconnectDelay(reconnectAttempt++, signal)
      continue
    }
    if (!statusResp.ok) throw await responseError(statusResp, 'turn_status_failed')
    const status = await statusResp.json() as {
      status: string
      error_code?: string | null
      error_message?: string | null
    }
    if (status.status === 'failed' || status.status === 'interrupted') {
      throw new TurnStreamError(
        status.error_code ?? 'model_error',
        status.error_message ?? '回合生成失败',
      )
    }
    reconnectAttempt = 0
    await reconnectDelay(reconnectAttempt++, signal)
  }
}

async function consume(
  body: ReadableStream<Uint8Array>,
  handlers: TurnHandlers,
  initialEventId: number,
  signal?: AbortSignal,
): Promise<{ lastEventId: number; done: boolean; error?: TurnStreamError }> {
  const reader = body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''
  let lastEventId = initialEventId
  while (true) {
    let chunk: ReadableStreamReadResult<Uint8Array>
    try {
      chunk = await reader.read()
    } catch (error) {
      if (signal?.aborted) throw error
      return { lastEventId, done: false }
    }
    const { value, done } = chunk
    if (done) break
    buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, '\n')
    let separator: number
    while ((separator = buffer.indexOf('\n\n')) >= 0) {
      const block = buffer.slice(0, separator)
      buffer = buffer.slice(separator + 2)
      const dispatched = dispatch(block, handlers)
      if (dispatched.id !== undefined) lastEventId = dispatched.id
      if (dispatched.done || dispatched.error) {
        return { lastEventId, done: dispatched.done, error: dispatched.error }
      }
    }
  }
  if (buffer.trim()) {
    const dispatched = dispatch(buffer, handlers)
    if (dispatched.id !== undefined) lastEventId = dispatched.id
    if (dispatched.done || dispatched.error) {
      return { lastEventId, done: dispatched.done, error: dispatched.error }
    }
  }
  return { lastEventId, done: false }
}

function dispatch(
  block: string,
  h: TurnHandlers,
): { id?: number; done: boolean; error?: TurnStreamError } {
  let event = 'message'
  let data = ''
  let id: number | undefined
  for (const line of block.split('\n')) {
    if (line.startsWith('event: ')) event = line.slice(7).trim()
    else if (line.startsWith('data: ')) data += line.slice(6)
    else if (line.startsWith('id:')) {
      const parsed = Number(line.slice(3).trim())
      if (Number.isInteger(parsed)) id = parsed
    }
  }
  if (!data) return { id, done: false }

  let parsed: any
  try {
    parsed = JSON.parse(data)
  } catch {
    return { id, done: false }
  }

  switch (event) {
    case 'narrative':
      h.onNarrative?.(parsed.text ?? '')
      break
    case 'tag':
      h.onTag?.(parsed.name, parsed.attrs ?? {}, parsed.content ?? '')
      break
    case 'parse_error':
    case 'summarize_error':
      h.onError?.(parsed.message ?? 'error')
      break
    case 'error': {
      const error = new TurnStreamError(
        parsed.code ?? 'model_error',
        parsed.message ?? '回合生成失败',
      )
      h.onError?.(error.message)
      return { id, done: false, error }
    }
    case 'done': {
      let doneData: { assistant_msg_id?: number } = {}
      try { doneData = parsed ?? {} } catch { /* ignore */ }
      h.onDone?.(doneData)
      return { id, done: true }
    }
  }
  return { id, done: false }
}

async function createOrRecoverRun(
  url: string,
  requestId: string,
  action: string,
  signal?: AbortSignal,
): Promise<Response> {
  let lastError: unknown
  for (let attempt = 0; attempt < 5; attempt += 1) {
    try {
      return await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ request_id: requestId, action }),
        signal,
      })
    } catch (error) {
      if (signal?.aborted) throw error
      lastError = error
      await reconnectDelay(attempt, signal)
    }
  }
  throw new TurnStreamError(
    'turn_create_failed',
    lastError instanceof Error ? lastError.message : '无法创建回合',
  )
}

async function settleEventGap(
  runUrl: string,
  runId: string,
  gap: TurnStreamError,
  signal?: AbortSignal,
): Promise<TurnStreamError> {
  let attempt = 0
  while (true) {
    try {
      const response = await fetch(runUrl, { signal })
      if (!response.ok) throw await responseError(response, 'turn_status_failed')
      const status = await response.json() as {
        status: string
        error_code?: string | null
        error_message?: string | null
      }
      if (status.status === 'completed') {
        return new TurnStreamError(gap.code, gap.message, runId)
      }
      if (status.status === 'failed' || status.status === 'interrupted') {
        return new TurnStreamError(
          status.error_code ?? 'model_error',
          status.error_message ?? '回合生成失败',
          runId,
        )
      }
      await reconnectDelay(attempt++, signal)
    } catch (error) {
      if (signal?.aborted || error instanceof TurnStreamError) throw error
      await reconnectDelay(attempt++, signal)
    }
  }
}

async function responseError(response: Response, fallbackCode: string): Promise<TurnStreamError> {
  try {
    const payload = await response.json() as { code?: string; message?: string }
    return new TurnStreamError(
      payload.code ?? fallbackCode,
      payload.message ?? `请求失败 (${response.status})`,
    )
  } catch {
    return new TurnStreamError(fallbackCode, `请求失败 (${response.status})`)
  }
}

async function reconnectDelay(attempt: number, signal?: AbortSignal): Promise<void> {
  const delay = Math.min(3000, 250 * (2 ** Math.min(attempt, 4)))
  await new Promise<void>((resolve, reject) => {
    const onAbort = () => {
      clearTimeout(timer)
      reject(signal?.reason ?? new DOMException('Aborted', 'AbortError'))
    }
    const timer = setTimeout(() => {
      signal?.removeEventListener('abort', onAbort)
      resolve()
    }, delay)
    signal?.addEventListener('abort', onAbort, { once: true })
  })
}
