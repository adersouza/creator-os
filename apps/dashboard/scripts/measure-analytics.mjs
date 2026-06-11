import { chromium } from 'playwright';

const baseUrl = process.env.PLAYWRIGHT_BASE_URL ?? 'http://127.0.0.1:3000';
const storageState = process.env.ANALYTICS_STORAGE_STATE;
const views = [
  { name: 'fleet', path: '/analytics?telemetry=1' },
  { name: 'instagram', path: '/analytics?p=ig&telemetry=1' },
  { name: 'threads', path: '/analytics?p=threads&telemetry=1' },
];

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({
  storageState,
  viewport: { width: 1440, height: 1100 },
});

for (const view of views) {
  const page = await context.newPage();
  const requests = [];
  const responses = [];

  page.on('request', (request) => {
    const url = new URL(request.url());
    if (url.origin === baseUrl || url.pathname.startsWith('/api/')) {
      requests.push({
        method: request.method(),
        path: `${url.pathname}${url.search}`,
        resourceType: request.resourceType(),
        startedAt: Date.now(),
      });
    }
  });

  page.on('response', async (response) => {
    const url = new URL(response.url());
    if (!url.pathname.startsWith('/api/')) return;
    responses.push({
      path: `${url.pathname}${url.search}`,
      status: response.status(),
      timing: response.request().timing(),
    });
  });

  const startedAt = Date.now();
  await page.goto(`${baseUrl}${view.path}`, { waitUntil: 'domcontentloaded' });
  await page.waitForLoadState('networkidle', { timeout: 20_000 }).catch(() => {});

  const title = await page.locator('h1').first().textContent().catch(() => null);
  const url = page.url();
  if (new URL(url).pathname === '/login') {
    console.log(JSON.stringify({
      view: view.name,
      url,
      title,
      authRequired: true,
      note: 'Provide ANALYTICS_STORAGE_STATE=/path/to/storage-state.json to measure authenticated Analytics.',
    }, null, 2));
    await page.close();
    continue;
  }
  const telemetry = await page
    .waitForFunction(() => window.__JUNO_ANALYTICS_TELEMETRY__ ?? null, null, {
      timeout: 12_000,
    })
    .then((handle) => handle.jsonValue())
    .catch(() => null);
  const nav = await page.evaluate(() => {
    const entry = performance.getEntriesByType('navigation')[0];
    if (!entry) return null;
    return {
      domContentLoadedMs: Math.round(entry.domContentLoadedEventEnd),
      loadMs: Math.round(entry.loadEventEnd),
      transferSize: entry.transferSize,
    };
  });

  const queryCount = await page.evaluate(() => {
    const snapshot = window.__JUNO_ANALYTICS_TELEMETRY__;
    return snapshot?.queries ?? null;
  });
  const jsHeap = await page.evaluate(() => performance.memory
    ? {
        usedMb: Math.round((performance.memory.usedJSHeapSize / 1024 / 1024) * 10) / 10,
        totalMb: Math.round((performance.memory.totalJSHeapSize / 1024 / 1024) * 10) / 10,
      }
    : null);

  const apiResponses = responses
    .map((response) => ({
      path: response.path,
      status: response.status,
      durationMs: Math.max(0, Math.round(response.timing.responseEnd - response.timing.startTime)),
    }))
    .sort((a, b) => b.durationMs - a.durationMs);

  console.log(JSON.stringify({
    view: view.name,
    url,
    title,
    routeWallMs: Date.now() - startedAt,
    nav,
    requestCount: requests.length,
    apiCount: apiResponses.length,
    queryCount,
    jsHeap,
    slowApi: apiResponses.filter((response) => response.durationMs >= 800).slice(0, 12),
    telemetry,
  }, null, 2));

  await page.close();
}

await browser.close();
