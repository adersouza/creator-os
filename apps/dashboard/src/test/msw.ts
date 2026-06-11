import { setupServer } from 'msw/node';
import { http, HttpResponse } from 'msw';

// Default handlers — every test starts from this baseline. Tests can override
// per-test with server.use(...). Unhandled requests throw in setup.ts so we
// see drift the moment a new endpoint starts firing.
export const handlers = [
  // Subscription: the app polls this for trial/tier on load.
  http.post('*/api/subscription*', () =>
    HttpResponse.json({ tier: 'free', daysRemaining: null, active: false }),
  ),
  // Push notifications vapid key — fetched on load when SW registers.
  http.get('*/api/push/vapid-key', () =>
    HttpResponse.json({ key: '' }),
  ),
  // Analytics feature-usage beacon — silent success.
  http.post('*/api/analytics/feature-usage', () =>
    HttpResponse.json({ ok: true }),
  ),
];

export const server = setupServer(...handlers);
