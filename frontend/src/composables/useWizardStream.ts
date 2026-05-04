import { backendOrigin } from '@/api/client'

export interface WizardStreamHandlers<T = any> {
  onDelta: (text: string) => void
  onResult: (data: T) => void
  onError: (msg: string) => void
}

/**
 * POST `path` with `body`, consume the wizard SSE stream.
 *
 * Events from backend:
 *   delta  → {"text": "..."}   raw token chunk
 *   result → {...parsed data}  final result on success
 *   error  → {"message": "..."} on failure
 */
export async function streamWizardStep<T>(
  path: string,
  body: object,
  handlers: WizardStreamHandlers<T>,
  signal?: AbortSignal,
): Promise<void> {
  const resp = await fetch(`${backendOrigin}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    body: JSON.stringify(body),
    signal,
  })
  if (!resp.ok || !resp.body) {
    const text = await resp.text().catch(() => resp.statusText)
    throw new Error(`wizard stream failed: ${resp.status} ${text}`)
  }

  const reader = resp.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buf = ''

  while (true) {
    const { value, done } = await reader.read()
    if (done) break
    buf += decoder.decode(value, { stream: true }).replace(/\r\n/g, '\n')

    let nl: number
    while ((nl = buf.indexOf('\n\n')) >= 0) {
      const block = buf.slice(0, nl)
      buf = buf.slice(nl + 2)
      dispatchBlock(block, handlers)
    }
  }
  if (buf.trim()) dispatchBlock(buf, handlers)
}

function dispatchBlock<T>(block: string, h: WizardStreamHandlers<T>) {
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

  if (event === 'delta') {
    h.onDelta(parsed.text ?? '')
  } else if (event === 'result') {
    h.onResult(parsed as T)
  } else if (event === 'error') {
    h.onError(parsed.message ?? 'unknown error')
  }
}
