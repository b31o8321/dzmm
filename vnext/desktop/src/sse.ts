export type ParsedSseEvent = {
  event: string
  data: Record<string, unknown>
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
