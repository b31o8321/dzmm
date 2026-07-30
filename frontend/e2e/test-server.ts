/**
 * Helpers for the Playwright E2E suite.
 *
 * The actual backend + frontend processes are launched by Playwright's
 * `webServer` config (see ../playwright.config.ts). This module exposes
 * a couple of convenience helpers for tests that want to talk to the
 * stub backend directly (e.g. seed data inspection or health checks).
 */

const backendPort = process.env.DZMM_E2E_BACKEND_PORT ?? '28765'
const frontendPort = process.env.DZMM_E2E_FRONTEND_PORT ?? '25173'

export const BACKEND_URL = `http://127.0.0.1:${backendPort}`
export const FRONTEND_URL = `http://127.0.0.1:${frontendPort}`

/**
 * Polls the backend `/health` endpoint until it responds OK or `timeoutMs`
 * elapses. Useful inside tests that want belt-and-suspenders confirmation
 * that the stub backend is alive before driving the UI.
 */
export async function waitForBackend(timeoutMs = 30_000): Promise<void> {
  const deadline = Date.now() + timeoutMs
  let lastErr: unknown = null
  while (Date.now() < deadline) {
    try {
      const r = await fetch(`${BACKEND_URL}/health`)
      if (r.ok) return
      lastErr = new Error(`status ${r.status}`)
    } catch (e) {
      lastErr = e
    }
    await new Promise((r) => setTimeout(r, 250))
  }
  throw new Error(`backend not ready after ${timeoutMs}ms: ${String(lastErr)}`)
}

export async function waitForTurnRun(
  sessionId: number,
  runId: string,
  timeoutMs = 30_000,
): Promise<Record<string, unknown>> {
  const deadline = Date.now() + timeoutMs
  let latest: Record<string, unknown> = {}
  while (Date.now() < deadline) {
    const response = await fetch(
      `${BACKEND_URL}/sessions/${sessionId}/turn-runs/${encodeURIComponent(runId)}`,
    )
    if (response.ok) {
      latest = await response.json() as Record<string, unknown>
      if (latest.status !== 'running') return latest
    }
    await new Promise((resolve) => setTimeout(resolve, 100))
  }
  throw new Error(`turn run ${runId} did not finish: ${JSON.stringify(latest)}`)
}
