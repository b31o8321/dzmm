import type { TurnEvent } from '@/api/types'
import { backendOrigin } from '@/api/client'

export interface TurnHandlers {
  onNarrative?: (text: string) => void
  onTag?: (name: string, attrs: Record<string, string>, content: string) => void
  onError?: (message: string) => void
  onDone?: (doneData?: { assistant_msg_id?: number }) => void
}

/**
 * Consume the SSE stream from POST /sessions/{id}/turn.
 *
 * Backend emits `event: <name>\ndata: <json>\n\n` blocks. We parse with a
 * line-buffer state machine — no library needed.
 */
export async function streamTurn(
  sessionId: number,
  action: string,
  handlers: TurnHandlers,
  signal?: AbortSignal,
): Promise<void> {
  const resp = await fetch(`${backendOrigin}/sessions/${sessionId}/turn`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    body: JSON.stringify({ action }),
    signal,
  })
  if (!resp.ok || !resp.body) {
    throw new Error(`turn failed: ${resp.status} ${resp.statusText}`)
  }

  const reader = resp.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buf = ''

  while (true) {
    const { value, done } = await reader.read()
    if (done) break
    // Normalize CRLF → LF first. sse_starlette uses \r\n per spec; our
    // split-on-\n\n logic only works after normalization.
    buf += decoder.decode(value, { stream: true }).replace(/\r\n/g, '\n')

    let nl: number
    while ((nl = buf.indexOf('\n\n')) >= 0) {
      const block = buf.slice(0, nl)
      buf = buf.slice(nl + 2)
      dispatch(block, handlers)
    }
  }
  if (buf.trim()) dispatch(buf, handlers)
}

function dispatch(block: string, h: TurnHandlers) {
  let event = 'message'
  let data = ''
  for (const line of block.split('\n')) {
    if (line.startsWith('event: ')) event = line.slice(7).trim()
    else if (line.startsWith('data: ')) data += line.slice(6)
  }
  if (!data) return

  let parsed: any
  try {
    parsed = JSON.parse(data)
  } catch {
    return
  }

  switch (event as TurnEvent['type']) {
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
    case 'done': {
      let doneData: { assistant_msg_id?: number } = {}
      try { doneData = parsed ?? {} } catch { /* ignore */ }
      h.onDone?.(doneData)
      break
    }
  }
}
