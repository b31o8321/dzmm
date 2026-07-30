import { test, expect } from '@playwright/test'
import { waitForBackend, waitForTurnRun } from './test-server'

test.beforeAll(async () => {
  await waitForBackend()
})

test('SSE 跑团端到端：从首页发送动作 → narrative 显示', async ({ page }) => {
  // Pre-set onboarding-completed in localStorage so the router beforeEach
  // doesn't bounce us to /welcome. Avoids brittle dependence on the welcome
  // page rendering timely in CI's cold cache.
  await page.addInitScript(() => {
    try {
      // The app store reads this key in loadTourCompleted() → stores/app.ts
      localStorage.setItem('dzmm.tour_completed', '1')
    } catch { /* ignore */ }
  })

  // 1. Open the app.
  await page.goto('/')

  // 2. If welcome page shows (localStorage key not picked up, store key changed,
  //    etc.), click "直接进主界面". waitFor actually waits; isVisible does not.
  const skipBtn = page.getByRole('button', { name: /直接进主界面/ })
  await skipBtn.waitFor({ state: 'visible', timeout: 12_000 }).then(
    () => skipBtn.click(),
    () => { /* not on welcome page — good */ },
  )

  // 3. BootGate's choose-mode screen appears only under Tauri; harmless skip.
  const localBtn = page.getByRole('button', { name: /仅本机使用/ })
  await localBtn.waitFor({ state: 'visible', timeout: 3_000 }).then(
    () => localBtn.click(),
    () => { /* not shown */ },
  )

  // 4. Wait for the main layout — sidebar 跑团 link is the canonical signal.
  await expect(page.getByRole('link', { name: /跑团/ })).toBeVisible({
    timeout: 30_000,
  })

  // 5. Open the "new session" dialog.
  await page.getByRole('button', { name: /\+ 新开一局/ }).click()

  // 6. Fill the form. el-select dropdowns need click-to-open + click-option.
  //    The dialog defaults to "screenplay" mode: 世界观 → 剧本 → GM模型 → 摘要模型.
  //    No "角色" field — screenplay already embeds the PC.
  await page.getByLabel('存档名称').fill('e2e-test')

  async function pickFirst(label: string) {
    // Click the el-select trigger, then drive selection via keyboard (Down +
    // Enter). Element-plus's popper has display animations that confuse
    // Playwright's visibility heuristics; keyboard navigation sidesteps it.
    const trigger = page.locator(`.el-form-item:has(label:text("${label}")) .el-select`)
    await trigger.click()
    await page.waitForTimeout(200)
    await page.keyboard.press('ArrowDown')
    await page.keyboard.press('Enter')
  }

  await pickFirst('世界观')
  // After world is selected, the backend fetches that world's screenplays async.
  // Give it a moment before the 剧本 dropdown is populated.
  await page.waitForTimeout(800)
  await pickFirst('剧本')
  await pickFirst('GM 模型')
  await pickFirst('摘要模型')

  // 7. Submit — goes directly to /play/:id (no generate page for screenplay flow).
  await page.getByRole('button', { name: /^开始跑团$/ }).click()
  await expect(page).toHaveURL(/\/play\/\d+/, { timeout: 15_000 })

  // 8. A fresh session automatically starts its opening turn. Wait for that
  // turn to finish so the response below belongs to the explicit player action.
  const narratives = page.getByText('你站在虚拟的街道上，霓虹光闪烁。')
  const sendButton = page.getByRole('button', { name: /^发送$/ })
  await expect(narratives).toHaveCount(1, { timeout: 30_000 })
  await expect(sendButton).toBeEnabled()

  // 9. Send an explicit player action.
  await page.getByPlaceholder(/输入你的行动/).fill('环顾四周')
  const createdRun = page.waitForResponse((response) =>
    response.request().method() === 'POST'
      && /\/sessions\/\d+\/turn-runs$/.test(response.url()),
  )
  await sendButton.click()
  const runResponse = await createdRun
  const run = await runResponse.json() as { run_id: string }
  const sessionId = Number(page.url().match(/\/play\/(\d+)/)?.[1])

  // 10. The stub backend streams "霓虹光闪烁" — verify it lands in the log.
  await expect(narratives).toHaveCount(2, { timeout: 30_000 })

  // 11. Status panel side: token counter must update from the SSE final chunk.
  const tokenStrip = page.locator('text=/tokens:\\s*\\d+/')
  await expect(tokenStrip).toBeVisible()

  const status = await waitForTurnRun(sessionId, run.run_id)
  expect(status.status).toBe('completed')
  expect(status.assistant_message_id).toBeTruthy()
  await expect(sendButton).toBeEnabled()

  // 12. Refresh/re-entry hydrates the committed turns instead of resubmitting.
  await page.reload()
  await expect(narratives).toHaveCount(2, { timeout: 30_000 })

  // 13. Force one replay gap after the detached producer completes. The Vue
  // client must recover from persisted messages/state without duplicating it.
  let injectGap = true
  await page.route('**/sessions/*/turn-runs/*/events', async (route) => {
    if (!injectGap) {
      await route.continue()
      return
    }
    injectGap = false
    const match = route.request().url().match(
      /\/sessions\/(\d+)\/turn-runs\/([^/]+)\/events/,
    )
    if (!match) {
      await route.continue()
      return
    }
    await waitForTurnRun(Number(match[1]), decodeURIComponent(match[2]))
    await route.fulfill({
      status: 409,
      contentType: 'application/json',
      body: JSON.stringify({ code: 'event_gap', message: 'test replay gap' }),
    })
  })
  await page.getByPlaceholder(/输入你的行动/).fill('再次观察')
  await page.getByRole('button', { name: /^发送$/ }).click()
  await expect(narratives).toHaveCount(3, { timeout: 30_000 })
})
