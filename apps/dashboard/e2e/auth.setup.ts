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

  // Fill login form. The visual labels are not the textbox accessible names;
  // the controls expose their placeholders, so use the concrete input types.
  await page.locator('input[type="email"]').fill(email);
  await page.locator('input[type="password"]').fill(password);
  await page.getByRole('button', { name: 'Sign In', exact: true }).click();

  // Wait for redirect to dashboard
  await page.waitForURL(/dashboard/, { timeout: 15000 });
  await expect(page).toHaveURL(/dashboard/);

  fs.mkdirSync('e2e/.auth', { recursive: true });
  await page.context().storageState({ path: authFile });
});
