import { expect, test } from '@playwright/test'

const ADMIN_EMAIL = 'admin@wardenix.local'
const ADMIN_PASSWORD = 'changeme-admin'

async function login(page) {
  await page.goto('/login')
  await page.getByLabel('Email').fill(ADMIN_EMAIL)
  await page.getByLabel('Password').fill(ADMIN_PASSWORD)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByRole('heading', { name: 'Overview' })).toBeVisible()
}

test('login shows the overview with a verified audit chain', async ({ page }) => {
  await login(page)
  await expect(page.getByText('Pending approvals')).toBeVisible()
  await expect(page.getByText(/Chain verified/i)).toBeVisible()
})

test('audit log reports a verified hash chain', async ({ page }) => {
  await login(page)
  await page.getByRole('link', { name: 'Audit Log' }).click()
  await expect(page.getByText(/chain verified/i)).toBeVisible()
  // the audit table has rows
  await expect(page.locator('table tbody tr').first()).toBeVisible()
})

test('admin can create a policy via the UI', async ({ page }) => {
  await login(page)
  await page.getByRole('link', { name: 'Policies' }).click()
  const name = `e2e-ui-${Date.now()}`
  await page.getByRole('button', { name: 'New policy' }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByRole('textbox').first().fill(name)
  await dialog.getByRole('button', { name: 'Create' }).click()
  await expect(page.getByText(name)).toBeVisible()
})

test('approver can approve a pending request (seeded via a real MCP call)', async ({ page }) => {
  await login(page)
  await page.getByRole('link', { name: 'Approvals' }).click()

  const rows = page.locator('table tbody tr')
  const echoRows = rows.filter({ hasText: 'echo' })
  await expect(echoRows.first()).toBeVisible()
  const beforeEcho = await echoRows.count()

  await echoRows.first().getByRole('button', { name: 'Approve' }).click()

  // After approval the queue (DB-backed, refetched on the WS event) shrinks by one.
  await expect(echoRows).toHaveCount(beforeEcho - 1)
})

