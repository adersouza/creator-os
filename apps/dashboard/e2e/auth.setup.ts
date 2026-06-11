import { test as setup, expect } from '@playwright/test';
import * as fs from 'fs';

const authFile = 'e2e/.auth/user.json';

setup('authenticate', async ({ page }) => {
  const email = process.env.E2E_EMAIL;
  const password = process.env.E2E_PASSWORD;

  if (!email || !password) {
    // No credentials — save empty state (unauthenticated tests still run)
    fs.mkdirSync('e2e/.auth', { recursive: true });
    await page.context().storageState({ path: authFile });
    return;
  }

  await page.goto('/login');
  await page.waitForLoadState('networkidle');

  // Fill login form
  await page.getByRole('textbox', { name: /email/i }).fill(email);
  await page.getByRole('textbox', { name: /password/i }).fill(password);
  await page.getByRole('button', { name: 'Sign In', exact: true }).click();

  // Wait for redirect to dashboard
  await page.waitForURL(/dashboard/, { timeout: 15000 });
  await expect(page).toHaveURL(/dashboard/);

  fs.mkdirSync('e2e/.auth', { recursive: true });
  await page.context().storageState({ path: authFile });
});
