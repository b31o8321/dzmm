import { test, expect } from '@playwright/test'
import { waitForBackend } from './test-server'

test.beforeAll(async () => {
  await waitForBackend()
})

test('SSE 跑团端到端：从首页发送动作 → narrative 显示', async ({ page }) => {
  // Pre-set onboarding-completed in localStorage so the router beforeEach
  // doesn't bounce us to /welcome. Avoids brittle dependence on the welcome
  // page rendering timely in CI's cold cache.
  await page.addInitScript(() => {
    // Pinia persisted-state lives under various keys; set both the raw flag
    // and the structured pinia state. Done before any app code runs.
    try {
      // The app store reads this key in loadTourCompleted() → stores/app.ts
      localStorage.setItem('dzmm.tour_completed', '1')
    } catch { /* ignore */ }
  })

  // 1. Open the app.
  await page.goto('/')
  await page.waitForLoadState('networkidle')

  // 2. Belt-and-braces: if welcome still shows (e.g. store key changed),
  //    click the skip button. Generous 10s in case Vite is warming up.
  const skipBtn = page.getByRole('button', { name: /直接进主界面/ })
  if (await skipBtn.isVisible({ timeout: 10_000 }).catch(() => false)) {
    await skipBtn.click()
  }

  // 3. BootGate's choose-mode screen appears only under Tauri; harmless skip.
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

  // 6. Fill the form. el-select dropdowns need click-to-open + click-option.
  await page.getByLabel('存档名称').fill('e2e-test')

  async function pickFirst(label: string) {
    // Click the el-select trigger, then drive selection via keyboard (Down +
    // Enter). Element-plus's popper has display animations that confuse
    // Playwright's visibility heuristics; keyboard navigation sidesteps it.
    const trigger = page.locator(`.el-form-item:has(label:text("${label}")) .el-select`)
    await trigger.click()
    await page.waitForTimeout(150)
    await page.keyboard.press('ArrowDown')
    await page.keyboard.press('Enter')
  }

  await pickFirst('世界观')
  await pickFirst('角色')
  await pickFirst('GM 模型')
  await pickFirst('摘要模型')

  await page.getByRole('button', { name: /开始跑团/ }).click()

  // 7a. v0.1.0+: lands on generate loading page first
  //     (/sessions/generate/:id). Wait for outline to finish + the explicit
  //     "▶ 开始跑团" button on the preview phase.
  await expect(page).toHaveURL(/\/sessions\/generate\/\d+/, { timeout: 10_000 })
  await page.getByRole('button', { name: /▶ 开始跑团/ }).click({ timeout: 30_000 })

  // 7b. Now land on the actual game view.
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
