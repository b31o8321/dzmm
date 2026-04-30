import { test, expect } from '@playwright/test'
import { waitForBackend } from './test-server'

test.beforeAll(async () => {
  await waitForBackend()
})

test('SSE 跑团端到端：从首页发送动作 → narrative 显示', async ({ page }) => {
  // 1. Open the app. Router will redirect first-time visitors to /welcome.
  await page.goto('/')
  await page.waitForLoadState('networkidle')

  // 2. Skip the onboarding tour.
  const skipBtn = page.getByRole('button', { name: /直接进主界面/ })
  if (await skipBtn.isVisible({ timeout: 5_000 }).catch(() => false)) {
    await skipBtn.click()
  }

  // 3. Browser mode skips the BootGate "choose mode" screen, but if it ever
  //    appears (e.g. running under Tauri webview in the future) click the
  //    local-only option.
  const localBtn = page.getByRole('button', { name: /仅本机使用/ })
  if (await localBtn.isVisible({ timeout: 3_000 }).catch(() => false)) {
    await localBtn.click()
  }

  // 4. Wait for the main layout — sidebar 跑团 link is the canonical signal.
  await expect(page.getByRole('link', { name: /跑团/ })).toBeVisible({
    timeout: 30_000,
  })

  // 5. Open the "new session" dialog.
  await page.getByRole('button', { name: /\+ 新开一局/ }).click()

  // 6. Fill the form. World/character/model defaults come from seed data.
  await page.getByLabel('存档名称').fill('e2e-test')
  await page.getByRole('button', { name: /开始跑团/ }).click()

  // 7. Land on the game view.
  await expect(page).toHaveURL(/\/play\/\d+/, { timeout: 10_000 })

  // 8. Send an action.
  await page.getByPlaceholder(/输入你的行动/).fill('环顾四周')
  await page.getByRole('button', { name: /^发送$/ }).click()

  // 9. The stub backend streams "霓虹光闪烁" — verify it lands in the log.
  await expect(page.locator('text=霓虹')).toBeVisible({ timeout: 30_000 })

  // 10. Status panel side: token counter must update from the SSE final chunk.
  const tokenStrip = page.locator('text=/tokens:\\s*\\d+/')
  await expect(tokenStrip).toBeVisible()
})
