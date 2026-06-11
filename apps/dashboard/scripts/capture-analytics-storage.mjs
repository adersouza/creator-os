import { chromium } from 'playwright';
import fs from 'node:fs/promises';
import path from 'node:path';

const baseUrl = process.env.PLAYWRIGHT_BASE_URL ?? 'http://127.0.0.1:3000';
const outputPath = process.env.ANALYTICS_STORAGE_STATE ?? 'tmp/analytics-storage-state.json';

await fs.mkdir(path.dirname(outputPath), { recursive: true });

const browser = await chromium.launch({ headless: false });
const context = await browser.newContext({
  viewport: { width: 1440, height: 1100 },
});
const page = await context.newPage();

console.log(`Opening ${baseUrl}/analytics?telemetry=1`);
console.log('Log in in the opened Chromium window. This script will save storage state once Analytics or Dashboard is visible.');

await page.goto(`${baseUrl}/analytics?telemetry=1`, { waitUntil: 'domcontentloaded' });

await page.waitForFunction(() => {
  const path = window.location.pathname;
  const heading = document.querySelector('h1')?.textContent?.trim().toLowerCase() ?? '';
  return path !== '/login' && (heading.includes('analytics') || heading.includes('dashboard'));
}, null, { timeout: 10 * 60 * 1000 });

await page.goto(`${baseUrl}/analytics?telemetry=1`, { waitUntil: 'domcontentloaded' });
await page.waitForLoadState('networkidle', { timeout: 20_000 }).catch(() => {});
await context.storageState({ path: outputPath });

console.log(`Saved authenticated storage state to ${outputPath}`);
await browser.close();
