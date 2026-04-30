/**
 * Helpers for the Playwright E2E suite.
 *
 * The actual backend + frontend processes are launched by Playwright's
 * `webServer` config (see ../playwright.config.ts). This module exposes
 * a couple of convenience helpers for tests that want to talk to the
 * stub backend directly (e.g. seed data inspection or health checks).
 */

export const BACKEND_URL = 'http://127.0.0.1:8765'
export const FRONTEND_URL = 'http://127.0.0.1:5173'

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
