import { defineConfig } from '@playwright/test'

const backendPort = process.env.DZMM_E2E_BACKEND_PORT ?? '28765'
const frontendPort = process.env.DZMM_E2E_FRONTEND_PORT ?? '25173'
const backendURL = `http://127.0.0.1:${backendPort}`
const frontendURL = `http://127.0.0.1:${frontendPort}`

export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: process.env.CI ? 'github' : 'list',
  use: {
    baseURL: frontendURL,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  webServer: [
    {
      command: 'python e2e/mock_backend.py',
      url: `${backendURL}/health`,
      reuseExistingServer: false,
      timeout: 60_000,
      env: {
        PYTHONPATH: '../backend/src',
        DZMM_E2E_BACKEND_PORT: backendPort,
      },
      stdout: 'pipe',
      stderr: 'pipe',
    },
    {
      // Explicit --host 127.0.0.1 so CI Ubuntu (where `localhost` may resolve
      // to IPv6 ::1 only) binds an IPv4 socket Playwright can reach.
      command: `npx vite --host 127.0.0.1 --port ${frontendPort} --strictPort`,
      url: frontendURL,
      reuseExistingServer: false,
      timeout: 60_000,
      env: {
        VITE_API_BASE: backendURL,
      },
      stdout: 'pipe',
      stderr: 'pipe',
    },
  ],
  projects: [
    { name: 'chromium', use: { browserName: 'chromium' } },
  ],
})
