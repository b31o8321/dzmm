import axios from 'axios'

// In Vite dev, `/api` is proxied to the backend by vite.config.ts.
// In built bundles (Tauri or plain `vite build`), there is no proxy — go direct.
const baseURL = import.meta.env.DEV ? '/api' : 'http://127.0.0.1:8765'

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
