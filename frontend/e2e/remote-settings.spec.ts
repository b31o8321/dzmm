import { expect, test } from '@playwright/test'
import { waitForBackend } from './test-server'

test.beforeAll(async () => {
  await waitForBackend()
})

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem('dzmm.tour_completed', '1')
  })
})

test('局域网控制在浏览器模式保持只读，并可在刷新后恢复状态', async ({ page }) => {
  await page.goto('/#/settings')

  const card = page.getByTestId('remote-access-card')
  await expect(card).toBeVisible({ timeout: 30_000 })
  await expect(card.getByTestId('backend-mode')).toContainText('仅本机')
  await expect(card).toContainText('请在 dzmm Mac 应用中控制局域网访问')
  await expect(card.getByRole('button', { name: '开启局域网访问' })).toBeDisabled()

  await page.reload()
  await expect(page.getByTestId('remote-access-card')).toBeVisible({ timeout: 30_000 })
  await expect(page.getByTestId('backend-mode')).toContainText('仅本机')
})
