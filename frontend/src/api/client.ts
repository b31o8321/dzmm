import axios from 'axios'

// Backend port is fixed; the host is derived at runtime so the same bundle
// works in three contexts:
//   - Tauri prod webview (window.location.hostname = "tauri.localhost" or "localhost")
//   - Local dev browser (hostname = "localhost" / "127.0.0.1")
//   - LAN access from another device (hostname = the Mac's LAN IP)
// This requires the backend to bind 0.0.0.0 when LAN access is desired
// (DZMM_HOST=0.0.0.0). Default 127.0.0.1 still works for local-only modes.
function deriveBaseURL(): string {
  const host =
    (typeof window !== 'undefined' && window.location.hostname) || '127.0.0.1'
  // Tauri's custom-scheme webview reports special hostnames; treat them as local.
  const normalized = host === 'tauri.localhost' ? 'localhost' : host
  return `http://${normalized}:8765`
}

const baseURL = deriveBaseURL()

export const api = axios.create({
  baseURL,
  timeout: 30000,
})

export const backendOrigin = baseURL

api.interceptors.response.use(
  (r) => r,
  (err) => {
    const msg = err?.response?.data?.detail || err?.message || 'request failed'
    return Promise.reject(new Error(msg))
  },
)

export async function pingBackend(timeoutMs = 1500): Promise<boolean> {
  const ctrl = new AbortController()
  const t = setTimeout(() => ctrl.abort(), timeoutMs)
  try {
    const resp = await fetch(`${baseURL}/health`, { signal: ctrl.signal })
    return resp.ok
  } catch {
    return false
  } finally {
    clearTimeout(t)
  }
}

export interface HealthInfo {
  status: string
  version: string
  ok: boolean
}

export async function fetchHealth(timeoutMs = 2000): Promise<HealthInfo | null> {
  const ctrl = new AbortController()
  const t = setTimeout(() => ctrl.abort(), timeoutMs)
  try {
    const resp = await fetch(`${baseURL}/health`, { signal: ctrl.signal })
    if (!resp.ok) return null
    return (await resp.json()) as HealthInfo
  } catch {
    return null
  } finally {
    clearTimeout(t)
  }
}
