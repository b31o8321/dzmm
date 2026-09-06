import { invoke, isTauri } from '@tauri-apps/api/core'

const healthTimeoutMs = 20_000
let hostOrigin: string | null = null

async function waitForHealth(origin: string): Promise<void> {
  const deadline = Date.now() + healthTimeoutMs
  while (Date.now() < deadline) {
    try {
      const response = await fetch(`${origin}/health`, { cache: 'no-store' })
      const health = (await response.json()) as { app?: string }
      if (response.ok && health.app === 'dzmm') return
    } catch {
      // The sidecar can take several seconds to unpack and migrate on first launch.
    }
    await new Promise((resolve) => window.setTimeout(resolve, 250))
  }
  throw new Error('桌面 Host 未能在 20 秒内就绪，请检查端口和诊断日志。')
}

export async function startHost(): Promise<string | null> {
  if (!isTauri()) return null
  const origin = await invoke<string>('start_backend')
  await waitForHealth(origin)
  hostOrigin = origin
  return `${origin}/api/v2`
}
