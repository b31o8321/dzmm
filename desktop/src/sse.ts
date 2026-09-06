export type ParsedSseEvent = {
  event: string
  data: Record<string, unknown>
}

export async function consumeSseStream(
  body: ReadableStream<Uint8Array>,
  onEvent: (event: ParsedSseEvent) => void,
): Promise<void> {
  const reader = body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  const consume = (complete: boolean) => {
    const blocks = buffer.split(/\r?\n\r?\n/)
    buffer = complete ? '' : blocks.pop() ?? ''
    for (const block of blocks) {
      const event = parseSseBlock(block)
      if (event) onEvent(event)
    }
  }
  while (true) {
    const chunk = await reader.read()
    buffer += decoder.decode(chunk.value ?? new Uint8Array(), { stream: !chunk.done })
    consume(chunk.done)
    if (chunk.done) return
  }
}

export function parseSseBlock(block: string): ParsedSseEvent | null {
  let event = 'message'
  let data = ''
  for (const line of block.split(/\r?\n/)) {
    if (line.startsWith('event:')) event = line.slice('event:'.length).trim()
    if (line.startsWith('data:')) data += line.slice('data:'.length).trim()
  }
  if (!data) return null
  try {
    const parsed = JSON.parse(data) as unknown
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return null
    return { event, data: parsed as Record<string, unknown> }
  } catch {
    return null
  }
}
