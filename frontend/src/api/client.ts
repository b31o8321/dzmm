import axios from 'axios'

// Always go direct to the backend. Vite's proxy buffers SSE responses,
// breaking the streaming /turn endpoint. Backend's CORS allows localhost
// dev origin via FastAPI defaults; for cross-origin we'd add CORSMiddleware.
const baseURL = 'http://127.0.0.1:8765'

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
